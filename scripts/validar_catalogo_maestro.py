from __future__ import annotations

from collections import Counter
from typing import Any

from common import ROOT, as_float, as_int, load_json, normalized_text


CONFIG_FILE = ROOT / "config" / "catalogo.json"
MASTER_FILE = ROOT / "docs" / "data" / "catalogo_maestro.json"
REPORT_FILE = ROOT / "docs" / "data" / "informe_validacion.json"
CONFLICTS_FILE = ROOT / "docs" / "data" / "conflictos.json"


def fail(message: str) -> None:
    raise RuntimeError(message)


def main() -> None:
    config = load_json(CONFIG_FILE)
    master = load_json(MASTER_FILE)
    report = load_json(REPORT_FILE)
    conflicts = load_json(CONFLICTS_FILE)

    localities = master.get("localities")
    if not isinstance(localities, list):
        fail("catalogo_maestro.json no contiene una lista de localidades.")

    expected = int(config["expected_catalog_count"])
    if len(localities) < expected:
        fail(
            f"El catálogo final tiene {len(localities)} registros; "
            f"se esperaban al menos {expected}."
        )

    ids: list[int] = []
    smn_ids: list[int] = []
    invalid_coordinates: list[int] = []
    missing_required: list[int] = []
    malformed_candidates: list[int] = []

    for item in localities:
        if not isinstance(item, dict):
            fail("El catálogo contiene un registro que no es un objeto.")

        locality_id = as_int(item.get("id"))
        smn_id = as_int(item.get("smn_id"))
        name = str(item.get("name") or "").strip()
        province = str(item.get("province") or "").strip()
        lat = as_float(item.get("lat"))
        lon = as_float(item.get("lon"))

        if locality_id is None:
            fail("Existe una localidad sin ID entero.")
        ids.append(locality_id)

        if smn_id is not None:
            smn_ids.append(smn_id)

        if not name or not province:
            missing_required.append(locality_id)

        if lat is None or lon is None or not (-90 <= lat <= 90) or not (
            -180 <= lon <= 180
        ):
            invalid_coordinates.append(locality_id)

        candidates = item.get("forecast_candidate_ids")
        if (
            not isinstance(candidates, list)
            or not candidates
            or candidates[0] != locality_id
            or any(as_int(value) is None for value in candidates)
        ):
            malformed_candidates.append(locality_id)

    duplicate_ids = [
        value for value, count in Counter(ids).items() if count > 1
    ]
    duplicate_smn_ids = [
        value for value, count in Counter(smn_ids).items() if count > 1
    ]

    if duplicate_ids:
        fail(f"IDs internos duplicados: {duplicate_ids[:20]}")
    if duplicate_smn_ids:
        fail(f"smn_id duplicados: {duplicate_smn_ids[:20]}")
    if missing_required:
        fail(f"Registros sin nombre o provincia: {missing_required[:20]}")
    if invalid_coordinates:
        fail(f"Coordenadas inválidas: {invalid_coordinates[:20]}")
    if malformed_candidates:
        fail(
            "forecast_candidate_ids inválidos: "
            f"{malformed_candidates[:20]}"
        )

    by_id = {int(item["id"]): item for item in localities}
    orphan_references = []
    for item in localities:
        reference = as_int(item.get("forecast_reference_id"))
        if reference is not None and reference not in by_id:
            orphan_references.append(
                {
                    "id": item["id"],
                    "forecast_reference_id": reference,
                }
            )

    if orphan_references:
        fail(
            "Hay referencias de pronóstico que no existen en el catálogo: "
            f"{orphan_references[:10]}"
        )

    report_total = report.get("result_counts", {}).get("total")
    if report_total != len(localities):
        fail(
            "El informe no coincide con el catálogo: "
            f"{report_total} != {len(localities)}"
        )

    conflict_items = conflicts.get("conflicts")
    if not isinstance(conflict_items, list):
        fail("conflictos.json no contiene una lista válida.")

    error_conflicts = [
        item
        for item in conflict_items
        if isinstance(item, dict) and item.get("severity") == "error"
    ]
    if error_conflicts:
        fail(
            "Hay conflictos de identidad con severidad error. "
            "Revisá docs/data/conflictos.json."
        )

    print("Validación completada correctamente.")
    print(f"Localidades: {len(localities)}")
    print(f"IDs internos únicos: {len(set(ids))}")
    print(f"smn_id únicos: {len(set(smn_ids))}")
    print(
        "Localidades core: "
        f"{report.get('result_counts', {}).get('core')}"
    )
    print(f"Advertencias de identidad: {len(conflict_items)}")


if __name__ == "__main__":
    main()
