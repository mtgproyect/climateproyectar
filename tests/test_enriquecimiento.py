from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from enriquecer_georef import (  # noqa: E402
    add_rows_to_source,
    merge_non_null,
    parse_georef_row,
)


class GeorefEnrichmentTest(unittest.TestCase):
    def test_parse_25_de_mayo(self) -> None:
        row = [
            4003,
            "25 de Mayo",
            "25 de Mayo",
            "Buenos Aires",
            87550,
            3989,
            -60.1733,
            -35.433,
            64.35,
            "NUEVE DE JULIO",
        ]
        parsed = parse_georef_row(row)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed["id"], 4003)
        self.assertEqual(parsed["station_number"], 87550)
        self.assertEqual(parsed["forecast_reference_id"], 3989)
        self.assertEqual(parsed["station_name"], "NUEVE DE JULIO")

    def test_exact_id_filter(self) -> None:
        rows = [
            [
                4003,
                "25 de Mayo",
                "25 de Mayo",
                "Buenos Aires",
                87550,
                3989,
                -60.1733,
                -35.433,
                64.35,
                "NUEVE DE JULIO",
            ],
            [
                999999,
                "Resultado ajeno",
                None,
                "Buenos Aires",
                1,
                2,
                -60,
                -35,
                1,
                "ESTACION",
            ],
        ]
        known: dict[int, dict] = {}
        resolved = add_rows_to_source(rows, {4003}, known)
        self.assertEqual(resolved, [4003])
        self.assertIn(4003, known)
        self.assertNotIn(999999, known)

    def test_null_values_do_not_erase_known_values(self) -> None:
        current = {
            "id": 4003,
            "station_number": 87550,
            "forecast_reference_id": 3989,
        }
        incoming = {
            "id": 4003,
            "station_number": None,
            "forecast_reference_id": None,
            "station_name": "NUEVE DE JULIO",
        }
        merged = merge_non_null(current, incoming)
        self.assertEqual(merged["station_number"], 87550)
        self.assertEqual(merged["forecast_reference_id"], 3989)
        self.assertEqual(merged["station_name"], "NUEVE DE JULIO")


if __name__ == "__main__":
    unittest.main()
