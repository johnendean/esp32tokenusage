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
MONTH_MIN_ELAPSED = 0.15
CLOSE_THRESHOLD = 80

# Claude's windows: (Usage bar label, name in a limit message, length, min elapsed).
SESSION = ("Current session", "Session", SESSION_WINDOW, SESSION_MIN_ELAPSED)
WEEK = ("This week", "Weekly", WEEK_WINDOW, WEEK_MIN_ELAPSED)

ON_TRACK = 0
CLOSE = 1
LIMIT = 2

# MicroPython on ESP32 counts from 2000-01-01, CPython from 1970-01-01.
_EPOCH_DELTA = 946684800 if time.gmtime(0)[0] == 2000 else 0
_DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


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


def _date_text(t, utc_offset):
    """'24 Oct'."""
    tm = _local(t, utc_offset)
    return "%d %s" % (tm[2], _MONTHS[tm[1] - 1])


def when_text(t, now, utc_offset):
    """'8:10 PM' today, 'tomorrow 8:10 PM', 'Fri 8:10 PM' within the week, or '24 Oct'."""
    days = _day_number(t, utc_offset) - _day_number(now, utc_offset)
    clock = clock_text(t, utc_offset)
    if days <= 0:
        return clock
    if days == 1:
        return "tomorrow " + clock
    if days >= 7:
        return _date_text(t, utc_offset)
    return _DAYS[_local(t, utc_offset)[6]] + " " + clock


def reset_text(window, now, utc_offset):
    resets_at = window[1]
    if now >= resets_at:
        return ""
    return "Resets " + when_text(resets_at, now, utc_offset)


def month_reset_text(window, now, utc_offset):
    """'Resets Sun 1 Nov': a monthly window resets at midnight UTC, so the date
    matters more than the clock."""
    resets_at = window[1]
    if now >= resets_at:
        return ""
    return "Resets %s %s" % (_DAYS[_local(resets_at, utc_offset)[6]], _date_text(resets_at, utc_offset))


def _reset_label(t, now, utc_offset):
    days = _day_number(t, utc_offset) - _day_number(now, utc_offset)
    if days <= 0:
        return clock_text(t, utc_offset)
    if days == 1:
        return "tomorrow's"
    if days >= 7:
        return _date_text(t, utc_offset)
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


def _judged(windows, now):
    """(limit name, window, pace) for each window that has data and can be judged."""
    out = []
    for name, window, length, min_elapsed in windows:
        if window is not None:
            p = pace(window, length, min_elapsed, now)
            if p is not None:
                out.append((name, window, p))
    return out


def pace_message(session, week, now, utc_offset):
    """Claude's Pace message: (text, state) for whichever window is in more danger, or None.

    session and week are (pct, resets_at) tuples or None.
    """
    return _pace_message(
        [(SESSION[1], session, SESSION[2], SESSION[3]), (WEEK[1], week, WEEK[2], WEEK[3])], now, utc_offset
    )


def month_pace_message(month, length, now, utc_offset):
    """Copilot's Pace message for This month, a (pct, resets_at) window `length` seconds long."""
    return _pace_message([(None, month, length, MONTH_MIN_ELAPSED)], now, utc_offset)


def _limit_text(name, window, limit_at, now, utc_offset):
    prefix = name + " limit" if name else "Limit"
    if window[0] >= 100:
        return prefix + " reached"
    return prefix + " ~" + when_text(limit_at, now, utc_offset)


def _pace_message(windows, now, utc_offset):
    """windows: (limit name or None, (pct, resets_at) or None, length, min elapsed)."""
    candidates = _judged(windows, now)
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
        return (_limit_text(name, window, limit_at, now, utc_offset), LIMIT)
    label = _reset_label(window[1], now, utc_offset)
    if state == CLOSE:
        return ("Cutting it close for " + label + " reset", CLOSE)
    return ("On track for " + label + " reset", ON_TRACK)


def summary(windows, now, utc_offset):
    """An Agent's row on the Summary screen: its most pressing window.

    windows: (Usage bar label, (pct, resets_at) or None, length, min elapsed).
    Returns (label, pct, verdict, state), where verdict is "On track", "Close",
    "Limit ~3:40 PM" or "" when too early to judge (state None), or None when
    no window has data yet. The worse verdict wins, then the higher % used.
    """
    best = None
    for label, window, length, min_elapsed in windows:
        if window is None:
            continue
        pct = current_pct(window, now)
        p = pace(window, length, min_elapsed, now)
        key = (-1 if p is None else p[0], pct)
        if best is None or key > best[0]:
            best = (key, label, window, pct, p)
    if best is None:
        return None
    _, label, window, pct, p = best
    if p is None:
        return (label, pct, "", None)
    state, _, limit_at = p
    if state == LIMIT:
        return (label, pct, _limit_text(None, window, limit_at, now, utc_offset), LIMIT)
    return (label, pct, "Close" if state == CLOSE else "On track", state)


def ago_text(seconds):
    """'Updated just now', 'Updated 12 min ago', 'Updated 3 h ago' or 'Updated 2 days ago'."""
    minutes = int(seconds // 60)
    if minutes < 1:
        return "Updated just now"
    if minutes < 60:
        return "Updated %d min ago" % minutes
    if minutes < 48 * 60:
        return "Updated %d h ago" % (minutes // 60)
    return "Updated %d days ago" % (minutes // (24 * 60))


def wrap_lines(text, width, lines):
    """Word-wrap text into exactly `lines` strings of at most `width` chars.

    Words longer than a line are cut; text that does not fit is dropped.
    """
    out = [""]
    for word in text.split():
        word = word[:width]
        if not out[-1]:
            out[-1] = word
        elif len(out[-1]) + 1 + len(word) <= width:
            out[-1] += " " + word
        else:
            out.append(word)
    out = out[:lines]
    return out + [""] * (lines - len(out))
