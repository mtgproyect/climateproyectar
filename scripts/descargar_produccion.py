from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from common import ROOT, load_json, write_json_atomic


CONFIG_FILE = ROOT / "config" / "catalogo.json"
OUTPUT_FILE = ROOT / "data" / "fuentes" / "localidades_produccion.json"
METADATA_FILE = (
    ROOT / "data" / "fuentes" / "localidades_produccion.meta.json"
)


def validate_catalog(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise RuntimeError("El catálogo de producción no es un objeto JSON.")

    localities = payload.get("localities")
    if not isinstance(localities, list) or len(localities) < 100:
        raise RuntimeError(
            "El catálogo de producción no contiene suficientes localidades."
        )

    valid = 0
    for item in localities:
        if (
            isinstance(item, dict)
            and item.get("id") is not None
            and item.get("name")
        ):
            valid += 1

    if valid < 100:
        raise RuntimeError(
            "El catálogo de producción no contiene registros utilizables."
        )
    return payload


def main() -> None:
    config = load_json(CONFIG_FILE)
    url = str(config["production_catalog_url"])

    session = requests.Session()
    response = session.get(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "climateproyectar-catalog-builder/1.0",
        },
        timeout=60,
    )
    response.raise_for_status()

    payload = validate_catalog(response.json())
    write_json_atomic(OUTPUT_FILE, payload)
    write_json_atomic(
        METADATA_FILE,
        {
            "source_url": url,
            "downloaded_at": datetime.now(timezone.utc).isoformat(),
            "count": len(payload["localities"]),
            "generated_at_in_source": payload.get("generated_at"),
        },
    )

    print(
        "Catálogo de producción descargado: "
        f"{len(payload['localities'])} localidades."
    )


if __name__ == "__main__":
    main()
