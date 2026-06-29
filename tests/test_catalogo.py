from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MASTER = ROOT / "docs" / "data" / "catalogo_maestro.json"


class CatalogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = json.loads(MASTER.read_text(encoding="utf-8"))
        cls.localities = cls.payload["localities"]
        cls.by_id = {item["id"]: item for item in cls.localities}

    def test_expected_minimum(self) -> None:
        self.assertGreaterEqual(len(self.localities), 10601)

    def test_unique_ids(self) -> None:
        self.assertEqual(len(self.by_id), len(self.localities))

    def test_25_de_mayo_verified(self) -> None:
        item = self.by_id[4003]
        self.assertEqual(item["forecast_reference_id"], 3989)
        self.assertEqual(item["station_number"], 87550)
        self.assertEqual(item["station_name"], "NUEVE DE JULIO")

    def test_marambio_station(self) -> None:
        item = self.by_id[10818]
        self.assertEqual(item["station_number"], 89055)
        self.assertEqual(item["station_code"], "SAWB")
        self.assertTrue(item["special_flags"]["antarctica"])

    def test_forecast_order(self) -> None:
        item = self.by_id[4003]
        self.assertEqual(item["forecast_candidate_ids"], [4003, 3989])


if __name__ == "__main__":
    unittest.main()
