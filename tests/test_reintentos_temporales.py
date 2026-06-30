from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from descargar_datos_operativos import (  # noqa: E402
    ApiError,
    is_transient_error,
    request_with_retries,
)


class FakeSession:
    pass


class RetryPolicyTest(unittest.TestCase):
    def test_404_is_temporary(self) -> None:
        self.assertTrue(
            is_transient_error(ApiError("HTTP 404", 404))
        )

    def test_503_is_temporary(self) -> None:
        self.assertTrue(
            is_transient_error(ApiError("HTTP 503", 503))
        )

    def test_400_is_not_temporary(self) -> None:
        self.assertFalse(
            is_transient_error(ApiError("HTTP 400", 400))
        )

    @patch(
        "descargar_datos_operativos.time.sleep",
        return_value=None,
    )
    def test_eventual_success_after_404(
        self,
        _sleep,
    ) -> None:
        calls = {"count": 0}

        def function(session, token, target):
            del session, token, target
            calls["count"] += 1
            if calls["count"] < 3:
                raise ApiError("HTTP 404", 404)
            return {"forecast": [{"date": "2026-06-30"}]}

        payload, token, attempts = request_with_retries(
            FakeSession(),
            "token",
            function,
            {"query_id": 10817},
            max_http_attempts=4,
            retry_base_seconds=0.5,
        )

        self.assertEqual(attempts, 3)
        self.assertEqual(token, "token")
        self.assertIn("forecast", payload)


if __name__ == "__main__":
    unittest.main()
