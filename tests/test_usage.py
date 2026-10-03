import os
import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import usage  # noqa: E402

HOUR = 3600
DAY = 86400
# Thursday 2026-09-17 12:00 UTC
NOW = int(datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc).timestamp())
BST = HOUR


class ResetTextTest(unittest.TestCase):
    def test_same_day_shows_clock_only(self):
        self.assertEqual(usage.reset_text((12, NOW + 7 * HOUR + 10 * 60), NOW, BST), "Resets 8:10 PM")

    def test_next_day_says_tomorrow(self):
        self.assertEqual(usage.reset_text((25, NOW + DAY + 2 * HOUR), NOW, 0), "Resets tomorrow 2:00 PM")

    def test_later_in_week_uses_short_weekday(self):
        self.assertEqual(usage.reset_text((25, NOW + 3 * DAY - 2 * HOUR), NOW, 0), "Resets Sun 10:00 AM")

    def test_utc_offset_can_move_reset_to_tomorrow(self):
        # 23:30 UTC is 00:30 the next day in BST.
        self.assertEqual(usage.reset_text((5, NOW + 11 * HOUR + 30 * 60), NOW, BST), "Resets tomorrow 12:30 AM")

    def test_passed_reset_clears_text_and_zeroes_bar(self):
        window = (80, NOW - 1)
        self.assertEqual(usage.reset_text(window, NOW, 0), "")
        self.assertEqual(usage.current_pct(window, NOW), 0)
        self.assertEqual(usage.current_pct((80, NOW + 1), NOW), 80)


class PaceTest(unittest.TestCase):
    def week(self, pct, days_elapsed):
        return (pct, NOW + usage.WEEK_WINDOW - days_elapsed * DAY)

    def session(self, pct, hours_elapsed):
        return (pct, NOW + usage.SESSION_WINDOW - hours_elapsed * HOUR)

    def test_too_early_gives_no_message(self):
        self.assertIsNone(usage.pace_message(self.session(5, 0.5), self.week(3, 0.5), NOW, 0))

    def test_on_track_prefers_week(self):
        text, state = usage.pace_message(self.session(10, 3), self.week(25, 4), NOW, 0)
        self.assertEqual(state, usage.ON_TRACK)
        self.assertEqual(text, "On track for Sun reset")

    def test_on_track_week_tomorrow(self):
        text, _ = usage.pace_message(None, self.week(50, 6), NOW, 0)
        self.assertEqual(text, "On track for tomorrow's reset")

    def test_cutting_it_close(self):
        # 45% after 3.5 of 7 days projects to 90%.
        text, state = usage.pace_message(None, self.week(45, 3.5), NOW, 0)
        self.assertEqual(state, usage.CLOSE)
        self.assertEqual(text, "Cutting it close for Mon reset")

    def test_session_in_danger_beats_week_on_track(self):
        # 70% after 2h projects to 175%; 30 more % at 35%/h is ~51 minutes.
        text, state = usage.pace_message(self.session(70, 2), self.week(20, 4), NOW, 0)
        self.assertEqual(state, usage.LIMIT)
        self.assertEqual(text, "Session limit ~12:51 PM")

    def test_session_waits_for_30_percent_of_window(self):
        # 1h is 20% of a session: a heavy start is not judged yet, so This week speaks.
        text, state = usage.pace_message(self.session(70, 1), self.week(20, 4), NOW, 0)
        self.assertEqual((text, state), ("On track for Sun reset", usage.ON_TRACK))
        self.assertIsNone(usage.pace((70, NOW + 3.6 * HOUR), usage.SESSION_WINDOW, usage.SESSION_MIN_ELAPSED, NOW))

    def test_earliest_limit_wins(self):
        text, _ = usage.pace_message(self.session(60, 2), self.week(90, 3), NOW, 0)
        self.assertTrue(text.startswith("Session limit"), text)

    def test_limit_reached(self):
        text, state = usage.pace_message(self.session(100, 1), None, NOW, 0)
        self.assertEqual((text, state), ("Session limit reached", usage.LIMIT))

    def test_messages_fit_the_screen(self):
        for text in (
            "Cutting it close for tomorrow's reset",
            usage.pace_message(None, self.week(95, 2), NOW + 6 * HOUR, 0)[0],
        ):
            self.assertLessEqual(len(text), 39, text)


class WrapLinesTest(unittest.TestCase):
    def test_short_text_fills_first_line(self):
        self.assertEqual(usage.wrap_lines("On track", 28, 2), ["On track", ""])

    def test_breaks_between_words(self):
        self.assertEqual(
            usage.wrap_lines("Cutting it close for this week reset", 28, 2),
            ["Cutting it close for this", "week reset"],
        )

    def test_single_line_truncates_overflow(self):
        self.assertEqual(usage.wrap_lines("one two three", 7, 1), ["one two"])

    def test_cuts_words_longer_than_a_line(self):
        self.assertEqual(usage.wrap_lines("abcdefghij", 4, 2), ["abcd", ""])

    def test_empty_text_gives_blank_lines(self):
        self.assertEqual(usage.wrap_lines("", 10, 2), ["", ""])

    def test_every_message_fits_two_amoled_lines(self):
        for text in (
            "Cutting it close for tomorrow reset",
            "Session limit ~tomorrow 12:30 AM",
            "Waiting for data  192.168.100.200",
        ):
            self.assertEqual(" ".join(" ".join(usage.wrap_lines(text, 28, 2)).split()), " ".join(text.split()))


if __name__ == "__main__":
    unittest.main()
