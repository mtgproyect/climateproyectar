from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from descargar_datos_operativos import (  # noqa: E402
    normalize_legacy_forecast,
)


class HistoricalForecastTest(unittest.TestCase):
    def test_normalizes_legacy_payload(self) -> None:
        payload = [
            {
                "_id": "abc",
                "timestamp": 1778770803515,
                "date_time": "2026-05-15 18:00",
                "location_id": 10818,
                "forecast": {
                    "0": {
                        "date": "2026-05-15",
                        "temp_min": -9,
                        "temp_max": 1,
                        "morning": {
                            "weather_id": 1,
                            "description": "Cielo algo nublado.",
                        },
                        "afternoon": {
                            "weather_id": 2,
                            "description": "Parcial nublado.",
                        },
                    }
                },
            }
        ]

        result = normalize_legacy_forecast(payload, 10818)

        self.assertTrue(result["historical"])
        self.assertEqual(
            result["source"],
            "smn_legacy_forecast",
        )
        self.assertEqual(result["location"]["id"], 10818)
        self.assertEqual(
            result["forecast"][0]["date"],
            "2026-05-15",
        )
        self.assertEqual(
            result["legacy_metadata"]["date_time"],
            "2026-05-15 18:00",
        )

    def test_selects_latest_legacy_record(self) -> None:
        payload = [
            {
                "timestamp": 1,
                "date_time": "2026-04-01 18:00",
                "location_id": 10818,
                "forecast": {
                    "0": {"date": "2026-04-01"}
                },
            },
            {
                "timestamp": 2,
                "date_time": "2026-05-15 18:00",
                "location_id": 10818,
                "forecast": {
                    "0": {"date": "2026-05-15"}
                },
            },
        ]

        result = normalize_legacy_forecast(payload, 10818)
        self.assertEqual(
            result["updated"],
            "2026-05-15 18:00",
        )

    def test_rejects_wrong_location(self) -> None:
        payload = [
            {
                "location_id": 999,
                "forecast": {
                    "0": {"date": "2026-05-15"}
                },
            }
        ]

        with self.assertRaises(Exception):
            normalize_legacy_forecast(payload, 10818)


if __name__ == "__main__":
    unittest.main()
