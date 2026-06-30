from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from generar_publicacion_operativa import (  # noqa: E402
    build_publication,
    normalize_search_text,
)


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


class PublicationTest(unittest.TestCase):
    def build_fixture(self, root: Path) -> None:
        write_json(
            root / "docs/data/catalogo_maestro.json",
            {
                "localities": [
                    {
                        "id": 1,
                        "name": "San José",
                        "department": "Capital",
                        "province": "Mendoza",
                        "forecast_reference_id": 10,
                        "station_number": 100,
                        "station_name": "ANTIGUA",
                        "distance_km": 1.5,
                        "coord": {"lon": -68.0, "lat": -32.0},
                    },
                    {
                        "id": 2,
                        "name": "Villa Norte",
                        "department": "Capital",
                        "province": "Mendoza",
                        "forecast_reference_id": 10,
                        "station_number": 101,
                        "station_name": "ACTIVA",
                        "distance_km": 2.5,
                    },
                    {
                        "id": 3,
                        "name": "Base Sur",
                        "province": "Antártida",
                        "forecast_reference_id": 11,
                        "station_number": 102,
                        "station_name": "SUR",
                        "distance_km": 0.5,
                    },
                ]
            },
        )
        write_json(
            root / "docs/data/grupos_pronostico.json",
            {
                "groups": [
                    {
                        "forecast_reference_id": 10,
                        "locality_ids": [1, 2],
                    },
                    {
                        "forecast_reference_id": 11,
                        "locality_ids": [3],
                    },
                ]
            },
        )
        write_json(
            root / "docs/data/grupos_estaciones.json",
            {
                "groups": [
                    {
                        "station_number": 101,
                        "station_name": "ACTIVA",
                        "locality_ids": [1, 2],
                        "station_number_aliases": [100],
                    },
                    {
                        "station_number": 102,
                        "station_name": "SUR",
                        "locality_ids": [3],
                        "station_number_aliases": [],
                    },
                ]
            },
        )
        write_json(
            root / "docs/data/particiones_operativas.json",
            {
                "forecast": {
                    "partitions": [
                        {"shard": 1, "group_ids": [10, 11]}
                    ]
                },
                "stations": {
                    "partitions": [
                        {"shard": 1, "group_ids": [101, 102]}
                    ]
                },
            },
        )
        write_json(
            root / "docs/data/estado_descarga_operativa.json",
            {
                "generated_at": "2026-06-30T00:00:00+00:00",
                "totals": {
                    "query_keys": 4,
                    "success": 4,
                    "fresh": 3,
                    "stale": 1,
                    "errors": 0,
                    "pending": 0,
                },
            },
        )
        write_json(
            root / "data/cache/operativo/pronosticos_shard_1.json",
            {
                "records": {
                    "10": {
                        "status": "success",
                        "fetched_at": "2026-06-30T00:00:00+00:00",
                        "data_source": "modern",
                        "payload": {
                            "location": {"id": 10},
                            "forecast": [{"date": "2026-06-30"}],
                        },
                    },
                    "11": {
                        "status": "stale",
                        "fetched_at": "2026-05-15T00:00:00+00:00",
                        "data_source": "legacy",
                        "historical": True,
                        "payload": {
                            "location": {"id": 11},
                            "historical": True,
                            "forecast": [{"date": "2026-05-15"}],
                        },
                    },
                }
            },
        )
        write_json(
            root / "data/cache/operativo/estaciones_shard_1.json",
            {
                "records": {
                    "101": {
                        "status": "success",
                        "fetched_at": "2026-06-30T00:00:00+00:00",
                        "payload": {
                            "station_id": 101,
                            "temperature": 20,
                        },
                    },
                    "102": {
                        "status": "success",
                        "fetched_at": "2026-06-30T00:00:00+00:00",
                        "payload": {
                            "station_id": 102,
                            "temperature": -10,
                        },
                    },
                }
            },
        )

    def test_builds_deduplicated_publication(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.build_fixture(root)
            manifest = build_publication(
                root=root,
                expect_localities=3,
                expect_forecasts=2,
                expect_stations=2,
            )

            localities = json.loads(
                (
                    root
                    / "docs/data/publicacion/localidades.json"
                ).read_text(encoding="utf-8")
            )
            forecasts = json.loads(
                (
                    root
                    / "docs/data/publicacion/pronosticos.json"
                ).read_text(encoding="utf-8")
            )

        self.assertEqual(manifest["counts"]["localities"], 3)
        self.assertEqual(
            manifest["counts"]["stale_forecasts"],
            1,
        )
        self.assertEqual(
            localities["records"]["1"][
                "operational_station_number"
            ],
            101,
        )
        self.assertEqual(
            localities["records"]["1"][
                "source_station_number"
            ],
            100,
        )
        self.assertEqual(forecasts["count"], 2)

    def test_normalizes_accents_for_search(self) -> None:
        self.assertEqual(
            normalize_search_text(
                "San José",
                "Capital",
                "Mendoza",
            ),
            "san jose capital mendoza",
        )

    def test_rejects_incomplete_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.build_fixture(root)
            state_path = (
                root
                / "docs/data/estado_descarga_operativa.json"
            )
            state = json.loads(
                state_path.read_text(encoding="utf-8")
            )
            state["totals"]["success"] = 3
            state["totals"]["pending"] = 1
            write_json(state_path, state)

            with self.assertRaises(RuntimeError):
                build_publication(
                    root=root,
                    expect_localities=3,
                    expect_forecasts=2,
                    expect_stations=2,
                )


if __name__ == "__main__":
    unittest.main()
