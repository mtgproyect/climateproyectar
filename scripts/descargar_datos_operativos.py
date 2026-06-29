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

TOKEN_PAGE = "https://ws2.smn.gob.ar/pronostico"
FORECAST_URL = "https://ws1.smn.gob.ar/v1/forecast/location/{location_id}"
WEATHER_URL = "https://ws1.smn.gob.ar/v1/weather/location/{location_id}"

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
    response = session.get(
        FORECAST_URL.format(location_id=reference_id),
        headers=api_headers(token),
        timeout=30,
    )
    payload = response_json(
        response,
        f"el pronóstico {reference_id}",
    )
    return validate_forecast_payload(payload, reference_id)


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
    successes = sum(
        isinstance(records.get(target_id), dict)
        and records[target_id].get("status") == "success"
        for target_id in target_ids
    )
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
    errors = sum(item["errors"] for item in stats)

    state = {
        "schema_version": 1,
        "generated_at": utc_now(),
        "totals": {
            "query_keys": total,
            "success": success,
            "errors": errors,
            "pending": total - success,
        },
        "partitions": stats,
        "last_run": current_run,
    }
    write_json_atomic(STATE_FILE, state)

    error_rows: list[dict[str, Any]] = []
    for item in stats:
        path = ROOT / item["cache_file"]
        payload = load_optional(
            path,
            empty_cache(item["mode"], item["shard"]),
        )
        records = payload.get("records", {})
        if not isinstance(records, dict):
            continue
        for query_id, record in records.items():
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
    args = parser.parse_args()

    if not 1 <= args.batch_size <= 250:
        raise ValueError("--batch-size debe estar entre 1 y 250.")
    if args.sleep_seconds < 1.0:
        raise ValueError(
            "--sleep-seconds no puede ser menor que 1.0."
        )
    if not 1 <= args.max_attempts <= 5:
        raise ValueError("--max-attempts debe estar entre 1 y 5.")

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
        if not isinstance(previous, dict):
            eligible.append(target)
            continue
        if previous.get("status") == "success":
            continue
        attempts = as_int(previous.get("attempts")) or 0
        if attempts < args.max_attempts:
            eligible.append(target)

    selected = eligible[: args.batch_size]
    print(f"Modo: {args.mode}")
    print(f"Shard: {args.shard}")
    print(f"Claves totales: {len(targets)}")
    print(f"Claves elegibles: {len(eligible)}")
    print(f"Seleccionadas: {len(selected)}")

    session = requests.Session()
    token = get_token(session)

    attempted = 0
    completed = 0
    successes = 0
    request_errors = 0
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
            payload, token = request_with_refresh(
                session,
                token,
                function,
                target,
            )
            records[str(query_id)] = {
                **target,
                "status": "success",
                "attempts": attempts + 1,
                "fetched_at": utc_now(),
                "payload": payload,
            }
            successes += 1
            print("  OK")
        except Exception as error:
            request_errors += 1
            status_code = (
                error.status_code
                if isinstance(error, ApiError)
                else None
            )
            records[str(query_id)] = {
                **target,
                "status": "error",
                "attempts": attempts + 1,
                "last_attempt_at": utc_now(),
                "error": error_record(error),
            }
            print(f"  ERROR: {error}")

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

    current_run = {
        "mode": args.mode,
        "shard": args.shard,
        "configured_batch_size": args.batch_size,
        "attempted_queries": attempted,
        "completed_queries": completed,
        "successful_queries": successes,
        "request_errors": request_errors,
        "stopped_reason": stopped_reason,
    }
    build_global_state(current_run=current_run)

    print("Descarga operativa terminada.")
    print(f"Completadas: {completed}")
    print(f"Exitosas: {successes}")
    print(f"Errores: {request_errors}")
    print(f"Estado: {STATE_FILE}")


if __name__ == "__main__":
    main()
