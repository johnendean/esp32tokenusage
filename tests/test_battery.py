import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import battery  # noqa: E402

MINUTE = 60


def reading(**changes):
    """A healthy battery at 55%, on USB and charging fast; override what a test needs."""
    values = dict(
        battery_present=True,
        usb_connected=True,
        charging=True,
        stage=battery.FAST,
        level=55,
        battery_mv=3980,
        usb_mv=5124,
        chip_c=38.4,
        hot=False,
        usb_limited=False,
    )
    values.update(changes)
    return battery.Reading(**values)


ON_BATTERY = dict(usb_connected=False, usb_mv=None, charging=False, stage=battery.STOPPED)


class ChargingStateTest(unittest.TestCase):
    def test_charging(self):
        self.assertEqual(battery.charging_state(reading()), "Charging")
        self.assertEqual(battery.charging_state(reading(stage=battery.TOP_UP)), "Charging")

    def test_very_flat_battery_charges_slowly(self):
        for stage in (battery.TRICKLE, battery.PRECHARGE):
            self.assertEqual(battery.charging_state(reading(stage=stage)), "Charging slowly (very low)")

    def test_charged(self):
        self.assertEqual(battery.charging_state(reading(charging=False, stage=battery.DONE, level=100)), "Charged")

    def test_plugged_in_but_not_charging(self):
        self.assertEqual(
            battery.charging_state(reading(charging=False, stage=battery.STOPPED)), "Plugged in, not charging"
        )

    def test_on_battery(self):
        self.assertEqual(battery.charging_state(reading(**ON_BATTERY)), "On battery")

    def test_no_battery(self):
        self.assertEqual(battery.charging_state(reading(battery_present=False, level=None)), "No battery fitted")


class WarningsTest(unittest.TestCase):
    def test_none_when_healthy(self):
        self.assertEqual(battery.warnings(reading()), [])

    def test_hot_only_matters_while_charging(self):
        self.assertEqual(battery.warnings(reading(hot=True)), ["Board hot, charging slowed"])
        self.assertEqual(battery.warnings(reading(hot=True, **ON_BATTERY)), [])

    def test_weak_usb(self):
        self.assertEqual(battery.warnings(reading(usb_limited=True)), ["USB power too weak"])


class LowBatteryTest(unittest.TestCase):
    def test_bands(self):
        self.assertEqual(battery.band(21), battery.NORMAL)
        self.assertEqual(battery.band(20), battery.LOW)
        self.assertEqual(battery.band(10), battery.CRITICAL)
        self.assertEqual(battery.band(None), battery.NORMAL)

    def test_dims_at_ten_percent_on_battery_only(self):
        self.assertEqual(battery.brightness(reading(level=11, **ON_BATTERY)), battery.FULL_BRIGHTNESS)
        self.assertEqual(battery.brightness(reading(level=10, **ON_BATTERY)), battery.DIM_BRIGHTNESS)
        self.assertEqual(battery.brightness(reading(level=3)), battery.FULL_BRIGHTNESS)

    def test_warning_at_five_percent_on_battery_only(self):
        self.assertFalse(battery.low_battery_warning(reading(level=6, **ON_BATTERY)))
        self.assertTrue(battery.low_battery_warning(reading(level=5, **ON_BATTERY)))
        self.assertFalse(battery.low_battery_warning(reading(level=5)))
        self.assertFalse(battery.low_battery_warning(reading(battery_present=False, level=None, **ON_BATTERY)))


class TextTest(unittest.TestCase):
    def test_battery_screen_lines_fit(self):
        # The S3 Battery screen fits 28 characters of the medium font on a line.
        on_battery = dict(ON_BATTERY)
        lines = [battery.WORKING_OUT, "Full in about 10 h 55 min", "About 10 h 55 min left"]
        lines += battery.warnings(reading(hot=True, usb_limited=True))
        for changes in (
            {},
            dict(stage=battery.TRICKLE),
            dict(charging=False, stage=battery.DONE),
            dict(charging=False, stage=battery.STOPPED),
            on_battery,
            dict(battery_present=False, level=None),
        ):
            lines.append(battery.charging_state(reading(**changes)))
        for line in lines:
            self.assertLessEqual(len(line), 28, line)

    def test_readings_in_plain_units(self):
        self.assertEqual(battery.voltage_text(4199), "4.20 V")
        self.assertEqual(battery.usb_text(reading()), "Connected, 5.1 V")
        self.assertEqual(battery.usb_text(reading(**ON_BATTERY)), "Not connected")
        self.assertEqual(battery.temperature_text(38.4), "38°C")

    def test_durations_round_to_five_minutes(self):
        self.assertEqual(battery.duration_text(60), "5 min")
        self.assertEqual(battery.duration_text(23 * MINUTE), "25 min")
        self.assertEqual(battery.duration_text(60 * MINUTE), "1 h")
        self.assertEqual(battery.duration_text(81 * MINUTE), "1 h 20 min")


class EstimatorTest(unittest.TestCase):
    def feed(self, estimator, levels, step, start=0, **changes):
        """Feed one reading every `step` seconds; returns the time after the last."""
        t = start
        for level in levels:
            estimator.update(reading(level=level, **changes), t)
            t += step
        return t - step

    def test_waits_for_three_points_of_movement(self):
        e = battery.Estimator()
        self.feed(e, [50, 51, 52], MINUTE)
        self.assertEqual(e.text(), battery.WORKING_OUT)
        e.update(reading(level=53), 3 * MINUTE)
        # 3 points in 3 minutes, 47 to go: 47 minutes, shown as 45.
        self.assertEqual(e.text(), "Full in about 45 min")

    def test_time_left_on_battery(self):
        e = battery.Estimator()
        self.feed(e, [60, 58, 56, 54], 4 * MINUTE, **ON_BATTERY)
        # 6 points in 12 minutes: 54 left lasts 108 minutes.
        self.assertEqual(e.text(), "About 1 h 50 min left")

    def test_nothing_to_estimate_when_charged_or_plugged_in(self):
        e = battery.Estimator()
        e.update(reading(charging=False, stage=battery.DONE, level=100), 0)
        self.assertEqual(e.text(), "")
        e.update(reading(charging=False, stage=battery.STOPPED), 1)
        self.assertEqual(e.text(), "")

    def test_starts_over_when_charging_state_changes(self):
        e = battery.Estimator()
        t = self.feed(e, [50, 52, 54, 56], MINUTE)
        self.assertTrue(e.text().startswith("Full in"))
        e.update(reading(level=56, **ON_BATTERY), t + 1)
        self.assertEqual(e.text(), battery.WORKING_OUT)

    def test_ignores_movement_the_wrong_way(self):
        e = battery.Estimator()
        self.feed(e, [56, 55, 54, 53], MINUTE)  # gauge settling down after plugging in
        self.assertEqual(e.text(), battery.WORKING_OUT)

    def test_uses_only_the_last_half_hour(self):
        e = battery.Estimator()
        # Slow at first (1 point per 10 min), then fast (1 point per minute).
        t = self.feed(e, [10, 11, 12, 13, 14, 15], 10 * MINUTE)
        self.feed(e, [16, 17, 18, 19, 20], MINUTE, start=t + MINUTE)
        # At 55 min the window starts at 25 min, anchored by the 12 seen at 20 min:
        # 8 points in 35 min, so 80 to go takes 350 min. All 55 min would give 10 h.
        self.assertEqual(e.text(), "Full in about 5 h 50 min")


if __name__ == "__main__":
    unittest.main()
