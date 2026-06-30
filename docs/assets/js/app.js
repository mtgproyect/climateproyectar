(() => {
  "use strict";

  const DATA_BASE = "./data/web";
  const COL = Object.freeze({
    id: 0,
    name: 1,
    department: 2,
    province: 3,
    type: 4,
    forecastId: 5,
    stationId: 6,
    sourceStationId: 7,
    stationName: 8,
    distanceKm: 9,
    lat: 10,
    lon: 11,
  });
  const PERIODS = [
    ["early_morning", "Madrugada"],
    ["morning", "Mañana"],
    ["afternoon", "Tarde"],
    ["night", "Noche"],
  ];
  const RECENT_KEY = "clima-argentina-v2-recientes";

  const state = {
    manifest: null,
    rows: [],
    rowsById: new Map(),
    searchKeys: [],
    nameKeys: [],
    stations: {},
    suggestions: [],
    activeSuggestion: -1,
    selectedId: null,
  };

  const $ = (id) => document.getElementById(id);
  const elements = {
    localityCount: $("locality-count"),
    searchInput: $("search-input"),
    clearSearch: $("clear-search"),
    suggestions: $("suggestions"),
    searchStatus: $("search-status"),
    locationButton: $("location-button"),
    recentSearches: $("recent-searches"),
    recentList: $("recent-list"),
    resultSection: $("result-section"),
    emptyState: $("empty-state"),
    errorState: $("error-state"),
    errorMessage: $("error-message"),
    retryButton: $("retry-button"),
    shareButton: $("share-button"),
    alertContainer: $("alert-container"),
    locationTitle: $("location-title"),
    locationSubtitle: $("location-subtitle"),
    publicationDate: $("publication-date"),
    currentGlyph: $("current-glyph"),
    currentTemperature: $("current-temperature"),
    currentDescription: $("current-description"),
    feelsLike: $("feels-like"),
    stationSource: $("station-source"),
    observationBadge: $("observation-badge"),
    metricHumidity: $("metric-humidity"),
    metricWind: $("metric-wind"),
    metricPressure: $("metric-pressure"),
    metricVisibility: $("metric-visibility"),
    observationTime: $("observation-time"),
    forecastUpdated: $("forecast-updated"),
    forecastGrid: $("forecast-grid"),
    footerVersion: $("footer-version"),
  };

  function normalizeText(value) {
    return String(value || "")
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLocaleLowerCase("es-AR")
      .replace(/[^a-z0-9]+/g, " ")
      .trim()
      .replace(/\s+/g, " ");
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function formatNumber(value, maximumFractionDigits = 0) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) {
      return "—";
    }
    return new Intl.NumberFormat("es-AR", { maximumFractionDigits }).format(Number(value));
  }

  const dateUtils = window.ClimaDateUtils;
  if (!dateUtils) {
    throw new Error("No se cargaron las utilidades de fecha.");
  }
  const { parseDate, formatDateTime } = dateUtils;

  function weatherGlyph(description) {
    const text = normalizeText(description);
    if (/torment|electr/.test(text)) return "⛈️";
    if (/nieve|nevad|aguanieve/.test(text)) return "🌨️";
    if (/lluv|chaparr|precipit/.test(text)) return "🌧️";
    if (/niebla|neblina|bruma/.test(text)) return "🌫️";
    if (/ventos|viento fuerte|rafaga/.test(text)) return "💨";
    if (/despejado|soleado/.test(text)) return "☀️";
    if (/algo nublado|parcial/.test(text)) return "🌤️";
    if (/nublado|cubierto/.test(text)) return "☁️";
    return "🌡️";
  }

  async function fetchJson(url) {
    const response = await fetch(url, { cache: "no-cache" });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status} al cargar ${url}`);
    }
    return response.json();
  }

  function showFatalError(error) {
    console.error(error);
    elements.resultSection.hidden = true;
    elements.emptyState.hidden = true;
    elements.errorState.hidden = false;
    elements.errorMessage.textContent = error instanceof Error ? error.message : String(error);
    elements.searchStatus.textContent = "No se pudo cargar el catálogo.";
  }

  function localityLabel(row) {
    return [row[COL.name], row[COL.department], row[COL.province]].filter(Boolean).join(", ");
  }

  function buildIndexes() {
    state.rowsById.clear();
    state.searchKeys = new Array(state.rows.length);
    state.nameKeys = new Array(state.rows.length);
    state.rows.forEach((row, index) => {
      state.rowsById.set(Number(row[COL.id]), row);
      state.nameKeys[index] = normalizeText(row[COL.name]);
      state.searchKeys[index] = normalizeText(
        [row[COL.name], row[COL.department], row[COL.province]].filter(Boolean).join(" ")
      );
    });
  }

  function scoreRow(index, query, tokens) {
    const name = state.nameKeys[index];
    const full = state.searchKeys[index];
    if (name === query) return 0;
    if (name.startsWith(query)) return 1;
    if (tokens.every((token) => full.split(" ").some((word) => word.startsWith(token)))) return 2;
    if (name.includes(query)) return 3;
    if (tokens.every((token) => full.includes(token))) return 4;
    return null;
  }

  function searchRows(rawQuery) {
    const query = normalizeText(rawQuery);
    if (query.length < 2) return [];
    const tokens = query.split(" ").filter(Boolean);
    const matches = [];
    for (let index = 0; index < state.rows.length; index += 1) {
      const score = scoreRow(index, query, tokens);
      if (score === null) continue;
      matches.push({ row: state.rows[index], score });
    }
    matches.sort((a, b) => {
      if (a.score !== b.score) return a.score - b.score;
      return String(a.row[COL.name]).localeCompare(String(b.row[COL.name]), "es-AR");
    });
    return matches.slice(0, 10).map((match) => match.row);
  }

  function hideSuggestions() {
    state.activeSuggestion = -1;
    elements.suggestions.hidden = true;
    elements.suggestions.innerHTML = "";
    elements.searchInput.setAttribute("aria-expanded", "false");
  }

  function renderSuggestions(rows) {
    state.suggestions = rows;
    state.activeSuggestion = -1;
    elements.suggestions.innerHTML = "";
    if (!rows.length) {
      hideSuggestions();
      return;
    }
    rows.forEach((row, index) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "suggestion-item";
      button.setAttribute("role", "option");
      button.dataset.index = String(index);

      const text = document.createElement("span");
      const strong = document.createElement("strong");
      strong.textContent = row[COL.name] || "Localidad sin nombre";
      const secondary = document.createElement("span");
      secondary.textContent = [row[COL.department], row[COL.province]].filter(Boolean).join(" · ");
      text.append(strong, secondary);

      const type = document.createElement("span");
      type.className = "suggestion-type";
      type.textContent = row[COL.type] || "Localidad";
      button.append(text, type);
      button.addEventListener("click", () => selectLocality(Number(row[COL.id])));
      elements.suggestions.append(button);
    });
    elements.suggestions.hidden = false;
    elements.searchInput.setAttribute("aria-expanded", "true");
  }

  function setActiveSuggestion(index) {
    const items = [...elements.suggestions.querySelectorAll(".suggestion-item")];
    if (!items.length) return;
    state.activeSuggestion = (index + items.length) % items.length;
    items.forEach((item, itemIndex) => {
      const active = itemIndex === state.activeSuggestion;
      item.classList.toggle("active", active);
      item.setAttribute("aria-selected", active ? "true" : "false");
    });
    items[state.activeSuggestion].scrollIntoView({ block: "nearest" });
  }

  function getRecentIds() {
    try {
      const values = JSON.parse(localStorage.getItem(RECENT_KEY) || "[]");
      return Array.isArray(values) ? values.map(Number).filter(Number.isFinite) : [];
    } catch {
      return [];
    }
  }

  function saveRecent(localityId) {
    const ids = [localityId, ...getRecentIds().filter((id) => id !== localityId)].slice(0, 5);
    localStorage.setItem(RECENT_KEY, JSON.stringify(ids));
    renderRecentSearches();
  }

  function renderRecentSearches() {
    const rows = getRecentIds().map((id) => state.rowsById.get(id)).filter(Boolean);
    elements.recentList.innerHTML = "";
    rows.forEach((row) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "chip";
      button.textContent = row[COL.name];
      button.title = localityLabel(row);
      button.addEventListener("click", () => selectLocality(Number(row[COL.id])));
      elements.recentList.append(button);
    });
    elements.recentSearches.hidden = rows.length === 0;
  }

  function setUrl(localityId) {
    const url = new URL(window.location.href);
    url.searchParams.set("id", String(localityId));
    history.pushState({ localityId }, "", url);
  }

  function ageHours(value) {
    const date = parseDate(value);
    if (!date) return null;
    return Math.max(0, (Date.now() - date.getTime()) / 3600000);
  }

  function setObservation(row, stationRecord) {
    const payload = stationRecord?.payload || {};
    const temperature = payload.temperature;
    const description = payload.weather?.description || "Sin descripción";
    const observedAge = ageHours(payload.date);
    const delayed = observedAge !== null && observedAge > 4;

    elements.currentTemperature.textContent = temperature === null || temperature === undefined ? "—" : formatNumber(temperature, 1);
    elements.currentDescription.textContent = description;
    elements.currentGlyph.textContent = weatherGlyph(description);
    elements.feelsLike.textContent = payload.feels_like === null || payload.feels_like === undefined
      ? ""
      : `Sensación térmica: ${formatNumber(payload.feels_like, 1)} °C`;

    const distance = row[COL.distanceKm];
    const stationName = row[COL.stationName] || `Estación ${row[COL.stationId]}`;
    elements.stationSource.textContent = distance === null || distance === undefined
      ? `Observación de ${stationName}.`
      : `Observación de ${stationName}, estación asociada a ${formatNumber(distance, 1)} km.`;

    elements.observationBadge.textContent = delayed ? "Dato demorado" : "Dato reciente";
    elements.observationBadge.classList.toggle("delayed", delayed);
    elements.metricHumidity.textContent = payload.humidity === null || payload.humidity === undefined ? "—" : `${formatNumber(payload.humidity)} %`;

    const windParts = [];
    if (payload.wind?.direction) windParts.push(payload.wind.direction);
    if (payload.wind?.speed !== null && payload.wind?.speed !== undefined) windParts.push(`${formatNumber(payload.wind.speed)} km/h`);
    elements.metricWind.textContent = windParts.length ? windParts.join(" · ") : "—";
    elements.metricPressure.textContent = payload.pressure === null || payload.pressure === undefined ? "—" : `${formatNumber(payload.pressure, 1)} hPa`;
    elements.metricVisibility.textContent = payload.visibility === null || payload.visibility === undefined ? "—" : `${formatNumber(payload.visibility, 1)} km`;
    elements.observationTime.textContent = payload.date ? `Observado el ${formatDateTime(payload.date)}.` : "Horario de observación no informado.";
  }

  function dayDescription(day) {
    for (const [key] of [["afternoon"], ["morning"], ["night"], ["early_morning"]]) {
      const period = day[key];
      if (!period) continue;
      if (period.weather?.description) return period.weather.description;
      if (period.description) return period.description;
    }
    return "Pronóstico disponible";
  }

  function rangeText(value, suffix = "") {
    if (!Array.isArray(value) || value.length < 2) return null;
    if (value[0] === value[1]) return `${value[0]}${suffix}`;
    return `${value[0]}–${value[1]}${suffix}`;
  }

  function periodHtml(key, label, period) {
    if (!period) return "";
    const description = period.weather?.description || period.description || "Sin descripción";
    const meta = [];
    if (period.temperature !== null && period.temperature !== undefined) meta.push(`${formatNumber(period.temperature)} °C`);
    const rain = rangeText(period.rain_prob_range, "% lluvia");
    if (rain) meta.push(rain);
    const speed = rangeText(period.wind?.speed_range, " km/h");
    if (speed) meta.push(`Viento ${speed}`);
    if (period.wind?.direction) meta.push(period.wind.direction);
    const gust = rangeText(period.gust_range, " km/h");
    if (gust) meta.push(`Ráfagas ${gust}`);
    if (period.visibility) meta.push(`Visibilidad ${period.visibility}`);
    return `
      <div class="period">
        <div class="period-heading"><span>${escapeHtml(label)}</span><span>${weatherGlyph(description)}</span></div>
        <p>${escapeHtml(description)}</p>
        ${meta.length ? `<div class="period-meta">${meta.map((item) => `<span>${escapeHtml(item)}</span>`).join("")}</div>` : ""}
      </div>`;
  }

  function forecastCardHtml(day) {
    const date = parseDate(day.date);
    const weekday = date ? new Intl.DateTimeFormat("es-AR", { weekday: "long" }).format(date) : "Día";
    const dateLabel = date ? new Intl.DateTimeFormat("es-AR", { day: "numeric", month: "long" }).format(date) : (day.date || "—");
    const description = dayDescription(day);
    const periods = PERIODS.map(([key, label]) => periodHtml(key, label, day[key])).filter(Boolean).join("");
    return `
      <article class="forecast-card">
        <div class="forecast-summary">
          <p class="forecast-day">${escapeHtml(weekday)}</p>
          <p class="forecast-date">${escapeHtml(dateLabel)}</p>
          <div class="forecast-icon-row">
            <span class="forecast-glyph" aria-hidden="true">${weatherGlyph(description)}</span>
            <p class="forecast-description">${escapeHtml(description)}</p>
          </div>
          <div class="temperatures">
            <div class="temp-max"><span>Máx.</span><strong>${day.temp_max === null || day.temp_max === undefined ? "—" : `${formatNumber(day.temp_max)}°`}</strong></div>
            <div class="temp-min"><span>Mín.</span><strong>${day.temp_min === null || day.temp_min === undefined ? "—" : `${formatNumber(day.temp_min)}°`}</strong></div>
          </div>
        </div>
        ${periods ? `<details><summary>Ver detalle del día</summary><div class="period-list">${periods}</div></details>` : ""}
      </article>`;
  }

  function setForecast(forecastRecord) {
    const payload = forecastRecord?.payload || {};
    const days = Array.isArray(payload.forecast) ? payload.forecast : [];
    elements.forecastGrid.innerHTML = days.length
      ? days.map(forecastCardHtml).join("")
      : '<p class="muted-text">No hay días de pronóstico disponibles.</p>';
    elements.forecastUpdated.textContent = payload.updated
      ? `${forecastRecord.historical ? "Emitido" : "Actualizado"}: ${formatDateTime(payload.updated)}`
      : "Fecha de emisión no informada";

    elements.alertContainer.innerHTML = "";
    if (forecastRecord.status === "stale" || forecastRecord.historical) {
      const issueDate = payload.updated ? formatDateTime(payload.updated) : "fecha no informada";
      elements.alertContainer.innerHTML = `
        <div class="alert alert-warning" role="alert">
          <span aria-hidden="true">⚠️</span>
          <div>
            <strong>Último pronóstico oficial disponible</strong>
            <p>Fue emitido el ${escapeHtml(issueDate)}. Es un pronóstico histórico y puede no representar las condiciones actuales.</p>
          </div>
        </div>`;
    }
  }

  async function selectLocality(localityId, options = {}) {
    const row = state.rowsById.get(Number(localityId));
    if (!row) {
      elements.searchStatus.textContent = "La localidad solicitada no existe en el catálogo.";
      return;
    }
    state.selectedId = Number(localityId);
    hideSuggestions();
    elements.searchInput.value = row[COL.name] || "";
    elements.clearSearch.hidden = false;
    elements.searchStatus.textContent = localityLabel(row);
    elements.emptyState.hidden = true;
    elements.errorState.hidden = true;
    elements.resultSection.hidden = false;
    elements.shareButton.hidden = false;

    if (!options.skipUrl) setUrl(localityId);
    saveRecent(Number(localityId));

    elements.locationTitle.textContent = row[COL.name] || "Localidad";
    elements.locationSubtitle.textContent = [row[COL.type], row[COL.department], row[COL.province]].filter(Boolean).join(" · ");
    elements.publicationDate.textContent = formatDateTime(state.manifest.generated_at);
    setObservation(row, state.stations[String(row[COL.stationId])]);
    elements.forecastGrid.innerHTML = '<p class="muted-text">Cargando pronóstico…</p>';
    elements.resultSection.scrollIntoView({ behavior: options.instant ? "auto" : "smooth", block: "start" });

    try {
      const version = encodeURIComponent(state.manifest.generated_at || "1");
      const forecast = await fetchJson(`${DATA_BASE}/pronosticos/${Number(row[COL.forecastId])}.json?v=${version}`);
      if (state.selectedId !== Number(localityId)) return;
      setForecast(forecast);
    } catch (error) {
      console.error(error);
      elements.forecastGrid.innerHTML = '<div class="alert alert-warning"><div><strong>No se pudo cargar el pronóstico.</strong><p>La observación sigue disponible. Reintentá más tarde.</p></div></div>';
    }
  }

  function nearestLocality(latitude, longitude) {
    const toRadians = (degrees) => degrees * Math.PI / 180;
    let best = null;
    let bestDistance = Infinity;
    for (const row of state.rows) {
      const lat = Number(row[COL.lat]);
      const lon = Number(row[COL.lon]);
      if (!Number.isFinite(lat) || !Number.isFinite(lon)) continue;
      const dLat = toRadians(lat - latitude);
      const dLon = toRadians(lon - longitude);
      const a = Math.sin(dLat / 2) ** 2
        + Math.cos(toRadians(latitude)) * Math.cos(toRadians(lat)) * Math.sin(dLon / 2) ** 2;
      const distance = 6371 * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
      if (distance < bestDistance) {
        bestDistance = distance;
        best = row;
      }
    }
    return best;
  }

  function useCurrentLocation() {
    if (!navigator.geolocation) {
      elements.searchStatus.textContent = "Tu navegador no permite obtener la ubicación.";
      return;
    }
    elements.locationButton.disabled = true;
    elements.searchStatus.textContent = "Buscando la localidad más cercana…";
    navigator.geolocation.getCurrentPosition(
      (position) => {
        elements.locationButton.disabled = false;
        const row = nearestLocality(position.coords.latitude, position.coords.longitude);
        if (!row) {
          elements.searchStatus.textContent = "No encontramos una localidad cercana.";
          return;
        }
        selectLocality(Number(row[COL.id]));
      },
      () => {
        elements.locationButton.disabled = false;
        elements.searchStatus.textContent = "No fue posible acceder a tu ubicación.";
      },
      { enableHighAccuracy: false, timeout: 10000, maximumAge: 300000 },
    );
  }

  async function shareCurrent() {
    const row = state.rowsById.get(state.selectedId);
    if (!row) return;
    const data = {
      title: `Clima en ${row[COL.name]}`,
      text: `Pronóstico y observación para ${localityLabel(row)}.`,
      url: window.location.href,
    };
    try {
      if (navigator.share) {
        await navigator.share(data);
      } else if (navigator.clipboard) {
        await navigator.clipboard.writeText(data.url);
        elements.searchStatus.textContent = "Enlace copiado.";
      }
    } catch (error) {
      if (error?.name !== "AbortError") console.error(error);
    }
  }

  function bindEvents() {
    let timer = null;
    elements.searchInput.addEventListener("input", () => {
      const value = elements.searchInput.value;
      elements.clearSearch.hidden = !value;
      clearTimeout(timer);
      timer = setTimeout(() => {
        const rows = searchRows(value);
        renderSuggestions(rows);
        if (normalizeText(value).length < 2) {
          elements.searchStatus.textContent = "Escribí al menos dos caracteres.";
        } else {
          elements.searchStatus.textContent = rows.length ? `${rows.length} coincidencias principales.` : "No encontramos coincidencias.";
        }
      }, 90);
    });
    elements.searchInput.addEventListener("keydown", (event) => {
      if (elements.suggestions.hidden) return;
      if (event.key === "ArrowDown") {
        event.preventDefault();
        setActiveSuggestion(state.activeSuggestion + 1);
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        setActiveSuggestion(state.activeSuggestion - 1);
      } else if (event.key === "Enter" && state.activeSuggestion >= 0) {
        event.preventDefault();
        const row = state.suggestions[state.activeSuggestion];
        if (row) selectLocality(Number(row[COL.id]));
      } else if (event.key === "Escape") {
        hideSuggestions();
      }
    });
    elements.clearSearch.addEventListener("click", () => {
      elements.searchInput.value = "";
      elements.clearSearch.hidden = true;
      hideSuggestions();
      elements.searchInput.focus();
      elements.searchStatus.textContent = "Escribí al menos dos caracteres.";
    });
    document.addEventListener("click", (event) => {
      if (!event.target.closest(".search-box")) hideSuggestions();
    });
    elements.locationButton.addEventListener("click", useCurrentLocation);
    elements.retryButton.addEventListener("click", () => window.location.reload());
    elements.shareButton.addEventListener("click", shareCurrent);
    window.addEventListener("popstate", () => {
      const id = Number(new URL(window.location.href).searchParams.get("id"));
      if (Number.isFinite(id) && state.rowsById.has(id)) {
        selectLocality(id, { skipUrl: true, instant: true });
      }
    });
  }

  async function init() {
    bindEvents();
    try {
      state.manifest = await fetchJson(`${DATA_BASE}/manifiesto.json?t=${Date.now()}`);
      const version = encodeURIComponent(state.manifest.generated_at || "1");
      const [localities, stations] = await Promise.all([
        fetchJson(`${DATA_BASE}/${state.manifest.files.localities.path}?v=${version}`),
        fetchJson(`${DATA_BASE}/${state.manifest.files.stations.path}?v=${version}`),
      ]);
      state.rows = Array.isArray(localities.records) ? localities.records : [];
      state.stations = stations.records || {};
      buildIndexes();
      elements.localityCount.textContent = new Intl.NumberFormat("es-AR").format(state.rows.length);
      elements.searchStatus.textContent = `${new Intl.NumberFormat("es-AR").format(state.rows.length)} localidades disponibles.`;
      elements.footerVersion.textContent = `Publicación ${formatDateTime(state.manifest.generated_at)}`;
      renderRecentSearches();

      const requestedId = Number(new URL(window.location.href).searchParams.get("id"));
      if (Number.isFinite(requestedId) && state.rowsById.has(requestedId)) {
        await selectLocality(requestedId, { skipUrl: true, instant: true });
      }
    } catch (error) {
      showFatalError(error);
    }
  }

  init();
})();
