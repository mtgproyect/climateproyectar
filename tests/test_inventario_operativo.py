from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from generar_inventario_operativo import (  # noqa: E402
    build_balanced_partitions,
    select_station_representative,
    validate_unique_locality_ids,
)


class OperationalInventoryTest(unittest.TestCase):
    def test_selects_nearest_station_representative(self) -> None:
        items = [
            {"id": 10, "distance_km": 12.5},
            {"id": 20, "distance_km": 3.2},
            {"id": 30, "distance_km": None},
        ]
        selected = select_station_representative(items)
        self.assertEqual(selected["id"], 20)

    def test_balances_query_counts(self) -> None:
        groups = [
            {
                "forecast_reference_id": index,
                "locality_count": index,
            }
            for index in range(1, 10)
        ]
        partitions = build_balanced_partitions(
            groups,
            shards=2,
            id_field="forecast_reference_id",
        )
        counts = sorted(
            item["query_count"] for item in partitions
        )
        self.assertEqual(counts, [4, 5])

    def test_rejects_duplicate_ids(self) -> None:
        with self.assertRaises(RuntimeError):
            validate_unique_locality_ids(
                [
                    {"id": 1},
                    {"id": 1},
                ]
            )

    def test_accepts_unique_ids(self) -> None:
        result = validate_unique_locality_ids(
            [
                {"id": 1},
                {"id": 2},
            ]
        )
        self.assertEqual(sorted(result), [1, 2])


if __name__ == "__main__":
    unittest.main()
