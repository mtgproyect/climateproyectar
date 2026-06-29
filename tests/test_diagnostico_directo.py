from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from diagnosticar_pendientes_directos import (  # noqa: E402
    classify_georef_match,
    collect_station_candidates,
    parse_georef_row,
    summarize_forecast,
)


class DirectPendingDiagnosticTest(unittest.TestCase):
    def test_parse_georef_row(self) -> None:
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

    def test_classifications(self) -> None:
        self.assertEqual(
            classify_georef_match(None),
            "exact_id_absent",
        )
        self.assertEqual(
            classify_georef_match(
                {
                    "station_number": 87550,
                    "forecast_reference_id": None,
                }
            ),
            "forecast_missing",
        )
        self.assertEqual(
            classify_georef_match(
                {
                    "station_number": None,
                    "forecast_reference_id": 3989,
                }
            ),
            "station_missing",
        )
        self.assertEqual(
            classify_georef_match(
                {
                    "station_number": 87550,
                    "forecast_reference_id": 3989,
                }
            ),
            "exact_complete",
        )

    def test_station_candidates(self) -> None:
        payload = {
            "location": {
                "station": {
                    "id": 87550,
                    "name": "NUEVE DE JULIO",
                }
            }
        }
        candidates = collect_station_candidates(payload)
        self.assertTrue(candidates)
        self.assertEqual(
            candidates[0]["path"],
            "location.station",
        )

    def test_forecast_summary_omits_full_days(self) -> None:
        payload = {
            "location": {"id": 4003},
            "forecast": [
                {"date": "2026-06-29", "temperature": 10},
                {"date": "2026-06-30", "temperature": 11},
            ],
        }
        summary = summarize_forecast(payload)
        self.assertTrue(summary["available"])
        self.assertEqual(summary["days"], 2)


if __name__ == "__main__":
    unittest.main()
