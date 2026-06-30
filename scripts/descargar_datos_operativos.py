from __future__ import annotations

import argparse
import json
import math
import os
import re
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import requests


ROOT = Path(__file__).resolve().parents[1]

PARTITIONS_FILE = ROOT / "docs" / "data" / "particiones_operativas.json"
FORECAST_GROUPS_FILE = ROOT / "docs" / "data" / "grupos_pronostico.json"
STATION_GROUPS_FILE = ROOT / "docs" / "data" / "grupos_estaciones.json"

CACHE_DIR = ROOT / "data" / "cache" / "operativo"
STATE_FILE = ROOT / "docs" / "data" / "estado_descarga_operativa.json"
ERRORS_FILE = ROOT / "docs" / "data" / "errores_descarga_operativa.json"
LOCAL_LEGACY_FILE = (
    ROOT
    / "data"
    / "fuentes"
    / "pronosticos_historicos_antartida.json"
)

TOKEN_PAGE = "https://ws2.smn.gob.ar/pronostico"
FORECAST_URL = "https://ws1.smn.gob.ar/v1/forecast/location/{location_id}"
LEGACY_FORECAST_URL = (
    "https://ws.smn.gob.ar/forecast/location/{location_id}"
)
WEATHER_URL = "https://ws1.smn.gob.ar/v1/weather/location/{location_id}"

LEGACY_FALLBACK_STATUS = {
    404,
    500,
    502,
    503,
    504,
}

TRANSIENT_HTTP_STATUS = {
    404,
    408,
    425,
    429,
    500,
    502,
    503,
    504,
}

BASE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "es-AR,es;q=0.9",
}


class TokenRejected(RuntimeError):
    pass


class ApiError(RuntimeError):
    def __init__(
        self,
        message: str,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def as_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def as_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_optional(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return load_json(path)


def write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
        sort_keys=False,
    ) + "\n"

    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        delete=False,
    ) as handle:
        handle.write(serialized)
        temporary_path = Path(handle.name)

    os.replace(temporary_path, path)


def cache_file(mode: str, shard: int) -> Path:
    if mode == "forecast":
        return CACHE_DIR / f"pronosticos_shard_{shard}.json"
    return CACHE_DIR / f"estaciones_shard_{shard}.json"


def empty_cache(mode: str, shard: int) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "mode": mode,
        "shard": shard,
        "generated_at": None,
        "records": {},
    }


def get_token(session: requests.Session) -> str:
    response = session.get(
        TOKEN_PAGE,
        headers={
            **BASE_HEADERS,
            "Accept": "text/html,application/xhtml+xml",
        },
        timeout=30,
    )
    response.raise_for_status()

    patterns = [
        (
            r"localStorage\.setItem\(\s*[\"']token[\"']\s*,\s*"
            r"[\"']([^\"']+)[\"']\s*\)"
        ),
        r"localStorage\.setItem\(\s*`token`\s*,\s*`([^`]+)`\s*\)",
    ]
    for pattern in patterns:
        match = re.search(pattern, response.text)
        if match:
            token = match.group(1).strip()
            if token.count(".") == 2:
                return token

    raise RuntimeError("No se pudo obtener el token temporal del SMN.")


def api_headers(token: str) -> dict[str, str]:
    return {
        **BASE_HEADERS,
        "Accept": "application/json",
        "Authorization": f"JWT {token}",
        "Origin": "https://ws2.smn.gob.ar",
        "Referer": "https://ws2.smn.gob.ar/",
    }


def response_json(
    response: requests.Response,
    description: str,
) -> Any:
    if response.status_code in {401, 403}:
        raise TokenRejected(
            f"El token fue rechazado al consultar {description}."
        )
    if not response.ok:
        raise ApiError(
            f"HTTP {response.status_code} al consultar {description}.",
            response.status_code,
        )
    try:
        return response.json()
    except ValueError as error:
        raise ApiError(
            f"{description} no devolvió JSON válido.",
            response.status_code,
        ) from error


