from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class AntarcticDistanceSourceTest(unittest.TestCase):
    def test_exact_operational_distances(self) -> None:
        payload = json.loads(
            (ROOT / "data/fuentes/observaciones_antartida.json").read_text(
                encoding="utf-8"
            )
        )
        expected = {
            "10806": 3.07,
            "10810": 0.70,
            "10811": 0.55,
            "10814": 0.48,
            "10817": 0.33,
            "10818": 0.87,
        }
        for locality_id, distance in expected.items():
            actual = payload["observations"][locality_id]["location"][
                "distance_km"
            ]
            self.assertAlmostEqual(actual, distance, places=2)


if __name__ == "__main__":
    unittest.main()
