"""Usage bar text and Pace message logic.

Shared by the board (MicroPython) and the Mac tests (CPython), so it sticks to
features both support. All times are Unix epoch seconds.
"""
import time

SESSION_WINDOW = 5 * 3600
WEEK_WINDOW = 7 * 86400

# Projections are too noisy to trust before this fraction of a window has passed.
# A short burst early in a 5-hour session swings the projection far more than in a week.
SESSION_MIN_ELAPSED = 0.30
WEEK_MIN_ELAPSED = 0.15
CLOSE_THRESHOLD = 80

ON_TRACK = 0
CLOSE = 1
LIMIT = 2

# MicroPython on ESP32 counts from 2000-01-01, CPython from 1970-01-01.
_EPOCH_DELTA = 946684800 if time.gmtime(0)[0] == 2000 else 0
_DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def current_pct(window, now):
    """Percentage used, or 0 once the window's Reset time has passed."""
    pct, resets_at = window
    return 0 if now >= resets_at else pct


def _local(t, utc_offset):
    return time.gmtime(int(t + utc_offset) - _EPOCH_DELTA)


def _day_number(t, utc_offset):
    return int(t + utc_offset) // 86400


def clock_text(t, utc_offset):
    tm = _local(t, utc_offset)
    hour = tm[3] % 12 or 12
    return "%d:%02d %s" % (hour, tm[4], "AM" if tm[3] < 12 else "PM")


def when_text(t, now, utc_offset):
    """'8:10 PM' today, 'tomorrow 8:10 PM', or 'Fri 8:10 PM' further out."""
    days = _day_number(t, utc_offset) - _day_number(now, utc_offset)
    clock = clock_text(t, utc_offset)
    if days <= 0:
        return clock
    if days == 1:
        return "tomorrow " + clock
    return _DAYS[_local(t, utc_offset)[6]] + " " + clock


def reset_text(window, now, utc_offset):
    resets_at = window[1]
    if now >= resets_at:
        return ""
    return "Resets " + when_text(resets_at, now, utc_offset)


def _reset_label(t, now, utc_offset):
    days = _day_number(t, utc_offset) - _day_number(now, utc_offset)
    if days <= 0:
        return clock_text(t, utc_offset)
    if days == 1:
        return "tomorrow's"
    return _DAYS[_local(t, utc_offset)[6]]


def pace(window, length, min_elapsed, now):
    """(state, projected_pct, limit_at) for one window, or None if too early to judge."""
    pct, resets_at = window
    remaining = resets_at - now
    if remaining <= 0:
        return None
    if pct >= 100:
        return (LIMIT, pct, now)
    elapsed = length - remaining
    if elapsed < length * min_elapsed:
        return None
    projected = pct * length / elapsed
    if projected > 100:
        return (LIMIT, projected, now + (100 - pct) * elapsed / pct)
    if projected > CLOSE_THRESHOLD:
        return (CLOSE, projected, None)
    return (ON_TRACK, projected, None)


def _danger(p):
    state, projected, limit_at = p
    if state == LIMIT:
        # Earlier limit is more dangerous.
        return (state, -limit_at)
    return (state, projected)


def pace_message(session, week, now, utc_offset):
    """(text, state) for whichever window is in more danger, or None.

    session and week are (pct, resets_at) tuples or None.
    """
    candidates = []
    for name, window, length, min_elapsed in (
        ("Session", session, SESSION_WINDOW, SESSION_MIN_ELAPSED),
        ("Weekly", week, WEEK_WINDOW, WEEK_MIN_ELAPSED),
    ):
        if window is not None:
            p = pace(window, length, min_elapsed, now)
            if p is not None:
                candidates.append((name, window, p))
    if not candidates:
        return None

    worst = candidates[0]
    for c in candidates[1:]:
        if _danger(c[2]) > _danger(worst[2]):
            worst = c
    if worst[2][0] == ON_TRACK:
        # Nothing in danger: prefer This week, which is the longer-term signal.
        worst = candidates[-1]

    name, window, (state, projected, limit_at) = worst
    if state == LIMIT:
        if window[0] >= 100:
            return (name + " limit reached", LIMIT)
        return (name + " limit ~" + when_text(limit_at, now, utc_offset), LIMIT)
    label = _reset_label(window[1], now, utc_offset)
    if state == CLOSE:
        return ("Cutting it close for " + label + " reset", CLOSE)
    return ("On track for " + label + " reset", ON_TRACK)
