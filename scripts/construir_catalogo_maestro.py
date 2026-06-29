from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from common import (
    ROOT,
    add_alias,
    as_float,
    as_int,
    clean_text,
    haversine_km,
    load_json,
    normalized_text,
    same_text,
    write_json_atomic,
)


CONFIG_FILE = ROOT / "config" / "catalogo.json"
BASE_FILE = ROOT / "data" / "fuentes" / "catalogo_smn_10601.json"
ENRICHED_FILE = (
    ROOT / "data" / "fuentes" / "localidades_enriquecidas_79.json"
)
PRODUCTION_FILE = (
    ROOT / "data" / "fuentes" / "localidades_produccion.json"
)
ANTARCTICA_FILE = (
    ROOT / "data" / "fuentes" / "observaciones_antartida.json"
)
MANUAL_FILE = (
    ROOT / "data" / "fuentes" / "verificaciones_manuales.json"
)
GEOREF_FILE = (
    ROOT / "data" / "fuentes" / "localidades_georef.json"
)

MASTER_FILE = ROOT / "docs" / "data" / "catalogo_maestro.json"
REPORT_FILE = ROOT / "docs" / "data" / "informe_validacion.json"
CONFLICTS_FILE = ROOT / "docs" / "data" / "conflictos.json"


def load_config() -> dict[str, Any]:
    config = load_json(CONFIG_FILE)
    config["_null_strings"] = {
        str(value).casefold()
        for value in config.get("null_strings", [])
    }
    return config


def canonical_province(value: Any, config: dict[str, Any]) -> str | None:
    text = clean_text(value, config["_null_strings"])
    if text is None:
        return None
    return config.get("province_aliases", {}).get(text, text)


