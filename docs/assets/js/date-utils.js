(() => {
  "use strict";

  function parseDate(value) {
    if (!value) return null;
    const text = String(value).trim();
    const dateOnly = /^(\d{4})-(\d{2})-(\d{2})$/.exec(text);
    if (dateOnly) {
      const [, year, month, day] = dateOnly;
      const date = new Date(
        Number(year),
        Number(month) - 1,
        Number(day),
        12,
        0,
        0,
        0,
      );
      return Number.isNaN(date.getTime()) ? null : date;
    }

    const normalized = text.includes("T")
      ? text
      : text.replace(" ", "T");
    const date = new Date(normalized);
    return Number.isNaN(date.getTime()) ? null : date;
  }

  function formatDateTime(value) {
    const date = parseDate(value);
    if (!date) return value || "—";
    return new Intl.DateTimeFormat("es-AR", {
      day: "numeric",
      month: "long",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    }).format(date);
  }

  const api = Object.freeze({ parseDate, formatDateTime });
  const target = typeof window !== "undefined" ? window : globalThis;
  target.ClimaDateUtils = api;
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
})();