def request_with_refresh(
    session: requests.Session,
    token: str,
    function: Callable[
        [requests.Session, str, dict[str, Any]],
        dict[str, Any],
    ],
    target: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    try:
        return function(session, token, target), token
    except TokenRejected:
        refreshed = get_token(session)
        return function(session, refreshed, target), refreshed



def is_transient_error(error: Exception) -> bool:
    if isinstance(error, TokenRejected):
        return True
    if isinstance(error, ApiError):
        return error.status_code in TRANSIENT_HTTP_STATUS
    return isinstance(error, requests.RequestException)


def request_with_retries(
    session: requests.Session,
    token: str,
    function: Callable[
        [requests.Session, str, dict[str, Any]],
        dict[str, Any],
    ],
    target: dict[str, Any],
    *,
    max_http_attempts: int,
    retry_base_seconds: float,
) -> tuple[dict[str, Any], str, int]:
    current_token = token
    last_error: Exception | None = None

    for attempt in range(1, max_http_attempts + 1):
        try:
            payload, current_token = request_with_refresh(
                session,
                current_token,
                function,
                target,
            )
            return payload, current_token, attempt
        except Exception as error:
            last_error = error

            if (
                not is_transient_error(error)
                or attempt >= max_http_attempts
            ):
                raise

            delay = retry_base_seconds * (2 ** (attempt - 1))
            status_code = (
                error.status_code
                if isinstance(error, ApiError)
                else None
            )
            print(
                "  Reintento "
                f"{attempt + 1}/{max_http_attempts} "
                f"en {delay:.1f}s "
                f"(HTTP {status_code!r})"
            )
            time.sleep(delay)

            if isinstance(error, TokenRejected):
                current_token = get_token(session)

    assert last_error is not None
    raise last_error



def legacy_headers() -> dict[str, str]:
    return {
        **BASE_HEADERS,
        "Accept": "application/json",
        "Origin": "https://www.smn.gob.ar",
        "Referer": "https://www.smn.gob.ar/",
    }


def normalize_legacy_forecast(
    payload: Any,
    reference_id: int,
) -> dict[str, Any]:
    if not isinstance(payload, list) or not payload:
        raise ApiError(
            "El endpoint histórico no devolvió pronósticos."
        )

    candidates: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        if as_int(item.get("location_id")) != reference_id:
            continue
        forecast = item.get("forecast")
        if not isinstance(forecast, (dict, list)):
            continue
        candidates.append(item)

    if not candidates:
        raise ApiError(
            "El endpoint histórico no devolvió un registro válido "
            f"para {reference_id}."
        )

    def candidate_key(item: dict[str, Any]) -> tuple[int, str]:
        timestamp = as_int(item.get("timestamp")) or 0
        date_time = str(item.get("date_time") or "")
        return timestamp, date_time

    selected = max(candidates, key=candidate_key)
    raw_forecast = selected.get("forecast")

    if isinstance(raw_forecast, list):
        days = [
            item for item in raw_forecast
            if isinstance(item, dict)
        ]
    else:
        assert isinstance(raw_forecast, dict)

        def forecast_key(value: tuple[str, Any]) -> tuple[int, str]:
            key, item = value
            numeric = as_int(key)
            date = (
                str(item.get("date") or "")
                if isinstance(item, dict)
                else ""
            )
            return (
                numeric if numeric is not None else 10**9,
                date,
            )

        days = [
            item
            for _, item in sorted(
                raw_forecast.items(),
                key=forecast_key,
            )
            if isinstance(item, dict)
        ]

    if not days:
        raise ApiError(
            "El pronóstico histórico no contiene días válidos."
        )

    for day in days:
        if not day.get("date"):
            raise ApiError(
                "Un día del pronóstico histórico no contiene fecha."
            )

    return {
        "source": "smn_legacy_forecast",
        "historical": True,
        "updated": selected.get("date_time"),
        "location": {
            "id": reference_id,
        },
        "type": "legacy_location",
        "forecast": days,
        "legacy_metadata": {
            "_id": selected.get("_id"),
            "timestamp": selected.get("timestamp"),
            "date_time": selected.get("date_time"),
            "location_id": selected.get("location_id"),
        },
    }


def fetch_legacy_forecast(
    session: requests.Session,
    reference_id: int,
) -> dict[str, Any]:
    response = session.get(
        LEGACY_FORECAST_URL.format(location_id=reference_id),
        headers=legacy_headers(),
        timeout=30,
    )
    payload = response_json(
        response,
        f"el pronóstico histórico {reference_id}",
    )
    return normalize_legacy_forecast(payload, reference_id)



def local_legacy_forecast(
    reference_id: int,
) -> dict[str, Any] | None:
    payload = load_optional(
        LOCAL_LEGACY_FILE,
        {
            "records": {},
        },
    )
    records = payload.get("records")
    if not isinstance(records, dict):
        return None

    raw = records.get(str(reference_id))
    if isinstance(raw, dict):
        items = [raw]
    elif isinstance(raw, list):
        items = raw
    else:
        return None

    result = normalize_legacy_forecast(items, reference_id)
    result["source"] = "smn_legacy_local_seed"
    result["historical"] = True
    result["legacy_metadata"]["seed_file"] = str(
        LOCAL_LEGACY_FILE.relative_to(ROOT)
    )
    return result


def legacy_record_from_normalized_payload(
    reference_id: int,
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    if not payload.get("historical"):
        return None

    forecast = payload.get("forecast")
    metadata = payload.get("legacy_metadata")
    if not isinstance(forecast, list) or not forecast:
        return None
    if not isinstance(metadata, dict):
        return None

    raw_forecast = {
        str(index): day
        for index, day in enumerate(forecast)
        if isinstance(day, dict)
    }
    if not raw_forecast:
        return None

    return {
        "_id": metadata.get("_id"),
        "timestamp": metadata.get("timestamp"),
        "date_time": metadata.get("date_time")
        or payload.get("updated"),
        "location_id": reference_id,
        "forecast": raw_forecast,
    }


def sync_local_legacy_file() -> int:
    source = load_optional(
        LOCAL_LEGACY_FILE,
        {
            "schema_version": 1,
            "records": {},
        },
    )
    records = source.get("records")
    if not isinstance(records, dict):
        records = {}

    before = len(records)
    for shard in (1, 2):
        path = cache_file("forecast", shard)
        cache = load_optional(
            path,
            empty_cache("forecast", shard),
        )
        cached_records = cache.get("records")
        if not isinstance(cached_records, dict):
            continue

        for query_id, cached in cached_records.items():
            if not isinstance(cached, dict):
                continue
            if cached.get("status") != "stale":
                continue
            reference_id = as_int(query_id)
            payload = cached.get("payload")
            if reference_id is None or not isinstance(payload, dict):
                continue

            raw = legacy_record_from_normalized_payload(
                reference_id,
                payload,
            )
            if raw is not None:
                records[str(reference_id)] = [raw]

    source["schema_version"] = 1
    source["generated_at"] = utc_now()
    source["source"] = (
        "Respuestas oficiales del endpoint histórico del SMN, "
        "capturadas o sincronizadas desde el caché operativo."
    )
    source["expected_antartic_references"] = [
        10806,
        10810,
        10811,
        10814,
        10817,
        10818,
    ]
    source["records"] = {
        key: records[key]
        for key in sorted(
            records,
            key=lambda value: int(value),
        )
    }
    source["count"] = len(source["records"])
    write_json_atomic(LOCAL_LEGACY_FILE, source)
    return len(records) - before


def validate_forecast_payload(
    payload: Any,
    reference_id: int,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ApiError("El pronóstico no es un objeto JSON.")

    location = payload.get("location")
    forecast = payload.get("forecast")
    if not isinstance(location, dict):
        raise ApiError("El pronóstico no contiene location.")
    if as_int(location.get("id")) != reference_id:
        raise ApiError(
            "El pronóstico devolvió un ID distinto: "
            f"{location.get('id')!r}; se esperaba {reference_id}."
        )
    if not isinstance(forecast, list) or not forecast:
        raise ApiError("El pronóstico no contiene días válidos.")

    return payload


def fetch_forecast(
    session: requests.Session,
    token: str,
    target: dict[str, Any],
) -> dict[str, Any]:
    reference_id = int(target["query_id"])

    try:
        response = session.get(
            FORECAST_URL.format(location_id=reference_id),
            headers=api_headers(token),
            timeout=30,
        )
        payload = response_json(
            response,
            f"el pronóstico moderno {reference_id}",
        )
        result = validate_forecast_payload(
            payload,
            reference_id,
        )
        result.setdefault("source", "smn_modern_forecast")
        result.setdefault("historical", False)
        return result
    except ApiError as error:
        if error.status_code not in LEGACY_FALLBACK_STATUS:
            raise

        print(
            "  El endpoint moderno no respondió; "
            "se consulta el pronóstico histórico."
        )
        try:
            return fetch_legacy_forecast(
                session,
                reference_id,
            )
        except (
            ApiError,
            requests.RequestException,
        ) as legacy_error:
            local = local_legacy_forecast(reference_id)
            if local is not None:
                print(
                    "  El endpoint histórico remoto no respondió; "
                    "se usa el respaldo local oficial."
                )
                return local
            raise legacy_error


def validate_weather_payload(
    payload: Any,
    *,
    representative_id: int,
    station_number: int,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ApiError("El tiempo actual no es un objeto JSON.")

    location = payload.get("location")
    if not isinstance(location, dict):
        raise ApiError("El tiempo actual no contiene location.")
    if as_int(location.get("id")) != representative_id:
        raise ApiError(
            "El tiempo actual devolvió una localidad distinta: "
            f"{location.get('id')!r}; se esperaba {representative_id}."
        )

    returned_station = as_int(payload.get("station_id"))
    if returned_station != station_number:
        raise ApiError(
            "El tiempo actual devolvió station_id "
            f"{returned_station!r}; se esperaba {station_number}."
        )

    if payload.get("temperature") is None and not payload.get("weather"):
        raise ApiError("El tiempo actual está vacío.")

    return payload


def fetch_station(
    session: requests.Session,
    token: str,
    target: dict[str, Any],
) -> dict[str, Any]:
    representative_id = int(target["representative_locality_id"])
    station_number = int(target["query_id"])

    response = session.get(
        WEATHER_URL.format(location_id=representative_id),
        headers=api_headers(token),
        timeout=30,
    )
    payload = response_json(
        response,
        f"la estación {station_number}",
    )
    return validate_weather_payload(
        payload,
        representative_id=representative_id,
        station_number=station_number,
    )


def partition_ids(
    partitions: dict[str, Any],
    mode: str,
    shard: int,
) -> list[int]:
    section_name = "forecast" if mode == "forecast" else "stations"
    section = partitions.get(section_name)
    if not isinstance(section, dict):
        raise RuntimeError(
            f"No existe la sección {section_name!r}."
        )

    values = section.get("partitions")
    if not isinstance(values, list):
        raise RuntimeError("Las particiones no contienen una lista válida.")

    for item in values:
        if not isinstance(item, dict):
            continue
        if as_int(item.get("shard")) == shard:
            group_ids = item.get("group_ids")
            if not isinstance(group_ids, list):
                raise RuntimeError(
                    f"El shard {shard} no contiene group_ids."
                )
            result = [
                value
                for raw in group_ids
                if (value := as_int(raw)) is not None
            ]
            if len(result) != len(group_ids):
                raise RuntimeError(
                    f"El shard {shard} contiene IDs inválidos."
                )
            return result

    raise RuntimeError(
        f"No existe el shard {shard} para el modo {mode}."
    )


def group_index(path: Path, id_field: str) -> dict[int, dict[str, Any]]:
    payload = load_json(path)
    groups = payload.get("groups")
    if not isinstance(groups, list):
        raise RuntimeError(f"{path} no contiene groups válidos.")

    result: dict[int, dict[str, Any]] = {}
    for group in groups:
        if not isinstance(group, dict):
            continue
        group_id = as_int(group.get(id_field))
        if group_id is not None:
            result[group_id] = group
    return result


def build_targets(
    *,
    mode: str,
    shard: int,
) -> list[dict[str, Any]]:
    partitions = load_json(PARTITIONS_FILE)
    ids = partition_ids(partitions, mode, shard)

    if mode == "forecast":
        groups = group_index(
            FORECAST_GROUPS_FILE,
            "forecast_reference_id",
        )
        targets = []
        for reference_id in ids:
            group = groups.get(reference_id)
            if group is None:
                raise RuntimeError(
                    f"Falta el grupo de pronóstico {reference_id}."
                )
            targets.append(
                {
                    "query_id": reference_id,
                    "locality_count": as_int(
                        group.get("locality_count")
                    ),
                }
            )
        return targets

    groups = group_index(STATION_GROUPS_FILE, "station_number")
    targets = []
    for station_number in ids:
        group = groups.get(station_number)
        if group is None:
            raise RuntimeError(
                f"Falta el grupo de estación {station_number}."
            )
        representative = as_int(
            group.get("representative_locality_id")
        )
        if representative is None:
            raise RuntimeError(
                "La estación "
                f"{station_number} no tiene localidad representante."
            )
        targets.append(
            {
                "query_id": station_number,
                "representative_locality_id": representative,
                "expected_station_name": group.get("station_name"),
                "locality_count": as_int(
                    group.get("locality_count")
                ),
            }
        )
    return targets


def error_record(error: Exception) -> dict[str, Any]:
    return {
        "type": type(error).__name__,
        "message": str(error),
        "status_code": (
            error.status_code
            if isinstance(error, ApiError)
            else None
        ),
    }


def save_cache(path: Path, cache: dict[str, Any]) -> None:
    cache["generated_at"] = utc_now()
    write_json_atomic(path, cache)


def cache_statistics(
    *,
    mode: str,
    shard: int,
    targets: list[dict[str, Any]],
) -> dict[str, Any]:
    path = cache_file(mode, shard)
    payload = load_optional(path, empty_cache(mode, shard))
    records = payload.get("records")
    if not isinstance(records, dict):
        records = {}

    target_ids = {str(item["query_id"]) for item in targets}
    fresh = sum(
        isinstance(records.get(target_id), dict)
        and records[target_id].get("status") == "success"
        for target_id in target_ids
    )
    stale = sum(
        isinstance(records.get(target_id), dict)
        and records[target_id].get("status") == "stale"
        for target_id in target_ids
    )
    successes = fresh + stale
    errors = sum(
        isinstance(records.get(target_id), dict)
        and records[target_id].get("status") == "error"
        for target_id in target_ids
    )

    return {
        "mode": mode,
        "shard": shard,
        "total": len(targets),
        "success": successes,
        "fresh": fresh,
        "stale": stale,
        "errors": errors,
        "pending": len(targets) - successes,
        "cache_file": str(path.relative_to(ROOT)),
    }


def build_global_state(
    *,
    current_run: dict[str, Any],
) -> None:
    partitions = load_json(PARTITIONS_FILE)

    forecast_partitions = (
        partitions.get("forecast", {}).get("partitions", [])
    )
    station_partitions = (
        partitions.get("stations", {}).get("partitions", [])
    )

    stats: list[dict[str, Any]] = []
    for item in forecast_partitions:
        shard = as_int(item.get("shard"))
        if shard is None:
            continue
        stats.append(
            cache_statistics(
                mode="forecast",
                shard=shard,
                targets=build_targets(
                    mode="forecast",
                    shard=shard,
                ),
            )
        )

    for item in station_partitions:
        shard = as_int(item.get("shard"))
        if shard is None:
            continue
        stats.append(
            cache_statistics(
                mode="stations",
                shard=shard,
                targets=build_targets(
                    mode="stations",
                    shard=shard,
                ),
            )
        )

    total = sum(item["total"] for item in stats)
    success = sum(item["success"] for item in stats)
    fresh = sum(item["fresh"] for item in stats)
    stale = sum(item["stale"] for item in stats)
    errors = sum(item["errors"] for item in stats)

    state = {
        "schema_version": 1,
        "generated_at": utc_now(),
        "totals": {
            "query_keys": total,
            "success": success,
            "fresh": fresh,
            "stale": stale,
            "errors": errors,
            "pending": total - success,
        },
        "partitions": stats,
        "last_run": current_run,
    }
    write_json_atomic(STATE_FILE, state)

    error_rows: list[dict[str, Any]] = []
    for item in stats:
        active_ids = {
            str(target["query_id"])
            for target in build_targets(
                mode=item["mode"],
                shard=item["shard"],
            )
        }
        path = ROOT / item["cache_file"]
        payload = load_optional(
            path,
            empty_cache(item["mode"], item["shard"]),
        )
        records = payload.get("records", {})
        if not isinstance(records, dict):
            continue
        for query_id, record in records.items():
            if str(query_id) not in active_ids:
                continue
            if (
                isinstance(record, dict)
                and record.get("status") == "error"
            ):
                error_rows.append(
                    {
                        "mode": item["mode"],
                        "shard": item["shard"],
                        "query_id": as_int(query_id),
                        "attempts": as_int(record.get("attempts")),
                        "last_attempt_at": record.get(
                            "last_attempt_at"
                        ),
                        "error": record.get("error"),
                    }
                )

    write_json_atomic(
        ERRORS_FILE,
        {
            "schema_version": 1,
            "generated_at": utc_now(),
            "count": len(error_rows),
            "errors": error_rows,
        },
    )



def parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        result = datetime.fromisoformat(text)
    except ValueError:
        return None
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def record_age_hours(record: dict[str, Any]) -> float | None:
    value = (
        record.get("fetched_at")
        or record.get("last_attempt_at")
        or record.get("last_refresh_attempt_at")
    )
    parsed = parse_datetime(value)
    if parsed is None:
        return None
    delta = datetime.now(timezone.utc) - parsed
    return max(0.0, delta.total_seconds() / 3600.0)


def is_target_eligible(
    previous: Any,
    *,
    refresh_scope: str,
    max_attempts: int,
    max_age_hours: float,
) -> bool:
    if not isinstance(previous, dict):
        return True

    status = str(previous.get("status") or "")
    attempts = as_int(previous.get("attempts")) or 0

    if refresh_scope == "all":
        return True

    if refresh_scope == "stale":
        return status == "stale"

    if refresh_scope == "expired":
        if status not in {"success", "stale"}:
            return attempts < max_attempts
        age = record_age_hours(previous)
        return age is None or age >= max_age_hours

    if refresh_scope != "pending":
        raise ValueError(
            f"Ámbito de actualización desconocido: {refresh_scope!r}"
        )

    if status in {"success", "stale"}:
        return False
    return attempts < max_attempts


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Descarga pronósticos y observaciones por claves "
            "operativas, con caché reanudable."
        )
    )
    parser.add_argument(
        "--mode",
        choices=("forecast", "stations"),
        required=True,
    )
    parser.add_argument("--shard", type=int, required=True)
    parser.add_argument("--batch-size", type=int, default=25)
    parser.add_argument("--sleep-seconds", type=float, default=1.0)
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument(
        "--http-attempts",
        type=int,
        default=4,
        help=(
            "Cantidad máxima de intentos HTTP dentro de una misma "
            "ejecución para errores temporales."
        ),
    )
    parser.add_argument(
        "--retry-base-seconds",
        type=float,
        default=2.0,
        help="Espera base para el retroceso exponencial.",
    )
    parser.add_argument(
        "--refresh-scope",
        choices=("pending", "stale", "expired", "all"),
        default="pending",
        help=(
            "pending: solo faltantes/errores; stale: históricos o "
            "conservados; expired: registros vencidos; all: todo el shard."
        ),
    )
    parser.add_argument(
        "--max-age-hours",
        type=float,
        default=6.0,
        help=(
            "Antigüedad mínima para --refresh-scope expired."
        ),
    )
    args = parser.parse_args()

    if not 1 <= args.batch_size <= 250:
        raise ValueError("--batch-size debe estar entre 1 y 250.")
    if args.sleep_seconds < 1.0:
        raise ValueError(
            "--sleep-seconds no puede ser menor que 1.0."
        )
    if not 1 <= args.max_attempts <= 5:
        raise ValueError("--max-attempts debe estar entre 1 y 5.")
    if not 1 <= args.http_attempts <= 8:
        raise ValueError("--http-attempts debe estar entre 1 y 8.")
    if args.retry_base_seconds < 0.5:
        raise ValueError(
            "--retry-base-seconds no puede ser menor que 0.5."
        )
    if args.max_age_hours <= 0:
        raise ValueError(
            "--max-age-hours debe ser mayor que cero."
        )

    targets = build_targets(mode=args.mode, shard=args.shard)
    path = cache_file(args.mode, args.shard)
    cache = load_optional(
        path,
        empty_cache(args.mode, args.shard),
    )
    records = cache.setdefault("records", {})
    if not isinstance(records, dict):
        raise RuntimeError("El archivo de caché tiene formato inválido.")

    eligible: list[dict[str, Any]] = []
    for target in targets:
        query_id = str(target["query_id"])
        previous = records.get(query_id)
        if is_target_eligible(
            previous,
            refresh_scope=args.refresh_scope,
            max_attempts=args.max_attempts,
            max_age_hours=args.max_age_hours,
        ):
            eligible.append(target)

    selected = eligible[: args.batch_size]
    print(f"Modo: {args.mode}")
    print(f"Shard: {args.shard}")
    print(f"Ámbito: {args.refresh_scope}")
    if args.refresh_scope == "expired":
        print(f"Antigüedad mínima: {args.max_age_hours} horas")
    print(f"Claves totales: {len(targets)}")
    print(f"Claves elegibles: {len(eligible)}")
    print(f"Seleccionadas: {len(selected)}")

    session = requests.Session()
    token = get_token(session)

    attempted = 0
    completed = 0
    successes = 0
    fresh_queries = 0
    stale_queries = 0
    request_errors = 0
    http_attempts_total = 0
    stopped_reason: str | None = None

    function = (
        fetch_forecast
        if args.mode == "forecast"
        else fetch_station
    )

    for position, target in enumerate(selected, start=1):
        query_id = int(target["query_id"])
        previous = records.get(str(query_id))
        attempts = (
            as_int(previous.get("attempts"))
            if isinstance(previous, dict)
            else 0
        ) or 0

        print(
            f"[{position}/{len(selected)}] "
            f"{args.mode} {query_id}"
        )
        attempted += 1

        try:
            payload, token, http_attempts = request_with_retries(
                session,
                token,
                function,
                target,
                max_http_attempts=args.http_attempts,
                retry_base_seconds=args.retry_base_seconds,
            )
            http_attempts_total += http_attempts

            previous_payload = (
                previous.get("payload")
                if isinstance(previous, dict)
                else None
            )
            is_historical = bool(payload.get("historical"))
            status = "stale" if is_historical else "success"

            records[str(query_id)] = {
                **target,
                "status": status,
                "data_source": payload.get("source"),
                "historical": is_historical,
                "attempts": attempts + 1,
                "http_attempts_last_run": http_attempts,
                "fetched_at": utc_now(),
                "previous_payload_preserved": (
                    previous_payload is not None
                ),
                "payload": payload,
            }
            successes += 1
            if is_historical:
                stale_queries += 1
                print(
                    "  OK HISTÓRICO "
                    f"({http_attempts} intento(s) HTTP)"
                )
            else:
                fresh_queries += 1
                print(f"  OK ({http_attempts} intento(s) HTTP)")
        except Exception as error:
            request_errors += 1
            http_attempts_total += args.http_attempts
            status_code = (
                error.status_code
                if isinstance(error, ApiError)
                else None
            )

            previous_payload = (
                previous.get("payload")
                if isinstance(previous, dict)
                else None
            )
            previous_fetched_at = (
                previous.get("fetched_at")
                if isinstance(previous, dict)
                else None
            )

            if previous_payload is not None:
                records[str(query_id)] = {
                    **target,
                    "status": "stale",
                    "data_source": (
                        previous.get("data_source")
                        if isinstance(previous, dict)
                        else previous_payload.get("source")
                    ),
                    "historical": bool(
                        (
                            previous.get("historical")
                            if isinstance(previous, dict)
                            else None
                        )
                        or previous_payload.get("historical")
                    ),
                    "attempts": attempts + 1,
                    "fetched_at": previous_fetched_at,
                    "last_refresh_attempt_at": utc_now(),
                    "last_refresh_error": error_record(error),
                    "payload": previous_payload,
                }
                print(
                    "  TEMPORAL: se conserva el último "
                    "pronóstico exitoso"
                )
            else:
                records[str(query_id)] = {
                    **target,
                    "status": "error",
                    "attempts": attempts + 1,
                    "last_attempt_at": utc_now(),
                    "error": error_record(error),
                }
                print(f"  ERROR TEMPORAL: {error}")

            if status_code == 429:
                stopped_reason = (
                    "El servidor respondió HTTP 429; se detuvo el lote."
                )

        completed += 1
        save_cache(path, cache)

        if stopped_reason is not None:
            break

        if position < len(selected):
            time.sleep(args.sleep_seconds)

    save_cache(path, cache)
    synchronized_local_records = sync_local_legacy_file()

    current_run = {
        "mode": args.mode,
        "shard": args.shard,
        "configured_batch_size": args.batch_size,
        "refresh_scope": args.refresh_scope,
        "max_age_hours": args.max_age_hours,
        "attempted_queries": attempted,
        "completed_queries": completed,
        "successful_queries": successes,
        "fresh_queries": fresh_queries,
        "stale_queries": stale_queries,
        "request_errors": request_errors,
        "http_attempts_total": http_attempts_total,
        "synchronized_local_records": (
            synchronized_local_records
        ),
        "stopped_reason": stopped_reason,
    }
    build_global_state(current_run=current_run)

    print("Descarga operativa terminada.")
    print(f"Completadas: {completed}")
    print(f"Resueltas: {successes}")
    print(f"Actuales: {fresh_queries}")
    print(f"Históricas: {stale_queries}")
    print(f"Errores: {request_errors}")
    print(f"Intentos HTTP totales: {http_attempts_total}")
    print(
        "Registros históricos sincronizados: "
        f"{synchronized_local_records}"
    )
    print(f"Estado: {STATE_FILE}")


if __name__ == "__main__":
    main()
