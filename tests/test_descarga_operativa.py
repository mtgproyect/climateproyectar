from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from descargar_datos_operativos import (  # noqa: E402
    partition_ids,
    validate_forecast_payload,
    validate_weather_payload,
)


class OperationalDownloadTest(unittest.TestCase):
    def test_partition_ids(self) -> None:
        payload = {
            "forecast": {
                "partitions": [
                    {
                        "shard": 1,
                        "group_ids": [10, 20],
                    }
                ]
            }
        }
        self.assertEqual(
            partition_ids(payload, "forecast", 1),
            [10, 20],
        )

    def test_valid_forecast(self) -> None:
        payload = {
            "location": {"id": 10},
            "forecast": [{"date": "2026-06-30"}],
        }
        self.assertIs(
            validate_forecast_payload(payload, 10),
            payload,
        )

    def test_wrong_forecast_id_rejected(self) -> None:
        payload = {
            "location": {"id": 11},
            "forecast": [{"date": "2026-06-30"}],
        }
        with self.assertRaises(Exception):
            validate_forecast_payload(payload, 10)

    def test_valid_weather(self) -> None:
        payload = {
            "location": {"id": 100},
            "station_id": 87550,
            "temperature": 12.0,
        }
        self.assertIs(
            validate_weather_payload(
                payload,
                representative_id=100,
                station_number=87550,
            ),
            payload,
        )

    def test_wrong_station_rejected(self) -> None:
        payload = {
            "location": {"id": 100},
            "station_id": 99999,
            "temperature": 12.0,
        }
        with self.assertRaises(Exception):
            validate_weather_payload(
                payload,
                representative_id=100,
                station_number=87550,
            )


if __name__ == "__main__":
    unittest.main()
