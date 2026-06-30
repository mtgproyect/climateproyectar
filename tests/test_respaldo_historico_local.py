from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import descargar_datos_operativos as module  # noqa: E402
from descargar_datos_operativos import (  # noqa: E402
    legacy_record_from_normalized_payload,
    local_legacy_forecast,
)


class LocalHistoricalFallbackTest(unittest.TestCase):
    def legacy_source(self) -> dict:
        return {
            "records": {
                "10817": [
                    {
                        "_id": "abc",
                        "timestamp": 1778770803513,
                        "date_time": "2026-05-15 09:00",
                        "location_id": 10817,
                        "forecast": {
                            "0": {
                                "date": "2026-05-15",
                                "temp_min": -8,
                                "temp_max": -2,
                            }
                        },
                    }
                ]
            }
        }

    def test_loads_local_historical_forecast(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = (
                root
                / "data"
                / "fuentes"
                / "pronosticos_historicos_antartida.json"
            )
            source.parent.mkdir(parents=True)
            source.write_text(
                json.dumps(self.legacy_source()),
                encoding="utf-8",
            )

            with (
                patch.object(module, "ROOT", root),
                patch.object(module, "LOCAL_LEGACY_FILE", source),
            ):
                result = local_legacy_forecast(10817)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertTrue(result["historical"])
        self.assertEqual(
            result["source"],
            "smn_legacy_local_seed",
        )
        self.assertEqual(
            result["forecast"][0]["date"],
            "2026-05-15",
        )

    def test_missing_local_reference_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = (
                root
                / "data"
                / "fuentes"
                / "pronosticos_historicos_antartida.json"
            )
            source.parent.mkdir(parents=True)
            source.write_text(
                json.dumps(self.legacy_source()),
                encoding="utf-8",
            )

            with (
                patch.object(module, "ROOT", root),
                patch.object(module, "LOCAL_LEGACY_FILE", source),
            ):
                result = local_legacy_forecast(99999)

        self.assertIsNone(result)

    def test_reconstructs_raw_legacy_record(self) -> None:
        payload = {
            "historical": True,
            "updated": "2026-05-15 09:00",
            "forecast": [
                {
                    "date": "2026-05-15",
                    "temp_min": -8,
                    "temp_max": -2,
                }
            ],
            "legacy_metadata": {
                "_id": "abc",
                "timestamp": 1778770803513,
                "date_time": "2026-05-15 09:00",
            },
        }

        result = legacy_record_from_normalized_payload(
            10817,
            payload,
        )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["location_id"], 10817)
        self.assertEqual(
            result["forecast"]["0"]["date"],
            "2026-05-15",
        )


if __name__ == "__main__":
    unittest.main()
