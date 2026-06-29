from __future__ import annotations

import argparse
import json
import math
import os
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CATALOG_FILE = ROOT / "docs" / "data" / "catalogo_maestro.json"

SUMMARY_FILE = ROOT / "docs" / "data" / "inventario_operativo.json"
FORECAST_GROUPS_FILE = ROOT / "docs" / "data" / "grupos_pronostico.json"
STATION_GROUPS_FILE = ROOT / "docs" / "data" / "grupos_estaciones.json"
PARTITIONS_FILE = ROOT / "docs" / "data" / "particiones_operativas.json"


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
    text = " ".join(str(value).split())
    return text or None


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
        temporary_path = Path(handle.name)

    os.replace(temporary_path, path)


def extract_localities(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        for key in ("localities", "locations", "localidades"):
            value = payload.get(key)
            if isinstance(value, list):
                return [
                    item for item in value
                    if isinstance(item, dict)
                ]
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    raise RuntimeError(
        "No se encontró una lista de localidades en el catálogo maestro."
    )


def locality_summary(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": as_int(item.get("id")),
        "name": clean_text(item.get("name")),
        "department": clean_text(item.get("department")),
        "province": clean_text(item.get("province")),
        "type": clean_text(item.get("type")),
        "distance_km": as_float(item.get("distance_km")),
    }


def select_station_representative(
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    def key(item: dict[str, Any]) -> tuple[int, float, int]:
        distance = as_float(item.get("distance_km"))
        locality_id = as_int(item.get("id"))
        return (
            1 if distance is None else 0,
            distance if distance is not None else float("inf"),
            locality_id if locality_id is not None else 10**12,
        )

    return min(items, key=key)


def build_balanced_partitions(
    groups: list[dict[str, Any]],
    *,
    shards: int,
    id_field: str,
) -> list[dict[str, Any]]:
    if shards < 1:
        raise ValueError("La cantidad de particiones debe ser positiva.")

    buckets = [
        {
            "shard": index + 1,
            "group_ids": [],
            "query_count": 0,
            "mapped_localities": 0,
        }
        for index in range(shards)
    ]

    ordered = sorted(
        groups,
        key=lambda group: (
            -int(group["locality_count"]),
            int(group[id_field]),
        ),
    )

    for group in ordered:
        bucket = min(
            buckets,
            key=lambda item: (
                item["query_count"],
                item["mapped_localities"],
                item["shard"],
            ),
        )
        bucket["group_ids"].append(int(group[id_field]))
        bucket["query_count"] += 1
        bucket["mapped_localities"] += int(
            group["locality_count"]
        )

    for bucket in buckets:
        bucket["group_ids"].sort()

    return buckets


def validate_unique_locality_ids(
    localities: list[dict[str, Any]],
) -> dict[int, dict[str, Any]]:
    records: dict[int, dict[str, Any]] = {}
    duplicate_ids: list[int] = []

    for item in localities:
        locality_id = as_int(item.get("id"))
        if locality_id is None:
            raise RuntimeError("Existe una localidad sin ID operativo.")
        if locality_id in records:
            duplicate_ids.append(locality_id)
        records[locality_id] = item

    if duplicate_ids:
        raise RuntimeError(
            "Hay IDs operativos duplicados: "
            + ", ".join(map(str, sorted(set(duplicate_ids))[:20]))
        )

    return records


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Genera el inventario de referencias de pronóstico, "
            "estaciones y particiones operativas."
        )
    )
    parser.add_argument("--expect-total", type=int, default=10601)
    parser.add_argument(
        "--expect-forecast-groups",
        type=int,
        default=475,
    )
    parser.add_argument(
        "--expect-station-groups",
        type=int,
        default=124,
    )
    parser.add_argument(
        "--forecast-shards",
        type=int,
        default=2,
    )
    parser.add_argument(
        "--station-shards",
        type=int,
        default=1,
    )
    args = parser.parse_args()

    catalog = load_json(CATALOG_FILE)
    localities = extract_localities(catalog)
    records = validate_unique_locality_ids(localities)

    forecast_map: dict[int, list[dict[str, Any]]] = defaultdict(list)
    station_map: dict[int, list[dict[str, Any]]] = defaultdict(list)

    missing_forecast: list[int] = []
    missing_station: list[int] = []

    for locality_id, item in records.items():
        reference_id = as_int(item.get("forecast_reference_id"))
        station_number = as_int(item.get("station_number"))

        if reference_id is None:
            missing_forecast.append(locality_id)
        else:
            forecast_map[reference_id].append(item)

        if station_number is None:
            missing_station.append(locality_id)
        else:
            station_map[station_number].append(item)

    forecast_groups: list[dict[str, Any]] = []
    for reference_id in sorted(forecast_map):
        items = forecast_map[reference_id]
        locality_ids = sorted(int(item["id"]) for item in items)
        forecast_groups.append(
            {
                "forecast_reference_id": reference_id,
                "locality_count": len(items),
                "locality_ids": locality_ids,
                "reference_is_locality_id": reference_id in locality_ids,
                "sample_localities": [
                    locality_summary(item)
                    for item in sorted(
                        items,
                        key=lambda value: int(value["id"]),
                    )[:5]
                ],
            }
        )

    station_groups: list[dict[str, Any]] = []
    for station_number in sorted(station_map):
        items = station_map[station_number]
        representative = select_station_representative(items)
        names = sorted(
            {
                name
                for item in items
                if (name := clean_text(item.get("station_name")))
            }
        )
        locality_ids = sorted(int(item["id"]) for item in items)

        station_groups.append(
            {
                "station_number": station_number,
                "station_name": names[0] if len(names) == 1 else None,
                "station_name_candidates": names,
                "locality_count": len(items),
                "representative_locality_id": int(
                    representative["id"]
                ),
                "representative_distance_km": as_float(
                    representative.get("distance_km")
                ),
                "locality_ids": locality_ids,
                "sample_localities": [
                    locality_summary(item)
                    for item in sorted(
                        items,
                        key=lambda value: int(value["id"]),
                    )[:5]
                ],
            }
        )

    forecast_partitions = build_balanced_partitions(
        forecast_groups,
        shards=args.forecast_shards,
        id_field="forecast_reference_id",
    )
    station_partitions = build_balanced_partitions(
        station_groups,
        shards=args.station_shards,
        id_field="station_number",
    )

    grouped_by_forecast = sum(
        group["locality_count"] for group in forecast_groups
    )
    grouped_by_station = sum(
        group["locality_count"] for group in station_groups
    )

    problems: list[str] = []
    if len(records) != args.expect_total:
        problems.append(
            f"Se esperaban {args.expect_total} localidades y "
            f"se encontraron {len(records)}."
        )
    if missing_forecast:
        problems.append(
            f"Hay {len(missing_forecast)} localidades sin referencia."
        )
    if missing_station:
        problems.append(
            f"Hay {len(missing_station)} localidades sin estación."
        )
    if len(forecast_groups) != args.expect_forecast_groups:
        problems.append(
            f"Se esperaban {args.expect_forecast_groups} grupos de "
            f"pronóstico y se encontraron {len(forecast_groups)}."
        )
    if len(station_groups) != args.expect_station_groups:
        problems.append(
            f"Se esperaban {args.expect_station_groups} grupos de "
            f"estación y se encontraron {len(station_groups)}."
        )
    if grouped_by_forecast != len(records):
        problems.append(
            "La agrupación de pronóstico no cubre todo el catálogo."
        )
    if grouped_by_station != len(records):
        problems.append(
            "La agrupación de estaciones no cubre todo el catálogo."
        )

    if problems:
        raise RuntimeError(" ".join(problems))

    generated_at = utc_now()
    total_queries = len(forecast_groups) + len(station_groups)

    summary = {
        "schema_version": 1,
        "generated_at": generated_at,
        "catalog_total": len(records),
        "operational_coverage": {
            "with_forecast_reference": (
                len(records) - len(missing_forecast)
            ),
            "with_station": len(records) - len(missing_station),
        },
        "unique_query_keys": {
            "forecast_references": len(forecast_groups),
            "stations": len(station_groups),
            "total_per_full_refresh": total_queries,
        },
        "recommended_architecture": {
            "forecast_shards": args.forecast_shards,
            "station_shards": args.station_shards,
            "forecast_queries_by_shard": [
                item["query_count"]
                for item in forecast_partitions
            ],
            "station_queries_by_shard": [
                item["query_count"]
                for item in station_partitions
            ],
            "minimum_spacing_seconds": 1.0,
            "minimum_request_spacing_time_seconds": total_queries,
            "strategy": (
                "Consultar una vez por forecast_reference_id y una vez "
                "por station_number, usando una localidad representante "
                "para verificar cada estación."
            ),
        },
        "largest_groups": {
            "forecast": [
                {
                    "forecast_reference_id": group[
                        "forecast_reference_id"
                    ],
                    "locality_count": group["locality_count"],
                }
                for group in sorted(
                    forecast_groups,
                    key=lambda item: (
                        -item["locality_count"],
                        item["forecast_reference_id"],
                    ),
                )[:20]
            ],
            "stations": [
                {
                    "station_number": group["station_number"],
                    "station_name": group["station_name"],
                    "locality_count": group["locality_count"],
                }
                for group in sorted(
                    station_groups,
                    key=lambda item: (
                        -item["locality_count"],
                        item["station_number"],
                    ),
                )[:20]
            ],
        },
        "validation": {
            "duplicate_locality_ids": False,
            "missing_forecast_references": len(missing_forecast),
            "missing_stations": len(missing_station),
            "forecast_grouped_localities": grouped_by_forecast,
            "station_grouped_localities": grouped_by_station,
            "errors": 0,
        },
    }

    write_json_atomic(
        FORECAST_GROUPS_FILE,
        {
            "schema_version": 1,
            "generated_at": generated_at,
            "count": len(forecast_groups),
            "groups": forecast_groups,
        },
    )
    write_json_atomic(
        STATION_GROUPS_FILE,
        {
            "schema_version": 1,
            "generated_at": generated_at,
            "count": len(station_groups),
            "groups": station_groups,
        },
    )
    write_json_atomic(
        PARTITIONS_FILE,
        {
            "schema_version": 1,
            "generated_at": generated_at,
            "forecast": {
                "shard_count": len(forecast_partitions),
                "partitions": forecast_partitions,
            },
            "stations": {
                "shard_count": len(station_partitions),
                "partitions": station_partitions,
            },
        },
    )
    write_json_atomic(SUMMARY_FILE, summary)

    print("Inventario operativo generado correctamente.")
    print(f"Localidades: {len(records)}")
    print(f"Referencias de pronóstico únicas: {len(forecast_groups)}")
    print(f"Estaciones únicas: {len(station_groups)}")
    print(f"Consultas por actualización completa: {total_queries}")
    print(
        "Particiones de pronóstico: "
        + ", ".join(
            str(item["query_count"])
            for item in forecast_partitions
        )
    )
    print(
        "Particiones de estaciones: "
        + ", ".join(
            str(item["query_count"])
            for item in station_partitions
        )
    )


if __name__ == "__main__":
    main()
