from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]

STATE_FILE = (
    ROOT / "docs" / "data" / "estado_descarga_operativa.json"
)
PUBLIC_MANIFEST_FILE = (
    ROOT / "docs" / "data" / "publicacion" / "manifiesto.json"
)
WEB_MANIFEST_FILE = (
    ROOT / "docs" / "data" / "web" / "manifiesto.json"
)

EXPECTED_STALE_FORECASTS = {
    10806,
    10810,
    10811,
    10814,
    10817,
    10818,
}


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def as_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def validate_state(state: Any) -> None:
    totals = state.get("totals") if isinstance(state, dict) else None
    if not isinstance(totals, dict):
        raise RuntimeError("El estado no contiene totals válidos.")

    expected = {
        "query_keys": 596,
        "success": 596,
        "errors": 0,
        "pending": 0,
    }
    for key, expected_value in expected.items():
        value = as_int(totals.get(key))
        if value != expected_value:
            raise RuntimeError(
                f"Estado inválido: {key}={value}; "
                f"se esperaba {expected_value}."
            )

    fresh = as_int(totals.get("fresh"))
    stale = as_int(totals.get("stale"))
    if fresh is None or stale is None or fresh + stale != 596:
        raise RuntimeError(
            "La suma de datos fresh y stale no coincide con 596."
        )


def validate_manifest(manifest: Any, *, web: bool) -> None:
    counts = (
        manifest.get("counts")
        if isinstance(manifest, dict)
        else None
    )
    if not isinstance(counts, dict):
        raise RuntimeError("El manifiesto no contiene counts válidos.")

    expected = {
        "localities": 10601,
        "forecast_references": 475,
        "stations": 121,
    }
    for key, expected_value in expected.items():
        value = as_int(counts.get(key))
        if value != expected_value:
            raise RuntimeError(
                f"Manifiesto inválido: {key}={value}; "
                f"se esperaba {expected_value}."
            )

    if not web:
        query_keys = as_int(counts.get("operational_query_keys"))
        if query_keys != 596:
            raise RuntimeError(
                "El manifiesto operativo no contiene 596 claves."
            )

    fresh_forecasts = as_int(counts.get("fresh_forecasts"))
    stale_forecasts = as_int(counts.get("stale_forecasts"))
    fresh_stations = as_int(counts.get("fresh_stations"))
    stale_stations = as_int(counts.get("stale_stations"))

    if (
        fresh_forecasts is None
        or stale_forecasts is None
        or fresh_forecasts + stale_forecasts != 475
    ):
        raise RuntimeError(
            "Los conteos de pronósticos no suman 475."
        )
    if (
        fresh_stations is None
        or stale_stations is None
        or fresh_stations + stale_stations != 121
    ):
        raise RuntimeError(
            "Los conteos de estaciones no suman 121."
        )

    stale = manifest.get("stale")
    if not isinstance(stale, dict):
        raise RuntimeError("El manifiesto no contiene stale válido.")

    raw_forecasts = stale.get("forecast_reference_ids")
    if not isinstance(raw_forecasts, list):
        raise RuntimeError(
            "No existe la lista de pronósticos stale."
        )
    stale_ids = {
        value
        for raw in raw_forecasts
        if (value := as_int(raw)) is not None
    }
    unexpected = stale_ids - EXPECTED_STALE_FORECASTS
    if unexpected:
        raise RuntimeError(
            "Aparecieron pronósticos stale inesperados: "
            + ", ".join(map(str, sorted(unexpected)))
        )

    validation = manifest.get("validation")
    if not isinstance(validation, dict):
        raise RuntimeError(
            "El manifiesto no contiene validación."
        )
    if validation.get("errors") != 0:
        raise RuntimeError(
            "El manifiesto informa errores de validación."
        )
    if validation.get("missing_forecasts") != 0:
        raise RuntimeError("Hay pronósticos faltantes.")
    if validation.get("missing_stations") != 0:
        raise RuntimeError("Hay estaciones faltantes.")


def main() -> None:
    state = load_json(STATE_FILE)
    operational = load_json(PUBLIC_MANIFEST_FILE)
    web = load_json(WEB_MANIFEST_FILE)

    validate_state(state)
    validate_manifest(operational, web=False)
    validate_manifest(web, web=True)

    print("Actualización automática validada correctamente.")
    print("Claves operativas: 596")
    print("Localidades: 10601")
    print("Pronósticos: 475")
    print("Estaciones: 121")


if __name__ == "__main__":
    main()
