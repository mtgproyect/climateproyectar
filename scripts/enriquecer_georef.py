from __future__ import annotations

import argparse
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from common import (
    ROOT,
    as_float,
    as_int,
    clean_text,
    load_json,
    normalized_text,
    write_json_atomic,
)


ENDPOINT = "https://ws1.smn.gob.ar/v1/georef/location/search"
MASTER_FILE = ROOT / "docs" / "data" / "catalogo_maestro.json"
CACHE_FILE = ROOT / "data" / "cache" / "busquedas_georef.json"
GEOREF_FILE = ROOT / "data" / "fuentes" / "localidades_georef.json"
STATE_FILE = ROOT / "docs" / "data" / "estado_enriquecimiento.json"
UNRESOLVED_FILE = ROOT / "docs" / "data" / "georef_no_resueltos.json"

USER_AGENT = "climateproyectar-georef-enrichment/1.0"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def empty_cache() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "endpoint": ENDPOINT,
        "updated_at": None,
        "searches": {},
    }


def empty_georef_source() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "source": "SMN georef location search",
        "endpoint": ENDPOINT,
        "generated_at": None,
        "count": 0,
        "locations": {},
    }


def load_optional(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return default
    payload = load_json(path)
    if not isinstance(payload, dict):
        raise RuntimeError(f"{path} no contiene un objeto JSON válido.")
    return payload


def parse_georef_row(row: Any) -> dict[str, Any] | None:
    if not isinstance(row, list) or len(row) < 10:
        return None

    locality_id = as_int(row[0])
    name = clean_text(row[1])
    if locality_id is None or not name:
        return None

    return {
        "id": locality_id,
        "name": name,
        "department": clean_text(row[2]),
        "province": clean_text(row[3]),
        "station_number": as_int(row[4]),
        "forecast_reference_id": as_int(row[5]),
        "lon": as_float(row[6]),
        "lat": as_float(row[7]),
        "distance_km": as_float(row[8]),
        "station_name": clean_text(row[9]),
        "source": "SMN georef location search",
    }


def merge_non_null(
    current: dict[str, Any] | None,
    incoming: dict[str, Any],
) -> dict[str, Any]:
    result = dict(current or {})
    for key, value in incoming.items():
        if value is not None:
            result[key] = value
        elif key not in result:
            result[key] = None
    return result


def source_locations(
    payload: dict[str, Any],
) -> dict[int, dict[str, Any]]:
    raw_locations = payload.get("locations", {})
    result: dict[int, dict[str, Any]] = {}

    if isinstance(raw_locations, dict):
        iterable = raw_locations.values()
    elif isinstance(raw_locations, list):
        iterable = raw_locations
    else:
        iterable = []

    for item in iterable:
        if not isinstance(item, dict):
            continue
        locality_id = as_int(item.get("id"))
        if locality_id is not None:
            result[locality_id] = item
    return result


def master_locations() -> list[dict[str, Any]]:
    payload = load_json(MASTER_FILE)
    locations = payload.get("localities")
    if not isinstance(locations, list):
        raise RuntimeError(
            "docs/data/catalogo_maestro.json no contiene una lista válida."
        )
    return [item for item in locations if isinstance(item, dict)]


def apply_known_source(
    locations: list[dict[str, Any]],
    known: dict[int, dict[str, Any]],
) -> None:
    for item in locations:
        locality_id = as_int(item.get("id"))
        if locality_id is None or locality_id not in known:
            continue

        enriched = known[locality_id]
        for field in (
            "station_number",
            "forecast_reference_id",
            "station_name",
            "distance_km",
        ):
            value = enriched.get(field)
            if value is not None:
                item[field] = value


def is_pending(item: dict[str, Any]) -> bool:
    return (
        as_int(item.get("station_number")) is None
        or as_int(item.get("forecast_reference_id")) is None
    )


def group_pending(
    locations: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}

    for item in locations:
        if not is_pending(item):
            continue

        name = clean_text(item.get("name"))
        locality_id = as_int(item.get("id"))
        if not name or locality_id is None:
            continue

        key = normalized_text(name)
        group = groups.setdefault(
            key,
            {
                "query": name,
                "ids": [],
                "locations": [],
            },
        )
        group["ids"].append(locality_id)
        group["locations"].append(
            {
                "id": locality_id,
                "name": name,
                "department": item.get("department"),
                "province": item.get("province"),
            }
        )

    return groups


def add_rows_to_source(
    rows: list[Any],
    master_ids: set[int],
    known: dict[int, dict[str, Any]],
) -> list[int]:
    resolved_ids: list[int] = []

    for row in rows:
        parsed = parse_georef_row(row)
        if parsed is None:
            continue

        locality_id = int(parsed["id"])
        if locality_id not in master_ids:
            continue

        known[locality_id] = merge_non_null(
            known.get(locality_id),
            parsed,
        )
        resolved_ids.append(locality_id)

    return sorted(set(resolved_ids))


def rebuild_source_from_cache(
    cache: dict[str, Any],
    master_ids: set[int],
    known: dict[int, dict[str, Any]],
) -> None:
    searches = cache.get("searches", {})
    if not isinstance(searches, dict):
        return

    for entry in searches.values():
        if not isinstance(entry, dict):
            continue
        if entry.get("status") != "success":
            continue
        rows = entry.get("results", [])
        if isinstance(rows, list):
            add_rows_to_source(rows, master_ids, known)


def save_progress(
    cache: dict[str, Any],
    known: dict[int, dict[str, Any]],
) -> None:
    now = utc_now()
    cache["updated_at"] = now
    write_json_atomic(CACHE_FILE, cache)

    payload = {
        "schema_version": 1,
        "source": "SMN georef location search",
        "endpoint": ENDPOINT,
        "generated_at": now,
        "count": len(known),
        "locations": {
            str(locality_id): known[locality_id]
            for locality_id in sorted(known)
        },
    }
    write_json_atomic(GEOREF_FILE, payload)


def request_search(
    session: requests.Session,
    query: str,
    timeout: float,
    max_retries: int,
) -> tuple[str, int | None, list[Any], str | None]:
    last_error: str | None = None

    for attempt in range(1, max_retries + 1):
        try:
            response = session.get(
                ENDPOINT,
                params={"name": query},
                headers={
                    "Accept": "application/json",
                    "User-Agent": USER_AGENT,
                },
                timeout=timeout,
            )

            if response.status_code in {403, 429}:
                return (
                    "rate_limited",
                    response.status_code,
                    [],
                    f"El servidor respondió HTTP {response.status_code}.",
                )

            if 500 <= response.status_code <= 599:
                last_error = (
                    f"HTTP {response.status_code} en intento {attempt}."
                )
                if attempt < max_retries:
                    time.sleep(min(2 ** attempt, 15))
                    continue

            response.raise_for_status()
            payload = response.json()

            if not isinstance(payload, list):
                return (
                    "invalid_response",
                    response.status_code,
                    [],
                    "La respuesta no es una lista JSON.",
                )

            return "success", response.status_code, payload, None

        except (
            requests.RequestException,
            ValueError,
        ) as error:
            last_error = f"{type(error).__name__}: {error}"
            if attempt < max_retries:
                time.sleep(min(2 ** attempt, 15))

    return "request_error", None, [], last_error


def build_unresolved(
    groups: dict[str, dict[str, Any]],
    cache: dict[str, Any],
    known: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    searches = cache.get("searches", {})
    if not isinstance(searches, dict):
        searches = {}

    unresolved: list[dict[str, Any]] = []

    for key, group in groups.items():
        entry = searches.get(key)
        if not isinstance(entry, dict):
            continue

        status = str(entry.get("status") or "")
        expected_ids = {int(value) for value in group["ids"]}
        unresolved_ids = sorted(
            locality_id
            for locality_id in expected_ids
            if locality_id not in known
            or as_int(known[locality_id].get("station_number")) is None
            or as_int(
                known[locality_id].get("forecast_reference_id")
            )
            is None
        )

        if not unresolved_ids:
            continue

        if status not in {
            "success",
            "invalid_response",
            "request_error",
            "rate_limited",
        }:
            continue

        by_id = {
            int(item["id"]): item
            for item in group["locations"]
            if as_int(item.get("id")) is not None
        }

        for locality_id in unresolved_ids:
            location = by_id.get(locality_id, {})
            unresolved.append(
                {
                    "id": locality_id,
                    "name": location.get("name"),
                    "department": location.get("department"),
                    "province": location.get("province"),
                    "query": group["query"],
                    "search_status": status,
                    "attempts": as_int(entry.get("attempts")) or 0,
                    "reason": (
                        "El ID no apareció con todos los campos operativos "
                        "en la respuesta."
                        if status == "success"
                        else entry.get("error")
                    ),
                }
            )

    return unresolved


def build_state(
    locations: list[dict[str, Any]],
    known: dict[int, dict[str, Any]],
    cache: dict[str, Any],
    *,
    batch_size: int,
    attempted_queries: int,
    completed_queries: int,
    stopped_reason: str | None,
) -> dict[str, Any]:
    combined = [dict(item) for item in locations]
    apply_known_source(combined, known)

    searches = cache.get("searches", {})
    if not isinstance(searches, dict):
        searches = {}

    resolved = sum(
        as_int(item.get("station_number")) is not None
        and as_int(item.get("forecast_reference_id")) is not None
        for item in combined
    )
    partial = sum(
        (
            as_int(item.get("station_number")) is not None
            or as_int(item.get("forecast_reference_id")) is not None
        )
        and not (
            as_int(item.get("station_number")) is not None
            and as_int(item.get("forecast_reference_id")) is not None
        )
        for item in combined
    )

    return {
        "schema_version": 1,
        "generated_at": utc_now(),
        "endpoint": ENDPOINT,
        "catalog_total": len(combined),
        "resolved_with_station_and_forecast": resolved,
        "partial": partial,
        "pending": len(combined) - resolved,
        "georef_records": len(known),
        "cached_searches": len(searches),
        "successful_searches": sum(
            isinstance(entry, dict) and entry.get("status") == "success"
            for entry in searches.values()
        ),
        "request_errors": sum(
            isinstance(entry, dict)
            and entry.get("status")
            in {"request_error", "invalid_response", "rate_limited"}
            for entry in searches.values()
        ),
        "last_batch": {
            "configured_size": batch_size,
            "attempted_queries": attempted_queries,
            "completed_queries": completed_queries,
            "stopped_reason": stopped_reason,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Completa estación y referencia de pronóstico mediante "
            "el buscador geográfico del SMN."
        )
    )
    parser.add_argument("--batch-size", type=int, default=25)
    parser.add_argument("--sleep-seconds", type=float, default=1.0)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--max-retries", type=int, default=3)
    args = parser.parse_args()

    if not 1 <= args.batch_size <= 500:
        raise ValueError("--batch-size debe estar entre 1 y 500.")
    if args.sleep_seconds < 0.5:
        raise ValueError(
            "--sleep-seconds no puede ser menor que 0.5."
        )
    if not 1 <= args.max_retries <= 5:
        raise ValueError("--max-retries debe estar entre 1 y 5.")

    locations = master_locations()
    master_ids = {
        int(item["id"])
        for item in locations
        if as_int(item.get("id")) is not None
    }

    cache = load_optional(CACHE_FILE, empty_cache())
    georef_payload = load_optional(
        GEOREF_FILE,
        empty_georef_source(),
    )
    known = source_locations(georef_payload)

    rebuild_source_from_cache(cache, master_ids, known)
    apply_known_source(locations, known)
    groups = group_pending(locations)

    searches = cache.setdefault("searches", {})
    if not isinstance(searches, dict):
        raise RuntimeError(
            "data/cache/busquedas_georef.json tiene un formato inválido."
        )

    eligible: list[tuple[str, dict[str, Any]]] = []
    for key, group in groups.items():
        entry = searches.get(key)

        if not isinstance(entry, dict):
            eligible.append((key, group))
            continue

        status = entry.get("status")
        attempts = as_int(entry.get("attempts")) or 0

        if status in {"request_error", "invalid_response"} and attempts < 3:
            eligible.append((key, group))

    eligible.sort(
        key=lambda pair: (
            normalized_text(
                pair[1]["locations"][0].get("province")
            ),
            normalized_text(
                pair[1]["locations"][0].get("department")
            ),
            pair[0],
        )
    )
    selected = eligible[: args.batch_size]

    session = requests.Session()
    attempted_queries = 0
    completed_queries = 0
    stopped_reason: str | None = None

    print(f"Localidades en catálogo: {len(locations)}")
    print(f"Registros georef conocidos: {len(known)}")
    print(f"Nombres pendientes elegibles: {len(eligible)}")
    print(f"Consultas seleccionadas: {len(selected)}")

    for position, (key, group) in enumerate(selected, start=1):
        query = str(group["query"])
        previous = searches.get(key)
        previous_attempts = (
            as_int(previous.get("attempts"))
            if isinstance(previous, dict)
            else 0
        ) or 0

        print(
            f"[{position}/{len(selected)}] Buscando: {query!r} "
            f"(IDs esperados: {group['ids']})"
        )

        attempted_queries += 1
        status, http_status, rows, error = request_search(
            session,
            query=query,
            timeout=args.timeout,
            max_retries=args.max_retries,
        )

        resolved_ids = (
            add_rows_to_source(rows, master_ids, known)
            if status == "success"
            else []
        )

        searches[key] = {
            "query": query,
            "searched_at": utc_now(),
            "status": status,
            "http_status": http_status,
            "attempts": previous_attempts + 1,
            "expected_ids": sorted(set(group["ids"])),
            "resolved_ids": resolved_ids,
            "result_count": len(rows),
            "results": rows,
            "error": error,
        }

        save_progress(cache, known)

        if status == "success":
            completed_queries += 1
            print(
                f"  Respuesta válida: {len(rows)} resultados; "
                f"IDs aprovechados: {resolved_ids}"
            )
        else:
            print(f"  Estado: {status}. Error: {error}")

        if status == "rate_limited":
            stopped_reason = (
                "El servidor indicó limitación o bloqueo temporal; "
                "se detuvo el lote."
            )
            break

        if position < len(selected):
            time.sleep(args.sleep_seconds)

    save_progress(cache, known)

    current_locations = master_locations()
    apply_known_source(current_locations, known)
    current_groups = group_pending(current_locations)

    unresolved = build_unresolved(
        current_groups,
        cache,
        known,
    )
    write_json_atomic(
        UNRESOLVED_FILE,
        {
            "schema_version": 1,
            "generated_at": utc_now(),
            "count": len(unresolved),
            "locations": unresolved,
        },
    )

    state = build_state(
        current_locations,
        known,
        cache,
        batch_size=args.batch_size,
        attempted_queries=attempted_queries,
        completed_queries=completed_queries,
        stopped_reason=stopped_reason,
    )
    write_json_atomic(STATE_FILE, state)

    print("Enriquecimiento finalizado.")
    print(
        "Resueltas con estación y pronóstico: "
        f"{state['resolved_with_station_and_forecast']}"
    )
    print(f"Pendientes: {state['pending']}")
    print(f"Casos procesados no resueltos: {len(unresolved)}")


if __name__ == "__main__":
    main()
