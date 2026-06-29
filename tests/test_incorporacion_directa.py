from __future__ import annotations
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from incorporar_pendientes_directos import extract_station_number, validate_result


class DirectIncorporationTest(unittest.TestCase):
    def sample(self) -> dict:
        return {
            "id": 4411,
            "name": "Villa Bordeu",
            "department": "Bahía Blanca",
            "province": "Buenos Aires",
            "direct_probe": {
                "id": 4411,
                "name": "Villa Bordeu",
                "tested_at": "2026-06-29T19:39:05+00:00",
                "status": "completed",
                "forecast": {"available": True, "days": 7, "location": {"id": 4411, "name": "Villa  Bordeu", "department": "Bahía Blanca", "province": "Buenos Aires"}},
                "weather": {"available": True, "location": {"id": 4411, "name": "Villa  Bordeu", "department": "Bahía Blanca", "province": "Buenos Aires", "distance": 15.89}, "station_candidates": [{"path": "station_id", "value": 87750}]},
            },
        }

    def test_extract_station(self) -> None:
        self.assertEqual(extract_station_number(self.sample()["direct_probe"]["weather"]), 87750)

    def test_valid_result(self) -> None:
        record, issues = validate_result(self.sample())
        self.assertEqual(issues, [])
        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record["forecast_reference_id"], 4411)
        self.assertEqual(record["station_number"], 87750)
        self.assertEqual(record["distance_km"], 15.89)

    def test_wrong_id_rejected(self) -> None:
        item = self.sample()
        item["direct_probe"]["weather"]["location"]["id"] = 9999
        record, issues = validate_result(item)
        self.assertIsNone(record)
        self.assertTrue(issues)

    def test_conflicting_station_ids_rejected(self) -> None:
        weather = self.sample()["direct_probe"]["weather"]
        weather["station_candidates"].append({"path": "station_id", "value": 99999})
        self.assertIsNone(extract_station_number(weather))


if __name__ == "__main__":
    unittest.main()
