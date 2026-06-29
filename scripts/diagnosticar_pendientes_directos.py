from __future__ import annotations

import argparse
import re
import time
from datetime import datetime, timezone
from typing import Any, Callable

import requests

from common import (
    ROOT,
    as_int,
    clean_text,
    load_json,
    normalized_text,
    write_json_atomic,
)


TOKEN_PAGE = "https://ws2.smn.gob.ar/pronostico"
FORECAST_URL = "https://ws1.smn.gob.ar/v1/forecast/location/{location_id}"
WEATHER_URL = "https://ws1.smn.gob.ar/v1/weather/location/{location_id}"

UNRESOLVED_FILE = ROOT / "docs" / "data" / "georef_no_resueltos.json"
GEOREF_CACHE_FILE = ROOT / "data" / "cache" / "busquedas_georef.json"
DIRECT_CACHE_FILE = ROOT / "data" / "cache" / "pendientes_directos.json"
RESULT_FILE = ROOT / "docs" / "data" / "pendientes_directos_resultados.json"
STATE_FILE = ROOT / "docs" / "data" / "estado_diagnostico_directo.json"

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


def empty_direct_cache() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "generated_at": None,
        "token_page": TOKEN_PAGE,
        "forecast_endpoint": FORECAST_URL,
        "weather_endpoint": WEATHER_URL,
        "locations": {},
    }


def load_optional(
    path,
    default: dict[str, Any],
) -> dict[str, Any]:
    if not path.exists():
        return default
    payload = load_json(path)
    if not isinstance(payload, dict):
        raise RuntimeError(f"{path} no contiene un objeto JSON válido.")
    return payload


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
        r"localStorage\.setItem\(\s*[\"']token[\"']\s*,\s*[\"']([^\"']+)[\"']\s*\)",
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
            status_code=response.status_code,
        )
    try:
        return response.json()
    except ValueError as error:
        raise ApiError(
            f"{description} no devolvió JSON válido.",
            status_code=response.status_code,
        ) from error


def request_forecast(
    session: requests.Session,
    token: str,
    location_id: int,
) -> dict[str, Any]:
    response = session.get(
        FORECAST_URL.format(location_id=location_id),
        headers=api_headers(token),
        timeout=30,
    )
    payload = response_json(
        response,
        f"el pronóstico del ID {location_id}",
    )
    if not isinstance(payload, dict):
        raise ApiError("El pronóstico no es un objeto JSON.")
    forecast = payload.get("forecast")
    if not isinstance(forecast, list) or not forecast:
        raise ApiError("La respuesta no contiene un pronóstico válido.")
    return payload


def request_weather(
    session: requests.Session,
    token: str,
    location_id: int,
) -> dict[str, Any]:
    response = session.get(
        WEATHER_URL.format(location_id=location_id),
        headers=api_headers(token),
        timeout=30,
    )
    payload = response_json(
        response,
        f"el tiempo actual del ID {location_id}",
    )
    if not isinstance(payload, dict):
        raise ApiError("El tiempo actual no es un objeto JSON.")
    if payload.get("temperature") is None and not payload.get("weather"):
        raise ApiError("La respuesta del tiempo actual está vacía.")
    return payload


def request_with_token_refresh(
    session: requests.Session,
    token: str,
    function: Callable[
        [requests.Session, str, int],
        dict[str, Any],
    ],
    location_id: int,
) -> tuple[dict[str, Any], str]:
    try:
        return function(session, token, location_id), token
    except TokenRejected:
        refreshed = get_token(session)
        return function(session, refreshed, location_id), refreshed


