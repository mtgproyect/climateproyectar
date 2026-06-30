from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from descargar_datos_operativos import (  # noqa: E402
    is_target_eligible,
)


class RefreshEligibilityTest(unittest.TestCase):
    def test_pending_skips_success_and_stale(self) -> None:
        self.assertFalse(
            is_target_eligible(
                {"status": "success", "attempts": 1},
                refresh_scope="pending",
                max_attempts=5,
                max_age_hours=6,
            )
        )
        self.assertFalse(
            is_target_eligible(
                {"status": "stale", "attempts": 1},
                refresh_scope="pending",
                max_attempts=5,
                max_age_hours=6,
            )
        )

    def test_stale_retries_only_stale(self) -> None:
        self.assertTrue(
            is_target_eligible(
                {"status": "stale", "attempts": 1},
                refresh_scope="stale",
                max_attempts=5,
                max_age_hours=6,
            )
        )
        self.assertFalse(
            is_target_eligible(
                {"status": "success", "attempts": 1},
                refresh_scope="stale",
                max_attempts=5,
                max_age_hours=6,
            )
        )

    def test_expired_uses_fetched_at(self) -> None:
        old = (
            datetime.now(timezone.utc) - timedelta(hours=8)
        ).isoformat()
        recent = (
            datetime.now(timezone.utc) - timedelta(hours=1)
        ).isoformat()

        self.assertTrue(
            is_target_eligible(
                {"status": "success", "fetched_at": old},
                refresh_scope="expired",
                max_attempts=5,
                max_age_hours=6,
            )
        )
        self.assertFalse(
            is_target_eligible(
                {"status": "success", "fetched_at": recent},
                refresh_scope="expired",
                max_attempts=5,
                max_age_hours=6,
            )
        )

    def test_all_retries_everything(self) -> None:
        self.assertTrue(
            is_target_eligible(
                {"status": "success"},
                refresh_scope="all",
                max_attempts=5,
                max_age_hours=6,
            )
        )


if __name__ == "__main__":
    unittest.main()
