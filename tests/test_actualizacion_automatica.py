from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from validar_actualizacion_automatica import (  # noqa: E402
    validate_manifest,
    validate_state,
)


class AutomaticUpdateValidationTest(unittest.TestCase):
    def valid_state(self) -> dict:
        return {
            "totals": {
                "query_keys": 596,
                "success": 596,
                "fresh": 590,
                "stale": 6,
                "errors": 0,
                "pending": 0,
            }
        }

    def valid_manifest(self) -> dict:
        return {
            "counts": {
                "localities": 10601,
                "forecast_references": 475,
                "stations": 121,
                "operational_query_keys": 596,
                "fresh_forecasts": 469,
                "stale_forecasts": 6,
                "fresh_stations": 121,
                "stale_stations": 0,
            },
            "stale": {
                "forecast_reference_ids": [
                    10806,
                    10810,
                    10811,
                    10814,
                    10817,
                    10818,
                ],
                "station_numbers": [],
            },
            "validation": {
                "errors": 0,
                "missing_forecasts": 0,
                "missing_stations": 0,
            },
        }

    def test_accepts_complete_state(self) -> None:
        validate_state(self.valid_state())

    def test_rejects_pending_queries(self) -> None:
        state = self.valid_state()
        state["totals"]["success"] = 595
        state["totals"]["pending"] = 1
        with self.assertRaises(RuntimeError):
            validate_state(state)

    def test_accepts_known_historical_forecasts(self) -> None:
        validate_manifest(self.valid_manifest(), web=False)

    def test_accepts_recovered_antarctic_forecast(self) -> None:
        manifest = self.valid_manifest()
        manifest["counts"]["fresh_forecasts"] = 470
        manifest["counts"]["stale_forecasts"] = 5
        manifest["stale"]["forecast_reference_ids"].remove(10818)
        validate_manifest(manifest, web=False)

    def test_rejects_unexpected_stale_forecast(self) -> None:
        manifest = self.valid_manifest()
        manifest["stale"]["forecast_reference_ids"].append(99999)
        manifest["counts"]["fresh_forecasts"] = 468
        manifest["counts"]["stale_forecasts"] = 7
        with self.assertRaises(RuntimeError):
            validate_manifest(manifest, web=False)


if __name__ == "__main__":
    unittest.main()
