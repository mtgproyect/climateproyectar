from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import tempfile
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]

CATALOG_FILE = ROOT / "docs" / "data" / "catalogo_maestro.json"
FORECAST_GROUPS_FILE = ROOT / "docs" / "data" / "grupos_pronostico.json"
STATION_GROUPS_FILE = ROOT / "docs" / "data" / "grupos_estaciones.json"
PARTITIONS_FILE = ROOT / "docs" / "data" / "particiones_operativas.json"
STATE_FILE = ROOT / "docs" / "data" / "estado_descarga_operativa.json"

CACHE_DIR = ROOT / "data" / "cache" / "operativo"
OUTPUT_DIR = ROOT / "docs" / "data" / "publicacion"

LOCALITIES_FILE = OUTPUT_DIR / "localidades.json"
SEARCH_FILE = OUTPUT_DIR / "busqueda_localidades.json"
FORECASTS_FILE = OUTPUT_DIR / "pronosticos.json"
STATIONS_FILE = OUTPUT_DIR / "estaciones.json"
MANIFEST_FILE = OUTPUT_DIR / "manifiesto.json"


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
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def clean_text(value: Any) -> str | None:
    if value is None:
        return None
    result = " ".join(str(value).split())
    return result or None


def normalize_search_text(*values: Any) -> str:
    text = " ".join(
        value
        for raw in values
        if (value := clean_text(raw)) is not None
    )
    text = unicodedata.normalize("NFKD", text)
    text = "".join(
        char
        for char in text
        if not unicodedata.combining(char)
    )
    text = text.casefold()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


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
        temporary = Path(handle.name)
    os.replace(temporary, path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def extract_localities(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        for key in ("localities", "locations", "localidades"):
            value = payload.get(key)
            if isinstance(value, list):
                return [
                    item
                    for item in value
                    if isinstance(item, dict)
                ]
    if isinstance(payload, list):
        return [
            item
            for item in payload
            if isinstance(item, dict)
        ]
    raise RuntimeError(
        "El catálogo maestro no contiene una lista de localidades."
    )


def extract_coordinates(item: dict[str, Any]) -> dict[str, float] | None:
    coord = item.get("coord")
    if isinstance(coord, dict):
        lon = as_float(
            coord.get("lon", coord.get("longitude"))
        )
        lat = as_float(
            coord.get("lat", coord.get("latitude"))
        )
    else:
        lon = as_float(
            item.get("lon", item.get("longitude"))
        )
        lat = as_float(
            item.get("lat", item.get("latitude"))
        )

    if lon is None or lat is None:
        return None
    return {"lon": lon, "lat": lat}


def groups(path: Path) -> list[dict[str, Any]]:
    payload = load_json(path)
    values = payload.get("groups") if isinstance(payload, dict) else None
    if not isinstance(values, list):
        raise RuntimeError(f"{path} no contiene groups válidos.")
    return [
        item
        for item in values
        if isinstance(item, dict)
    ]


def locality_to_group(
    values: list[dict[str, Any]],
    *,
    id_field: str,
) -> tuple[dict[int, int], dict[int, dict[str, Any]]]:
    locality_index: dict[int, int] = {}
    group_index: dict[int, dict[str, Any]] = {}

    for group in values:
        group_id = as_int(group.get(id_field))
        locality_ids = group.get("locality_ids")
        if group_id is None or not isinstance(locality_ids, list):
            raise RuntimeError(
                f"Grupo inválido para {id_field}."
            )
        if group_id in group_index:
            raise RuntimeError(
                f"Grupo operativo duplicado: {group_id}."
            )
        group_index[group_id] = group

        for raw_id in locality_ids:
            locality_id = as_int(raw_id)
            if locality_id is None:
                raise RuntimeError(
                    f"Localidad inválida en el grupo {group_id}."
                )
            if locality_id in locality_index:
                raise RuntimeError(
                    f"La localidad {locality_id} pertenece a "
                    "más de un grupo."
                )
            locality_index[locality_id] = group_id

    return locality_index, group_index


def partition_cache_files(
    partitions: dict[str, Any],
    *,
    section_name: str,
    prefix: str,
) -> list[Path]:
    section = partitions.get(section_name)
    values = (
        section.get("partitions")
        if isinstance(section, dict)
        else None
    )
    if not isinstance(values, list):
        raise RuntimeError(
            f"No existen particiones para {section_name}."
        )

    result: list[Path] = []
    for item in values:
        if not isinstance(item, dict):
            continue
        shard = as_int(item.get("shard"))
        if shard is None:
            raise RuntimeError(
                f"Shard inválido en {section_name}."
            )
        result.append(CACHE_DIR / f"{prefix}_shard_{shard}.json")
    return result


def load_cache_records(paths: list[Path]) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    for path in paths:
        payload = load_json(path)
        records = payload.get("records")
        if not isinstance(records, dict):
            raise RuntimeError(
                f"{path} no contiene records válidos."
            )
        for raw_id, record in records.items():
            query_id = as_int(raw_id)
            if query_id is None or not isinstance(record, dict):
                continue
            if query_id in result:
                raise RuntimeError(
                    f"Clave operativa duplicada: {query_id}."
                )
            result[query_id] = record
    return result


def publication_record(
    query_id: int,
    record: dict[str, Any],
    *,
    id_field: str,
) -> dict[str, Any]:
    status = str(record.get("status") or "")
    if status not in {"success", "stale"}:
        raise RuntimeError(
            f"La clave {query_id} no está resuelta: {status!r}."
        )
    payload = record.get("payload")
    if not isinstance(payload, dict):
        raise RuntimeError(
            f"La clave {query_id} no contiene payload."
        )

    historical = bool(
        record.get("historical")
        or payload.get("historical")
    )
    data_source = (
        clean_text(record.get("data_source"))
        or clean_text(payload.get("source"))
    )

    result = {
        id_field: query_id,
        "status": status,
        "fresh": status == "success",
        "historical": historical,
        "data_source": data_source,
        "fetched_at": record.get("fetched_at"),
        "last_refresh_attempt_at": record.get(
            "last_refresh_attempt_at"
        ),
        "last_refresh_error": record.get("last_refresh_error"),
        "payload": payload,
    }
    return result


def validate_complete_state(
    state: Any,
    *,
    expect_total_keys: int,
) -> None:
    totals = state.get("totals") if isinstance(state, dict) else None
    if not isinstance(totals, dict):
        raise RuntimeError("El estado operativo no contiene totals.")

    query_keys = as_int(totals.get("query_keys"))
    success = as_int(totals.get("success"))
    errors = as_int(totals.get("errors"))
    pending = as_int(totals.get("pending"))

    if query_keys != expect_total_keys:
        raise RuntimeError(
            f"El estado contiene {query_keys} claves; "
            f"se esperaban {expect_total_keys}."
        )
    if success != query_keys or errors != 0 or pending != 0:
        raise RuntimeError(
            "La descarga operativa no está completa: "
            f"success={success}, errors={errors}, pending={pending}."
        )


def build_publication(
    *,
    root: Path = ROOT,
    expect_localities: int = 10601,
    expect_forecasts: int = 475,
    expect_stations: int = 121,
) -> dict[str, Any]:
    global CATALOG_FILE
    global FORECAST_GROUPS_FILE
    global STATION_GROUPS_FILE
    global PARTITIONS_FILE
    global STATE_FILE
    global CACHE_DIR
    global OUTPUT_DIR
    global LOCALITIES_FILE
    global SEARCH_FILE
    global FORECASTS_FILE
    global STATIONS_FILE
    global MANIFEST_FILE

    CATALOG_FILE = root / "docs" / "data" / "catalogo_maestro.json"
    FORECAST_GROUPS_FILE = root / "docs" / "data" / "grupos_pronostico.json"
    STATION_GROUPS_FILE = root / "docs" / "data" / "grupos_estaciones.json"
    PARTITIONS_FILE = root / "docs" / "data" / "particiones_operativas.json"
    STATE_FILE = root / "docs" / "data" / "estado_descarga_operativa.json"
    CACHE_DIR = root / "data" / "cache" / "operativo"
    OUTPUT_DIR = root / "docs" / "data" / "publicacion"
    LOCALITIES_FILE = OUTPUT_DIR / "localidades.json"
    SEARCH_FILE = OUTPUT_DIR / "busqueda_localidades.json"
    FORECASTS_FILE = OUTPUT_DIR / "pronosticos.json"
    STATIONS_FILE = OUTPUT_DIR / "estaciones.json"
    MANIFEST_FILE = OUTPUT_DIR / "manifiesto.json"

    catalog_payload = load_json(CATALOG_FILE)
    catalog = extract_localities(catalog_payload)
    if len(catalog) != expect_localities:
        raise RuntimeError(
            f"Se encontraron {len(catalog)} localidades; "
            f"se esperaban {expect_localities}."
        )

    forecast_values = groups(FORECAST_GROUPS_FILE)
    station_values = groups(STATION_GROUPS_FILE)
    if len(forecast_values) != expect_forecasts:
        raise RuntimeError(
            f"Se encontraron {len(forecast_values)} pronósticos; "
            f"se esperaban {expect_forecasts}."
        )
    if len(station_values) != expect_stations:
        raise RuntimeError(
            f"Se encontraron {len(station_values)} estaciones; "
            f"se esperaban {expect_stations}."
        )

    forecast_by_locality, forecast_groups = locality_to_group(
        forecast_values,
        id_field="forecast_reference_id",
    )
    station_by_locality, station_groups = locality_to_group(
        station_values,
        id_field="station_number",
    )

    partitions = load_json(PARTITIONS_FILE)
    forecast_cache = load_cache_records(
        partition_cache_files(
            partitions,
            section_name="forecast",
            prefix="pronosticos",
        )
    )
    station_cache = load_cache_records(
        partition_cache_files(
            partitions,
            section_name="stations",
            prefix="estaciones",
        )
    )

    active_forecast_ids = set(forecast_groups)
    active_station_ids = set(station_groups)
    if not active_forecast_ids.issubset(forecast_cache):
        missing = sorted(active_forecast_ids - set(forecast_cache))
        raise RuntimeError(
            "Faltan pronósticos en caché: "
            + ", ".join(map(str, missing[:20]))
        )
    if not active_station_ids.issubset(station_cache):
        missing = sorted(active_station_ids - set(station_cache))
        raise RuntimeError(
            "Faltan estaciones en caché: "
            + ", ".join(map(str, missing[:20]))
        )

    state = load_json(STATE_FILE)
    validate_complete_state(
        state,
        expect_total_keys=expect_forecasts + expect_stations,
    )

    generated_at = utc_now()

    forecast_records = {
        str(query_id): publication_record(
            query_id,
            forecast_cache[query_id],
            id_field="forecast_reference_id",
        )
        for query_id in sorted(active_forecast_ids)
    }
    station_records = {
        str(query_id): publication_record(
            query_id,
            station_cache[query_id],
            id_field="station_number",
        )
        for query_id in sorted(active_station_ids)
    }

    locality_records: dict[str, dict[str, Any]] = {}
    search_records: list[dict[str, Any]] = []
    seen_ids: set[int] = set()

    for item in sorted(
        catalog,
        key=lambda value: as_int(value.get("id")) or 10**12,
    ):
        locality_id = as_int(item.get("id"))
        if locality_id is None:
            raise RuntimeError("Existe una localidad sin ID.")
        if locality_id in seen_ids:
            raise RuntimeError(
                f"ID de localidad duplicado: {locality_id}."
            )
        seen_ids.add(locality_id)

        forecast_id = forecast_by_locality.get(locality_id)
        station_id = station_by_locality.get(locality_id)
        if forecast_id is None or station_id is None:
            raise RuntimeError(
                f"La localidad {locality_id} no tiene mapeo completo."
            )

        station_group = station_groups[station_id]
        name = clean_text(item.get("name"))
        department = clean_text(item.get("department"))
        province = clean_text(item.get("province"))
        locality_type = clean_text(item.get("type"))

        locality_records[str(locality_id)] = {
            "id": locality_id,
            "name": name,
            "department": department,
            "province": province,
            "type": locality_type,
            "coord": extract_coordinates(item),
            "forecast_reference_id": forecast_id,
            "source_station_number": as_int(
                item.get("station_number")
            ),
            "operational_station_number": station_id,
            "station_name": clean_text(
                station_group.get("station_name")
            ),
            "distance_km": as_float(item.get("distance_km")),
        }

        search_records.append(
            {
                "id": locality_id,
                "name": name,
                "department": department,
                "province": province,
                "label": ", ".join(
                    value
                    for value in (name, department, province)
                    if value
                ),
                "search_text": normalize_search_text(
                    name,
                    department,
                    province,
                ),
            }
        )

    if len(locality_records) != expect_localities:
        raise RuntimeError("La publicación no cubre todo el catálogo.")

    stale_forecast_ids = [
        int(query_id)
        for query_id, record in forecast_records.items()
        if record["status"] == "stale"
    ]
    stale_station_ids = [
        int(query_id)
        for query_id, record in station_records.items()
        if record["status"] == "stale"
    ]

    write_json_atomic(
        LOCALITIES_FILE,
        {
            "schema_version": 1,
            "generated_at": generated_at,
            "count": len(locality_records),
            "records": locality_records,
        },
    )
    write_json_atomic(
        SEARCH_FILE,
        {
            "schema_version": 1,
            "generated_at": generated_at,
            "count": len(search_records),
            "records": search_records,
        },
    )
    write_json_atomic(
        FORECASTS_FILE,
        {
            "schema_version": 1,
            "generated_at": generated_at,
            "count": len(forecast_records),
            "fresh": len(forecast_records) - len(stale_forecast_ids),
            "stale": len(stale_forecast_ids),
            "records": forecast_records,
        },
    )
    write_json_atomic(
        STATIONS_FILE,
        {
            "schema_version": 1,
            "generated_at": generated_at,
            "count": len(station_records),
            "fresh": len(station_records) - len(stale_station_ids),
            "stale": len(stale_station_ids),
            "records": station_records,
        },
    )

    data_files = {
        "localities": LOCALITIES_FILE,
        "search": SEARCH_FILE,
        "forecasts": FORECASTS_FILE,
        "stations": STATIONS_FILE,
    }
    files = {
        key: {
            "path": str(path.relative_to(root)),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for key, path in data_files.items()
    }

    manifest = {
        "schema_version": 1,
        "generated_at": generated_at,
        "source_state_generated_at": state.get("generated_at"),
        "counts": {
            "localities": len(locality_records),
            "forecast_references": len(forecast_records),
            "stations": len(station_records),
            "operational_query_keys": (
                len(forecast_records) + len(station_records)
            ),
            "fresh_forecasts": (
                len(forecast_records) - len(stale_forecast_ids)
            ),
            "stale_forecasts": len(stale_forecast_ids),
            "fresh_stations": (
                len(station_records) - len(stale_station_ids)
            ),
            "stale_stations": len(stale_station_ids),
        },
        "stale": {
            "forecast_reference_ids": stale_forecast_ids,
            "station_numbers": stale_station_ids,
        },
        "files": files,
        "validation": {
            "complete_operational_state": True,
            "all_localities_mapped": True,
            "duplicate_locality_ids": False,
            "missing_forecasts": 0,
            "missing_stations": 0,
            "errors": 0,
        },
    }
    write_json_atomic(MANIFEST_FILE, manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Genera archivos estáticos para publicar las localidades, "
            "pronósticos y estaciones sin duplicar payloads."
        )
    )
    parser.add_argument("--expect-localities", type=int, default=10601)
    parser.add_argument("--expect-forecasts", type=int, default=475)
    parser.add_argument("--expect-stations", type=int, default=121)
    args = parser.parse_args()

    manifest = build_publication(
        expect_localities=args.expect_localities,
        expect_forecasts=args.expect_forecasts,
        expect_stations=args.expect_stations,
    )
    counts = manifest["counts"]
    print("Capa de publicación generada correctamente.")
    print(f"Localidades: {counts['localities']}")
    print(
        "Referencias de pronóstico: "
        f"{counts['forecast_references']}"
    )
    print(f"Estaciones: {counts['stations']}")
    print(
        "Pronósticos actuales/históricos: "
        f"{counts['fresh_forecasts']}/"
        f"{counts['stale_forecasts']}"
    )
    print(f"Manifiesto: {MANIFEST_FILE}")


if __name__ == "__main__":
    main()