def base_record(
    raw: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    locality_id = as_int(raw.get("smn_id_interno"))
    smn_id = as_int(raw.get("smn_id"))
    name = clean_text(raw.get("smn_nombre"), config["_null_strings"])
    department = clean_text(
        raw.get("smn_departamento"),
        config["_null_strings"],
    )
    province = canonical_province(raw.get("smn_provincia"), config)
    locality_type = clean_text(
        raw.get("smn_tipo"),
        config["_null_strings"],
    )
    lat = as_float(raw.get("smn_lat"))
    lon = as_float(raw.get("smn_lon"))

    if locality_id is None or smn_id is None or not name or not province:
        raise ValueError(f"Registro base inválido: {raw!r}")

    return {
        "id": locality_id,
        "smn_id": smn_id,
        "name": name,
        "aliases": [],
        "department": department,
        "province": province,
        "type": locality_type,
        "lat": lat,
        "lon": lon,
        "zoom": None,
        "forecast_reference_id": None,
        "forecast_candidate_ids": [locality_id],
        "station_number": None,
        "station_code": None,
        "station_name": None,
        "distance_km": None,
        "area": None,
        "core": False,
        "core_sources": [],
        "catalog_sources": ["smn_complete_catalog"],
        "special_flags": {
            "antarctica": department == "Antártida",
            "malvinas": department == "Islas Malvinas",
            "special_territory": department in {
                "Antártida",
                "Islas Malvinas",
            },
        },
        "operational_status": {
            "forecast": "id_only",
            "observation": "pending",
        },
        "distribution": {
            "tier": "pending",
            "worker": None,
        },
        "validation": {
            "status": "valid",
            "issues": [],
        },
    }


def record_conflict(
    conflicts: list[dict[str, Any]],
    *,
    locality_id: int,
    field: str,
    base_value: Any,
    incoming_value: Any,
    source: str,
    severity: str = "warning",
    detail: str | None = None,
) -> None:
    conflicts.append(
        {
            "id": locality_id,
            "field": field,
            "base_value": base_value,
            "incoming_value": incoming_value,
            "source": source,
            "severity": severity,
            "detail": detail,
        }
    )


def merge_identity(
    record: dict[str, Any],
    incoming: dict[str, Any],
    source: str,
    config: dict[str, Any],
    conflicts: list[dict[str, Any]],
    *,
    prefer_incoming_name: bool = False,
) -> None:
    locality_id = int(record["id"])
    incoming_name = clean_text(
        incoming.get("name"),
        config["_null_strings"],
    )
    incoming_department = clean_text(
        incoming.get("department"),
        config["_null_strings"],
    )
    incoming_province = canonical_province(
        incoming.get("province"),
        config,
    )
    incoming_lat = as_float(incoming.get("lat"))
    incoming_lon = as_float(incoming.get("lon"))

    if incoming_name and not same_text(record.get("name"), incoming_name):
        record_conflict(
            conflicts,
            locality_id=locality_id,
            field="name",
            base_value=record.get("name"),
            incoming_value=incoming_name,
            source=source,
            detail="Se conserva como alias o nombre preferido.",
        )
        if prefer_incoming_name:
            add_alias(record, record.get("name"))
            record["name"] = incoming_name
        else:
            add_alias(record, incoming_name)
    elif incoming_name and prefer_incoming_name:
        if incoming_name != record.get("name"):
            add_alias(record, record.get("name"))
            record["name"] = incoming_name

    if incoming_department:
        current_department = record.get("department")
        if current_department and not same_text(
            current_department,
            incoming_department,
        ):
            record_conflict(
                conflicts,
                locality_id=locality_id,
                field="department",
                base_value=current_department,
                incoming_value=incoming_department,
                source=source,
            )
        elif not current_department:
            record["department"] = incoming_department

    if incoming_province:
        current_province = record.get("province")
        if current_province and not same_text(
            current_province,
            incoming_province,
        ):
            record_conflict(
                conflicts,
                locality_id=locality_id,
                field="province",
                base_value=current_province,
                incoming_value=incoming_province,
                source=source,
                severity="error",
            )
        elif not current_province:
            record["province"] = incoming_province

    distance = haversine_km(
        as_float(record.get("lat")),
        as_float(record.get("lon")),
        incoming_lat,
        incoming_lon,
    )
    if distance is not None and distance > 2:
        record_conflict(
            conflicts,
            locality_id=locality_id,
            field="coordinates",
            base_value={
                "lat": record.get("lat"),
                "lon": record.get("lon"),
            },
            incoming_value={
                "lat": incoming_lat,
                "lon": incoming_lon,
            },
            source=source,
            detail=f"Diferencia aproximada: {distance:.2f} km.",
        )
    if record.get("lat") is None and incoming_lat is not None:
        record["lat"] = incoming_lat
    if record.get("lon") is None and incoming_lon is not None:
        record["lon"] = incoming_lon


def merge_operational(
    record: dict[str, Any],
    incoming: dict[str, Any],
    source: str,
    config: dict[str, Any],
    conflicts: list[dict[str, Any]],
    *,
    mark_core: bool,
    prefer_incoming_name: bool = False,
) -> None:
    merge_identity(
        record,
        incoming,
        source,
        config,
        conflicts,
        prefer_incoming_name=prefer_incoming_name,
    )

    fields = (
        "zoom",
        "forecast_reference_id",
        "station_number",
        "station_code",
        "station_name",
        "distance_km",
        "area",
    )
    for field in fields:
        value = incoming.get(field)
        if field in {"zoom", "forecast_reference_id", "station_number"}:
            value = as_int(value)
        elif field == "distance_km":
            value = as_float(value)
        else:
            value = clean_text(value, config["_null_strings"])

        if value is not None:
            record[field] = value

    if mark_core:
        record["core"] = True
        if source not in record["core_sources"]:
            record["core_sources"].append(source)
        record["distribution"]["tier"] = "core"

    if source not in record["catalog_sources"]:
        record["catalog_sources"].append(source)


def normalized_enriched(
    raw: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": as_int(raw.get("id")),
        "name": raw.get("name"),
        "department": raw.get("department"),
        "province": raw.get("province"),
        "lat": raw.get("lat"),
        "lon": raw.get("lon"),
        "zoom": raw.get("zoom"),
        "forecast_reference_id": raw.get("forecast_reference_id"),
        "station_number": raw.get("station_number"),
        "station_name": raw.get("station_name"),
        "distance_km": raw.get("distance_km"),
        "area": raw.get("area"),
    }


def normalized_production(
    raw: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": as_int(raw.get("id")),
        "name": raw.get("name"),
        "department": raw.get("department"),
        "province": raw.get("province"),
        "lat": raw.get("lat"),
        "lon": raw.get("lon"),
        "zoom": raw.get("zoom"),
        "forecast_reference_id": raw.get("forecast_reference_id"),
        "station_number": raw.get("station_number"),
        "station_name": raw.get("station_name"),
        "distance_km": raw.get("distance_km"),
        "area": raw.get("area"),
    }


def add_external_record(
    incoming: dict[str, Any],
    source: str,
    config: dict[str, Any],
) -> dict[str, Any]:
    locality_id = as_int(incoming.get("id"))
    name = clean_text(incoming.get("name"), config["_null_strings"])
    province = canonical_province(incoming.get("province"), config)
    if locality_id is None or not name or not province:
        raise ValueError(f"Registro externo inválido: {incoming!r}")

    record = {
        "id": locality_id,
        "smn_id": None,
        "name": name,
        "aliases": [],
        "department": clean_text(
            incoming.get("department"),
            config["_null_strings"],
        ),
        "province": province,
        "type": clean_text(
            incoming.get("type"),
            config["_null_strings"],
        ),
        "lat": as_float(incoming.get("lat")),
        "lon": as_float(incoming.get("lon")),
        "zoom": as_int(incoming.get("zoom")),
        "forecast_reference_id": as_int(
            incoming.get("forecast_reference_id")
        ),
        "forecast_candidate_ids": [],
        "station_number": as_int(incoming.get("station_number")),
        "station_code": clean_text(incoming.get("station_code")),
        "station_name": clean_text(incoming.get("station_name")),
        "distance_km": as_float(incoming.get("distance_km")),
        "area": clean_text(incoming.get("area")),
        "core": True,
        "core_sources": [source],
        "catalog_sources": [source],
        "special_flags": {
            "antarctica": False,
            "malvinas": False,
            "special_territory": False,
        },
        "operational_status": {
            "forecast": "pending",
            "observation": "pending",
        },
        "distribution": {
            "tier": "core",
            "worker": None,
        },
        "validation": {
            "status": "warning",
            "issues": ["No se encontró en el catálogo SMN completo."],
        },
    }
    return record


def merge_collection(
    records: dict[int, dict[str, Any]],
    items: list[dict[str, Any]],
    source: str,
    config: dict[str, Any],
    conflicts: list[dict[str, Any]],
    *,
    mark_core: bool,
    prefer_incoming_name: bool = False,
) -> int:
    merged = 0
    for raw in items:
        incoming = (
            normalized_enriched(raw)
            if source == "enriched_79"
            else normalized_production(raw)
        )
        locality_id = as_int(incoming.get("id"))
        if locality_id is None:
            continue
        if locality_id not in records:
            records[locality_id] = add_external_record(
                incoming,
                source,
                config,
            )
            record_conflict(
                conflicts,
                locality_id=locality_id,
                field="id",
                base_value=None,
                incoming_value=locality_id,
                source=source,
                severity="warning",
                detail="ID no presente en el catálogo completo.",
            )
        else:
            merge_operational(
                records[locality_id],
                incoming,
                source,
                config,
                conflicts,
                mark_core=mark_core,
                prefer_incoming_name=prefer_incoming_name,
            )
        merged += 1
    return merged


def merge_antarctica(
    records: dict[int, dict[str, Any]],
    payload: dict[str, Any],
    config: dict[str, Any],
    conflicts: list[dict[str, Any]],
) -> int:
    observations = payload.get("observations")
    if not isinstance(observations, dict):
        return 0

    count = 0
    for key, wrapper in observations.items():
        if not isinstance(wrapper, dict):
            continue
        location = wrapper.get("location")
        if not isinstance(location, dict):
            continue

        locality_id = as_int(location.get("id")) or as_int(key)
        if locality_id is None:
            continue

        incoming = {
            "id": locality_id,
            "name": location.get("name"),
            "department": location.get("department"),
            "province": location.get("province"),
            "lat": location.get("lat"),
            "lon": location.get("lon"),
            "station_number": location.get("station_id"),
            "station_code": location.get("station_code"),
            "station_name": location.get("station_name"),
            "distance_km": 0,
            "area": "Antártida",
        }

        if locality_id not in records:
            records[locality_id] = add_external_record(
                incoming,
                "antarctica_seed",
                config,
            )
        else:
            merge_operational(
                records[locality_id],
                incoming,
                "antarctica_seed",
                config,
                conflicts,
                mark_core=True,
                prefer_incoming_name=True,
            )

        record = records[locality_id]
        record["special_flags"]["antarctica"] = True
        record["special_flags"]["special_territory"] = True
        count += 1
    return count



def georef_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    locations = payload.get("locations", {})
    if isinstance(locations, dict):
        iterable = locations.values()
    elif isinstance(locations, list):
        iterable = locations
    else:
        iterable = []
    return [item for item in iterable if isinstance(item, dict)]


def merge_georef(
    records: dict[int, dict[str, Any]],
    payload: dict[str, Any],
    config: dict[str, Any],
    conflicts: list[dict[str, Any]],
) -> int:
    count = 0

    for raw in georef_items(payload):
        locality_id = as_int(raw.get("id"))
        if locality_id is None:
            continue

        record = records.get(locality_id)
        if record is None:
            record_conflict(
                conflicts,
                locality_id=locality_id,
                field="id",
                base_value=None,
                incoming_value=locality_id,
                source="georef_enrichment",
                severity="warning",
                detail=(
                    "El buscador devolvió un ID que no existe en el "
                    "catálogo maestro."
                ),
            )
            continue

        incoming_name = clean_text(
            raw.get("name"),
            config["_null_strings"],
        )
        if incoming_name and not same_text(
            incoming_name,
            record.get("name"),
        ):
            add_alias(record, incoming_name)

        incoming_department = clean_text(
            raw.get("department"),
            config["_null_strings"],
        )
        if not record.get("department") and incoming_department:
            record["department"] = incoming_department

        incoming_province = canonical_province(
            raw.get("province"),
            config,
        )
        if (
            incoming_province
            and record.get("province")
            and not same_text(
                incoming_province,
                record.get("province"),
            )
        ):
            record_conflict(
                conflicts,
                locality_id=locality_id,
                field="province",
                base_value=record.get("province"),
                incoming_value=incoming_province,
                source="georef_enrichment",
                severity="warning",
                detail=(
                    "El ID coincide exactamente; se conserva la provincia "
                    "del catálogo completo."
                ),
            )

        incoming_lat = as_float(raw.get("lat"))
        incoming_lon = as_float(raw.get("lon"))
        coordinate_distance = haversine_km(
            as_float(record.get("lat")),
            as_float(record.get("lon")),
            incoming_lat,
            incoming_lon,
        )
        if coordinate_distance is not None and coordinate_distance > 5:
            record_conflict(
                conflicts,
                locality_id=locality_id,
                field="coordinates",
                base_value={
                    "lat": record.get("lat"),
                    "lon": record.get("lon"),
                },
                incoming_value={
                    "lat": incoming_lat,
                    "lon": incoming_lon,
                },
                source="georef_enrichment",
                severity="warning",
                detail=(
                    "Diferencia aproximada: "
                    f"{coordinate_distance:.2f} km."
                ),
            )

        operational_fields = {
            "forecast_reference_id": as_int(
                raw.get("forecast_reference_id")
            ),
            "station_number": as_int(raw.get("station_number")),
            "station_name": clean_text(
                raw.get("station_name"),
                config["_null_strings"],
            ),
            "distance_km": as_float(raw.get("distance_km")),
        }
        for field, value in operational_fields.items():
            if value is not None:
                record[field] = value

        if "georef_enrichment" not in record["catalog_sources"]:
            record["catalog_sources"].append("georef_enrichment")

        count += 1

    return count


def merge_manual(
    records: dict[int, dict[str, Any]],
    payload: dict[str, Any],
    config: dict[str, Any],
    conflicts: list[dict[str, Any]],
) -> int:
    locations = payload.get("locations")
    if not isinstance(locations, list):
        return 0

    count = 0
    for raw in locations:
        if not isinstance(raw, dict):
            continue
        locality_id = as_int(raw.get("id"))
        if locality_id is None:
            continue
        if locality_id not in records:
            records[locality_id] = add_external_record(
                raw,
                "manual_verification",
                config,
            )
        else:
            merge_operational(
                records[locality_id],
                raw,
                "manual_verification",
                config,
                conflicts,
                mark_core=False,
                prefer_incoming_name=True,
            )
        count += 1
    return count


def finalize_record(record: dict[str, Any]) -> None:
    locality_id = int(record["id"])
    reference_id = as_int(record.get("forecast_reference_id"))

    candidates = [locality_id]
    if reference_id is not None and reference_id not in candidates:
        candidates.append(reference_id)
    record["forecast_candidate_ids"] = candidates

    if reference_id is not None:
        record["operational_status"]["forecast"] = "known_reference"
    else:
        record["operational_status"]["forecast"] = "id_only"

    if as_int(record.get("station_number")) is not None:
        record["operational_status"]["observation"] = "known_station"
    else:
        record["operational_status"]["observation"] = "pending"

    if record.get("core"):
        record["distribution"]["tier"] = "core"
    else:
        record["distribution"]["tier"] = "extended"

    record["aliases"] = sorted(
        set(record.get("aliases") or []),
        key=normalized_text,
    )
    record["core_sources"] = sorted(set(record["core_sources"]))
    record["catalog_sources"] = sorted(set(record["catalog_sources"]))


def build_report(
    records: list[dict[str, Any]],
    base_count: int,
    enriched_count: int,
    production_count: int,
    antarctica_count: int,
    georef_count: int,
    manual_count: int,
    conflicts: list[dict[str, Any]],
) -> dict[str, Any]:
    ids = [int(record["id"]) for record in records]
    smn_ids = [
        int(record["smn_id"])
        for record in records
        if record.get("smn_id") is not None
    ]
    references = {
        int(record["forecast_reference_id"])
        for record in records
        if record.get("forecast_reference_id") is not None
    }
    stations = {
        int(record["station_number"])
        for record in records
        if record.get("station_number") is not None
    }

    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_counts": {
            "complete_catalog": base_count,
            "enriched_79": enriched_count,
            "production_catalog": production_count,
            "antarctica_seed": antarctica_count,
            "georef_enrichment": georef_count,
            "manual_verifications": manual_count,
        },
        "result_counts": {
            "total": len(records),
            "unique_ids": len(set(ids)),
            "unique_smn_ids": len(set(smn_ids)),
            "core": sum(bool(record.get("core")) for record in records),
            "extended": sum(
                not bool(record.get("core")) for record in records
            ),
            "with_forecast_reference": sum(
                record.get("forecast_reference_id") is not None
                for record in records
            ),
            "unique_forecast_references": len(references),
            "with_station": sum(
                record.get("station_number") is not None
                for record in records
            ),
            "unique_stations": len(stations),
            "antarctica": sum(
                bool(record["special_flags"]["antarctica"])
                for record in records
            ),
            "malvinas": sum(
                bool(record["special_flags"]["malvinas"])
                for record in records
            ),
            "conflicts": len(conflicts),
            "error_conflicts": sum(
                conflict.get("severity") == "error"
                for conflict in conflicts
            ),
        },
        "province_counts": dict(
            sorted(
                Counter(
                    record.get("province") or "Sin provincia"
                    for record in records
                ).items()
            )
        ),
        "type_counts": dict(
            sorted(
                Counter(
                    record.get("type") or "Sin tipo"
                    for record in records
                ).items()
            )
        ),
        "production_catalog_loaded": production_count > 0,
        "notes": [
            (
                "El ID operativo principal es id, correspondiente a "
                "smn_id_interno."
            ),
            (
                "El pronóstico debe probar forecast_candidate_ids en orden: "
                "primero id y después forecast_reference_id."
            ),
            (
                "station_number identifica la estación de observación, no el "
                "endpoint de pronóstico."
            ),
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--require-production",
        action="store_true",
        help="Falla si no se descargó el catálogo actual de producción.",
    )
    args = parser.parse_args()

    config = load_config()
    base_payload = load_json(BASE_FILE)
    if not isinstance(base_payload, list):
        raise RuntimeError("El catálogo completo no es una lista JSON.")

    expected = int(config["expected_catalog_count"])
    if len(base_payload) != expected:
        raise RuntimeError(
            f"Se esperaban {expected} registros base y se encontraron "
            f"{len(base_payload)}."
        )

    records: dict[int, dict[str, Any]] = {}
    conflicts: list[dict[str, Any]] = []

    for raw in base_payload:
        if not isinstance(raw, dict):
            raise RuntimeError("El catálogo completo contiene un valor inválido.")
        record = base_record(raw, config)
        locality_id = int(record["id"])
        if locality_id in records:
            raise RuntimeError(f"ID base duplicado: {locality_id}")
        records[locality_id] = record

    enriched_payload = load_json(ENRICHED_FILE)
    enriched_items = enriched_payload.get("localities", [])
    enriched_count = merge_collection(
        records,
        enriched_items,
        "enriched_79",
        config,
        conflicts,
        mark_core=True,
        prefer_incoming_name=True,
    )

    production_count = 0
    if PRODUCTION_FILE.exists():
        production_payload = load_json(PRODUCTION_FILE)
        production_items = production_payload.get("localities", [])
        if not isinstance(production_items, list):
            raise RuntimeError(
                "El catálogo de producción no contiene una lista válida."
            )
        production_count = merge_collection(
            records,
            production_items,
            "production_catalog",
            config,
            conflicts,
            mark_core=True,
            prefer_incoming_name=False,
        )
    elif args.require_production:
        raise RuntimeError(
            "Falta data/fuentes/localidades_produccion.json. "
            "Ejecutá primero scripts/descargar_produccion.py."
        )

    antarctica_count = merge_antarctica(
        records,
        load_json(ANTARCTICA_FILE),
        config,
        conflicts,
    )
    georef_count = 0
    if GEOREF_FILE.exists():
        georef_count = merge_georef(
            records,
            load_json(GEOREF_FILE),
            config,
            conflicts,
        )

    manual_count = merge_manual(
        records,
        load_json(MANUAL_FILE),
        config,
        conflicts,
    )

    for record in records.values():
        finalize_record(record)

    final_records = sorted(
        records.values(),
        key=lambda record: (
            normalized_text(record.get("province")),
            normalized_text(record.get("department")),
            normalized_text(record.get("name")),
            int(record["id"]),
        ),
    )

    report = build_report(
        final_records,
        base_count=len(base_payload),
        enriched_count=enriched_count,
        production_count=production_count,
        antarctica_count=antarctica_count,
        georef_count=georef_count,
        manual_count=manual_count,
        conflicts=conflicts,
    )

    master = {
        "schema_version": 1,
        "source": "Catálogo maestro de localidades de climateproyectar",
        "generated_at": report["generated_at"],
        "count": len(final_records),
        "operational_rules": {
            "primary_location_id": "id",
            "primary_id_source": "smn_id_interno",
            "forecast_request_order": [
                "id",
                "forecast_reference_id",
            ],
            "observation_station_field": "station_number",
        },
        "localities": final_records,
    }

    write_json_atomic(MASTER_FILE, master)
    write_json_atomic(
        CONFLICTS_FILE,
        {
            "schema_version": 1,
            "generated_at": report["generated_at"],
            "count": len(conflicts),
            "conflicts": conflicts,
        },
    )
    write_json_atomic(REPORT_FILE, report)

    print(f"Catálogo maestro: {len(final_records)} localidades.")
    print(f"Localidades core: {report['result_counts']['core']}")
    print(f"Conflictos registrados: {len(conflicts)}")
    if not production_count:
        print(
            "Aviso: se construyó sin el catálogo de producción. "
            "El workflow lo descargará antes de la construcción definitiva."
        )


if __name__ == "__main__":
    main()
