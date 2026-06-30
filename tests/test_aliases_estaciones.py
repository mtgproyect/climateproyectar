from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from generar_inventario_operativo import (  # noqa: E402
    resolve_operational_station_number,
    select_operational_station_representative,
)


class OperationalStationAliasTest(unittest.TestCase):
    def test_resolves_known_aliases(self) -> None:
        self.assertEqual(
            resolve_operational_station_number(87412),
            87420,
        )
        self.assertEqual(
            resolve_operational_station_number(87470),
            87360,
        )
        self.assertEqual(
            resolve_operational_station_number(87683),
            87637,
        )

    def test_preserves_normal_station(self) -> None:
        self.assertEqual(
            resolve_operational_station_number(87576),
            87576,
        )

    def test_prefers_canonical_representative(self) -> None:
        items = [
            {
                "id": 9534,
                "station_number": 87412,
                "distance_km": 1.21,
            },
            {
                "id": 9378,
                "station_number": 87420,
                "distance_km": 5.0,
            },
        ]
        selected = select_operational_station_representative(
            items,
            87420,
        )
        self.assertEqual(selected["id"], 9378)


if __name__ == "__main__":
    unittest.main()