def sanitize_value(
    value: Any,
    *,
    depth: int = 0,
) -> Any:
    if depth > 3:
        return "<profundidad omitida>"
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, child in value.items():
            if key == "forecast" and isinstance(child, list):
                result[key] = {
                    "days": len(child),
                    "first_date": (
                        child[0].get("date")
                        if child and isinstance(child[0], dict)
                        else None
                    ),
                    "last_date": (
                        child[-1].get("date")
                        if child and isinstance(child[-1], dict)
                        else None
                    ),
                }
            else:
                result[str(key)] = sanitize_value(
                    child,
                    depth=depth + 1,
                )
        return result
    if isinstance(value, list):
        return [
            sanitize_value(item, depth=depth + 1)
            for item in value[:10]
        ]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def collect_station_candidates(
    value: Any,
    path: str = "",
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []

    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            normalized_key = normalized_text(key).replace(" ", "_")
            if any(
                token in normalized_key
                for token in (
                    "station",
                    "estacion",
                    "wmo",
                    "icao",
                )
            ):
                candidates.append(
                    {
                        "path": child_path,
                        "value": sanitize_value(child),
                    }
                )
            candidates.extend(
                collect_station_candidates(child, child_path)
            )
    elif isinstance(value, list):
        for index, child in enumerate(value[:20]):
            child_path = f"{path}[{index}]"
            candidates.extend(
                collect_station_candidates(child, child_path)
            )

    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in candidates:
        marker = repr(candidate)
        if marker not in seen:
            seen.add(marker)
            unique.append(candidate)
    return unique


def summarize_forecast(payload: dict[str, Any]) -> dict[str, Any]:
    forecast = payload.get("forecast")
    return {
        "available": isinstance(forecast, list) and bool(forecast),
        "days": len(forecast) if isinstance(forecast, list) else 0,
        "location": sanitize_value(payload.get("location")),
        "top_level_keys": sorted(str(key) for key in payload),
        "station_candidates": collect_station_candidates(payload),
    }


def summarize_weather(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "available": (
            payload.get("temperature") is not None
            or bool(payload.get("weather"))
        ),
        "date": payload.get("date"),
        "temperature": payload.get("temperature"),
        "weather": sanitize_value(payload.get("weather")),
        "location": sanitize_value(payload.get("location")),
        "top_level_keys": sorted(str(key) for key in payload),
        "station_candidates": collect_station_candidates(payload),
    }


def parse_georef_row(row: Any) -> dict[str, Any] | None:
    if not isinstance(row, list) or len(row) < 10:
        return None
    location_id = as_int(row[0])
    if location_id is None:
        return None
    return {
        "id": location_id,
        "name": clean_text(row[1]),
        "department": clean_text(row[2]),
        "province": clean_text(row[3]),
        "station_number": as_int(row[4]),
        "forecast_reference_id": as_int(row[5]),
        "lon": row[6],
        "lat": row[7],
        "distance_km": row[8],
        "station_name": clean_text(row[9]),
    }


def exact_georef_match(
    location: dict[str, Any],
    georef_cache: dict[str, Any],
) -> dict[str, Any] | None:
    location_id = as_int(location.get("id"))
    query = clean_text(location.get("query")) or clean_text(
        location.get("name")
    )
    if location_id is None or not query:
        return None

    searches = georef_cache.get("searches")
    if not isinstance(searches, dict):
        return None

    entry = searches.get(normalized_text(query))
    if not isinstance(entry, dict):
        return None

    rows = entry.get("results")
    if not isinstance(rows, list):
        return None

    for row in rows:
        parsed = parse_georef_row(row)
        if parsed and parsed["id"] == location_id:
            return parsed
    return None


def classify_georef_match(
    match: dict[str, Any] | None,
) -> str:
    if match is None:
        return "exact_id_absent"
    has_station = as_int(match.get("station_number")) is not None
    has_forecast = (
        as_int(match.get("forecast_reference_id")) is not None
    )
    if has_station and has_forecast:
        return "exact_complete"
    if has_station:
        return "forecast_missing"
    if has_forecast:
        return "station_missing"
    return "station_and_forecast_missing"


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


def save_cache(cache: dict[str, Any]) -> None:
    cache["generated_at"] = utc_now()
    write_json_atomic(DIRECT_CACHE_FILE, cache)


def build_outputs(
    unresolved: list[dict[str, Any]],
    direct_records: dict[str, Any],
    georef_cache: dict[str, Any],
    *,
    configured_size: int,
    attempted: int,
    completed: int,
    stopped_reason: str | None,
) -> None:
    results: list[dict[str, Any]] = []
    for location in unresolved:
        location_id = as_int(location.get("id"))
        if location_id is None:
            continue
        direct = direct_records.get(str(location_id))
        match = exact_georef_match(location, georef_cache)
        results.append(
            {
                "id": location_id,
                "name": location.get("name"),
                "department": location.get("department"),
                "province": location.get("province"),
                "georef_exact_match": match,
                "georef_classification": classify_georef_match(match),
                "direct_probe": direct,
            }
        )

    attempted_results = [
        item
        for item in results
        if isinstance(item.get("direct_probe"), dict)
    ]
    forecast_available = sum(
        bool(
            item["direct_probe"]
            .get("forecast", {})
            .get("available")
        )
        for item in attempted_results
    )
    weather_available = sum(
        bool(
            item["direct_probe"]
            .get("weather", {})
            .get("available")
        )
        for item in attempted_results
    )
    both_available = sum(
        bool(
            item["direct_probe"]
            .get("forecast", {})
            .get("available")
        )
        and bool(
            item["direct_probe"]
            .get("weather", {})
            .get("available")
        )
        for item in attempted_results
    )

    generated_at = utc_now()
    write_json_atomic(
        RESULT_FILE,
        {
            "schema_version": 1,
            "generated_at": generated_at,
            "count": len(results),
            "locations": results,
        },
    )
    write_json_atomic(
        STATE_FILE,
        {
            "schema_version": 1,
            "generated_at": generated_at,
            "unresolved_total": len(unresolved),
            "directly_tested_total": len(attempted_results),
            "forecast_available": forecast_available,
            "weather_available": weather_available,
            "forecast_and_weather_available": both_available,
            "forecast_unavailable_or_error": (
                len(attempted_results) - forecast_available
            ),
            "weather_unavailable_or_error": (
                len(attempted_results) - weather_available
            ),
            "georef_exact_id_absent": sum(
                item["georef_classification"] == "exact_id_absent"
                for item in results
            ),
            "georef_exact_partial": sum(
                item["georef_classification"]
                in {
                    "forecast_missing",
                    "station_missing",
                    "station_and_forecast_missing",
                }
                for item in results
            ),
            "last_batch": {
                "configured_size": configured_size,
                "attempted_ids": attempted,
                "completed_ids": completed,
                "stopped_reason": stopped_reason,
            },
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Diagnostica los IDs no resueltos consultando directamente "
            "los endpoints de pronóstico y tiempo actual."
        )
    )
    parser.add_argument("--batch-size", type=int, default=25)
    parser.add_argument("--sleep-seconds", type=float, default=1.0)
    parser.add_argument("--max-attempts", type=int, default=2)
    args = parser.parse_args()

    if not 1 <= args.batch_size <= 100:
        raise ValueError("--batch-size debe estar entre 1 y 100.")
    if args.sleep_seconds < 0.5:
        raise ValueError(
            "--sleep-seconds no puede ser menor que 0.5."
        )
    if not 1 <= args.max_attempts <= 3:
        raise ValueError("--max-attempts debe estar entre 1 y 3.")

    unresolved_payload = load_json(UNRESOLVED_FILE)
    unresolved = unresolved_payload.get("locations")
    if not isinstance(unresolved, list):
        raise RuntimeError(
            "georef_no_resueltos.json no contiene una lista válida."
        )
    unresolved = [
        item for item in unresolved if isinstance(item, dict)
    ]

    georef_cache = load_optional(
        GEOREF_CACHE_FILE,
        {"searches": {}},
    )
    direct_cache = load_optional(
        DIRECT_CACHE_FILE,
        empty_direct_cache(),
    )
    direct_records = direct_cache.setdefault("locations", {})
    if not isinstance(direct_records, dict):
        raise RuntimeError(
            "pendientes_directos.json tiene un formato inválido."
        )

    eligible: list[dict[str, Any]] = []
    for location in unresolved:
        location_id = as_int(location.get("id"))
        if location_id is None:
            continue
        previous = direct_records.get(str(location_id))
        if not isinstance(previous, dict):
            eligible.append(location)
            continue
        attempts = as_int(previous.get("attempts")) or 0
        if (
            previous.get("status") == "transient_error"
            and attempts < args.max_attempts
        ):
            eligible.append(location)

    selected = eligible[: args.batch_size]
    print(f"Pendientes totales: {len(unresolved)}")
    print(f"IDs elegibles: {len(eligible)}")
    print(f"IDs seleccionados: {len(selected)}")

    session = requests.Session()
    token = get_token(session)
    attempted = 0
    completed = 0
    stopped_reason: str | None = None

    for position, location in enumerate(selected, start=1):
        location_id = int(location["id"])
        previous = direct_records.get(str(location_id))
        attempts = (
            as_int(previous.get("attempts"))
            if isinstance(previous, dict)
            else 0
        ) or 0

        print(
            f"[{position}/{len(selected)}] "
            f"{location.get('name')} — ID {location_id}"
        )
        attempted += 1

        forecast_summary: dict[str, Any]
        weather_summary: dict[str, Any]
        transient = False
        rate_limited = False

        try:
            forecast_payload, token = request_with_token_refresh(
                session,
                token,
                request_forecast,
                location_id,
            )
            forecast_summary = summarize_forecast(forecast_payload)
        except Exception as error:
            forecast_summary = {
                "available": False,
                "error": error_record(error),
            }
            status_code = (
                error.status_code
                if isinstance(error, ApiError)
                else None
            )
            transient = transient or (
                status_code is None or status_code >= 500
            )
            rate_limited = rate_limited or status_code == 429

        time.sleep(args.sleep_seconds)

        try:
            weather_payload, token = request_with_token_refresh(
                session,
                token,
                request_weather,
                location_id,
            )
            weather_summary = summarize_weather(weather_payload)
        except Exception as error:
            weather_summary = {
                "available": False,
                "error": error_record(error),
            }
            status_code = (
                error.status_code
                if isinstance(error, ApiError)
                else None
            )
            transient = transient or (
                status_code is None or status_code >= 500
            )
            rate_limited = rate_limited or status_code == 429

        direct_records[str(location_id)] = {
            "id": location_id,
            "name": location.get("name"),
            "department": location.get("department"),
            "province": location.get("province"),
            "tested_at": utc_now(),
            "attempts": attempts + 1,
            "status": (
                "rate_limited"
                if rate_limited
                else "transient_error"
                if transient
                else "completed"
            ),
            "forecast": forecast_summary,
            "weather": weather_summary,
        }
        save_cache(direct_cache)
        completed += 1

        print(
            "  Pronóstico: "
            f"{forecast_summary.get('available', False)}; "
            "tiempo actual: "
            f"{weather_summary.get('available', False)}"
        )

        if rate_limited:
            stopped_reason = (
                "El servidor respondió HTTP 429; se detuvo el lote."
            )
            break

        if position < len(selected):
            time.sleep(args.sleep_seconds)

    save_cache(direct_cache)
    build_outputs(
        unresolved,
        direct_records,
        georef_cache,
        configured_size=args.batch_size,
        attempted=attempted,
        completed=completed,
        stopped_reason=stopped_reason,
    )

    print("Diagnóstico directo terminado.")
    print(f"IDs probados en esta ejecución: {completed}")
    print(f"Resultados: {RESULT_FILE}")
    print(f"Estado: {STATE_FILE}")


if __name__ == "__main__":
    main()
