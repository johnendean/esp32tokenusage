import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "mac"))

import push_usage  # noqa: E402

PAYLOAD = {"now": 1000, "utc_offset": 0, "session": {"pct": 5, "resets_at": 2000}, "week": None}


class DeviceHostsTest(unittest.TestCase):
    def test_splits_on_commas_and_trims(self):
        cfg = {"DEVICE_HOSTS": "claude-usage-c6.local, claude-usage-s3.local ,"}
        self.assertEqual(push_usage.device_hosts(cfg), ["claude-usage-c6.local", "claude-usage-s3.local"])

    def test_single_host(self):
        self.assertEqual(push_usage.device_hosts({"DEVICE_HOSTS": "a.local"}), ["a.local"])


class SendTest(unittest.TestCase):
    def setUp(self):
        self.cache = os.path.join(tempfile.mkdtemp(), "cache.json")
        patches = [
            mock.patch.object(push_usage, "CACHE", self.cache),
            mock.patch.object(push_usage, "settings", return_value={"DEVICE_HOSTS": "a, b", "DEVICE_TOKEN": "t"}),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_posts_to_every_host(self):
        with mock.patch.object(push_usage, "post") as post:
            push_usage.send(PAYLOAD)
        self.assertEqual(sorted(c.args[0] for c in post.call_args_list), ["a", "b"])
        self.assertTrue(os.path.exists(self.cache))

    def test_one_offline_board_still_updates_the_other_and_reports_it(self):
        def post(host, body, token):
            if host == "a":
                raise OSError("unreachable")

        with mock.patch.object(push_usage, "post", side_effect=post) as fake:
            with self.assertRaisesRegex(RuntimeError, "a: unreachable"):
                push_usage.send(PAYLOAD)
        self.assertIn("b", [c.args[0] for c in fake.call_args_list])
        self.assertTrue(os.path.exists(self.cache))

    def test_all_offline_leaves_cache_so_next_status_line_retries(self):
        with mock.patch.object(push_usage, "post", side_effect=OSError("down")):
            with self.assertRaises(RuntimeError):
                push_usage.send(PAYLOAD)
        self.assertFalse(os.path.exists(self.cache))


    def test_empty_host_list_is_an_error_not_a_silent_skip(self):
        with mock.patch.object(push_usage, "settings", return_value={"DEVICE_HOSTS": " , ", "DEVICE_TOKEN": "t"}):
            with mock.patch.object(push_usage, "post") as post:
                with self.assertRaisesRegex(ValueError, "DEVICE_HOSTS"):
                    push_usage.send(PAYLOAD)
        post.assert_not_called()
        self.assertFalse(os.path.exists(self.cache))


if __name__ == "__main__":
    unittest.main()
