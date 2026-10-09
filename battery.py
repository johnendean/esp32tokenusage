"""
Battery logic shared by the board and the Mac tests: turns power chip readings into
the Charging state, warnings, time estimate and Charge level bands the screens show.

Nothing here talks to hardware: axp2101.py makes the Readings.
"""

# Where the charger is in its cycle, as the power chip reports it.
TRICKLE = "trickle"  # battery so flat it is being woken gently
PRECHARGE = "precharge"  # still very low, charging at reduced current
FAST = "fast"  # constant current
TOP_UP = "top up"  # constant voltage, nearly full
DONE = "done"
STOPPED = "stopped"

# Charge level bands for the Battery indicator.
NORMAL, LOW, CRITICAL = "normal", "low", "critical"
LOW_LEVEL = 20
CRITICAL_LEVEL = 10  # also where the screen dims on battery
WARNING_LEVEL = 5  # Low battery warning replaces the Pace message

DIM_BRIGHTNESS = 128  # half of the panel's 0-255 range
FULL_BRIGHTNESS = 255

LOW_BATTERY_WARNING = "Battery low, plug in"
WORKING_OUT = "Working out time left..."
ESTIMATE_WINDOW = 30 * 60
ESTIMATE_MIN_CHANGE = 3  # Charge level points moved before an estimate is shown


class Reading:
    """One snapshot of the power chip.

    Args:
        battery_present (bool)
        usb_connected (bool): USB is supplying usable power
        charging (bool)
        stage (str): TRICKLE, PRECHARGE, FAST, TOP_UP, DONE or STOPPED
        level (int): Charge level 0-100, None without a battery
        battery_mv (int)
        usb_mv (int): None when USB is not connected
        chip_c (float): power chip temperature in Celsius
        hot (bool): the chip is holding charging back because it is hot
        usb_limited (bool): USB cannot supply everything the board asks for
    """

    def __init__(self, **kwargs):
        for name, value in kwargs.items():
            setattr(self, name, value)


def charging_state(r):
    """Plain-words Charging state, e.g. "Charging" or "On battery"."""
    if not r.battery_present:
        return "No battery fitted"
    if r.charging:
        if r.stage in (TRICKLE, PRECHARGE):
            return "Charging slowly (very low)"
        return "Charging"
    if r.usb_connected:
        return "Charged" if r.stage == DONE else "Plugged in, not charging"
    return "On battery"


def warnings(r):
    """Plain-words problems worth showing, most important first."""
    out = []
    if r.hot and r.charging:
        out.append("Board hot, charging slowed")
    if r.usb_limited and r.usb_connected:
        out.append("USB power too weak")
    return out


def band(level):
    """NORMAL, LOW or CRITICAL for colouring the Battery indicator."""
    if level is None or level > LOW_LEVEL:
        return NORMAL
    return CRITICAL if level <= CRITICAL_LEVEL else LOW


def _on_battery_at_or_below(r, level):
    return r.battery_present and not r.usb_connected and r.level is not None and r.level <= level


def brightness(r):
    """Panel brightness: dimmed to stretch a nearly flat battery, full on USB."""
    return DIM_BRIGHTNESS if _on_battery_at_or_below(r, CRITICAL_LEVEL) else FULL_BRIGHTNESS


def low_battery_warning(r):
    """True when the Low battery warning should replace the Pace message."""
    return _on_battery_at_or_below(r, WARNING_LEVEL)


def voltage_text(mv):
    return "%.2f V" % (mv / 1000)


def usb_text(r):
    if not r.usb_connected:
        return "Not connected"
    return "Connected, %.1f V" % (r.usb_mv / 1000) if r.usb_mv else "Connected"


def temperature_text(c):
    return "%d°C" % round(c)


def duration_text(seconds):
    """"25 min" or "1 h 20 min", to the nearest 5 minutes."""
    minutes = max(5, int((seconds / 60 + 2.5) // 5 * 5))
    hours, minutes = divmod(minutes, 60)
    if not hours:
        return "%d min" % minutes
    return "%d h" % hours if not minutes else "%d h %d min" % (hours, minutes)


def _direction(r):
    """+1 while charging, -1 while running down on battery, 0 otherwise."""
    if r.charging:
        return 1
    if r.battery_present and not r.usb_connected:
        return -1
    return 0


class Estimator:
    """Estimates time to full or time left from how fast the Charge level moves.

    Only the moments the level changes are kept, over the last ESTIMATE_WINDOW
    seconds, and the history starts over whenever the Charging state changes.
    Needing ESTIMATE_MIN_CHANGE points inside the window also caps the estimate:
    3 points in 30 minutes at the slowest, so never more than about 16 h 40 min.
    """

    def __init__(self):
        self._state = None
        self._direction = 0
        self._samples = []  # (seconds, level) at each change of level

    def update(self, r, now):
        state = charging_state(r)
        if state != self._state:
            self._state = state
            self._direction = _direction(r)
            self._samples = []
        if r.level is None:
            return
        if not self._samples or self._samples[-1][1] != r.level:
            self._samples.append((now, r.level))
        # Drop samples older than the window, but always keep the current level.
        while len(self._samples) > 1 and now - self._samples[0][0] > ESTIMATE_WINDOW:
            self._samples.pop(0)

    def text(self):
        """"Full in about 1 h 20 min", "About 3 h left", WORKING_OUT, or "" when
        there is nothing to estimate (charged, plugged in, no battery)."""
        if not self._direction:
            return ""
        if len(self._samples) < 2:
            return WORKING_OUT
        (t0, level0), (t1, level1) = self._samples[0], self._samples[-1]
        moved = (level1 - level0) * self._direction
        if moved < ESTIMATE_MIN_CHANGE or t1 <= t0:
            return WORKING_OUT
        per_second = moved / (t1 - t0)
        if self._direction > 0:
            return "Full in about " + duration_text((100 - level1) / per_second)
        return "About %s left" % duration_text(level1 / per_second)
