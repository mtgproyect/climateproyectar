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

from generar_sitio_v2 import build_web_publication  # noqa: E402


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


class WebPublicationTest(unittest.TestCase):
    def build_fixture(self, root: Path) -> None:
        source = root / "docs" / "data" / "publicacion"
        write_json(
            source / "manifiesto.json",
            {"generated_at": "2026-06-30T00:00:00+00:00"},
        )
        write_json(
            source / "localidades.json",
            {
                "records": {
                    "1": {
                        "id": 1,
                        "name": "San José",
                        "department": "Capital",
                        "province": "Mendoza",
                        "type": "Ciudad",
                        "forecast_reference_id": 10,
                        "source_station_number": 100,
                        "operational_station_number": 101,
                        "station_name": "MENDOZA",
                        "distance_km": 3.2,
                        "coord": {"lat": -32.8, "lon": -68.8},
                    },
                    "2": {
                        "id": 2,
                        "name": "Base Sur",
                        "province": "Antártida",
                        "type": "Base",
                        "forecast_reference_id": 11,
                        "source_station_number": 102,
                        "operational_station_number": 102,
                        "station_name": "SUR",
                        "distance_km": 0.5,
                        "coord": {"lat": -64, "lon": -56},
                    },
                }
            },
        )
        write_json(
            source / "pronosticos.json",
            {
                "records": {
                    "10": {
                        "status": "success",
                        "fresh": True,
                        "historical": False,
                        "fetched_at": "2026-06-30T00:00:00+00:00",
                        "payload": {"forecast": [{"date": "2026-06-30"}]},
                    },
                    "11": {
                        "status": "stale",
                        "fresh": False,
                        "historical": True,
                        "data_source": "legacy",
                        "fetched_at": "2026-05-15T00:00:00+00:00",
                        "payload": {"historical": True, "forecast": [{"date": "2026-05-15"}]},
                    },
                }
            },
        )
        write_json(
            source / "estaciones.json",
            {
                "records": {
                    "101": {
                        "status": "success",
                        "fresh": True,
                        "historical": False,
                        "fetched_at": "2026-06-30T00:00:00+00:00",
                        "payload": {"station_id": 101, "temperature": 20},
                    },
                    "102": {
                        "status": "success",
                        "fresh": True,
                        "historical": False,
                        "fetched_at": "2026-06-30T00:00:00+00:00",
                        "payload": {"station_id": 102, "temperature": -10},
                    },
                }
            },
        )

    def test_builds_compact_web_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.build_fixture(root)
            manifest = build_web_publication(
                root=root,
                expect_localities=2,
                expect_forecasts=2,
                expect_stations=2,
            )
            localities = json.loads(
                (root / "docs/data/web/localidades.min.json").read_text(
                    encoding="utf-8"
                )
            )
            historical = json.loads(
                (root / "docs/data/web/pronosticos/11.json").read_text(
                    encoding="utf-8"
                )
            )

        self.assertEqual(manifest["counts"]["localities"], 2)
        self.assertEqual(manifest["counts"]["stale_forecasts"], 1)
        self.assertEqual(localities["records"][0][0], 1)
        self.assertEqual(localities["records"][0][6], 101)
        self.assertTrue(historical["historical"])
        self.assertEqual(historical["status"], "stale")

    def test_rejects_missing_operational_reference(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.build_fixture(root)
            path = root / "docs/data/publicacion/localidades.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["records"]["1"]["forecast_reference_id"] = 999
            write_json(path, payload)

            with self.assertRaises(RuntimeError):
                build_web_publication(
                    root=root,
                    expect_localities=2,
                    expect_forecasts=2,
                    expect_stations=2,
                )


if __name__ == "__main__":
    unittest.main()
