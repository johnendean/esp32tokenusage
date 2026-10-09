import os
import sys
import unittest
from datetime import datetime, timezone
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "mac"))

import push_copilot  # noqa: E402
import push_usage  # noqa: E402

NOW = 1791563001  # 2026-10-09


def user(reset="2026-11-01", **quota):
    """The parts of /copilot_internal/user the display uses, as seen on an individual plan."""
    premium = dict(entitlement=1500, quota_remaining=606.8, percent_remaining=40.4, unlimited=False)
    premium.update(quota)
    return {
        "quota_reset_date": reset,
        "quota_snapshots": {"chat": {"unlimited": True}, "premium_interactions": premium},
    }


def utc(*args):
    return int(datetime(*args, tzinfo=timezone.utc).timestamp())


class BuildPayloadTest(unittest.TestCase):
    def setUp(self):
        patch = mock.patch.object(push_usage, "utc_offset", return_value=3600)
        patch.start()
        self.addCleanup(patch.stop)

    def test_this_month(self):
        self.assertEqual(
            push_copilot.build_payload(user(), NOW),
            {
                "now": NOW,
                "utc_offset": 3600,
                "copilot": {
                    "pct": 59.6,
                    "used": 893,
                    "entitlement": 1500,
                    "resets_at": utc(2026, 11, 1),
                    "starts_at": utc(2026, 10, 1),
                },
            },
        )

    def test_january_reset_starts_in_december(self):
        copilot = push_copilot.build_payload(user(reset="2027-01-01"), NOW)["copilot"]
        self.assertEqual(copilot["starts_at"], utc(2026, 12, 1))

    def test_unlimited_or_missing_plan_sends_nothing(self):
        self.assertIsNone(push_copilot.build_payload(user(unlimited=True), NOW))
        self.assertIsNone(push_copilot.build_payload({"quota_snapshots": {}}, NOW))


if __name__ == "__main__":
    unittest.main()
