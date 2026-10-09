import json
import time

import asyncio
import framebuf
import network

import battery
import board
import claude_logo
import copilot_logo
import st7789py as st7789
import usage
import vga1_8x16 as font
import wifi_secrets

# Each board announces its own name, e.g. claude-usage-s3.local, so several can share a network.
HOSTNAME = "%s-%s" % (wifi_secrets.DEVICE_NAME, board.detect())
REDRAW_SECONDS = 30
MAX_BODY = 2048
BATTERY_SECONDS = 2  # how often the power chip is read and the Battery screen redrawn
INPUT_MS = 50  # how often the touch screen or button is checked
IDLE_SECONDS = 30  # without a touch or press, any other screen returns to the Summary screen
COPILOT_STALE = 3600  # the Mac job sends every 5 minutes, so an hour old means it has stopped

SUMMARY_SCREEN, CLAUDE_SCREEN, COPILOT_SCREEN, BATTERY_SCREEN = "summary", "claude", "copilot", "battery"
BUTTON_CYCLE = (SUMMARY_SCREEN, CLAUDE_SCREEN, COPILOT_SCREEN)

hw = board.setup()
tft, layout, power = hw.tft, hw.layout, hw.power

BLACK = st7789.BLACK
WHITE = st7789.WHITE
ORANGE = st7789.color565(0xD9, 0x77, 0x57)
RED = st7789.color565(0xE0, 0x45, 0x3A)
GREY = st7789.color565(0x99, 0x99, 0x99)
TRACK = st7789.color565(0x33, 0x33, 0x33)
MESSAGE_COLORS = {usage.ON_TRACK: WHITE, usage.CLOSE: ORANGE, usage.LIMIT: RED}
BAND_COLORS = {battery.NORMAL: GREY, battery.LOW: ORANGE, battery.CRITICAL: RED}

BOLT = (
    ".......####.",
    "......####..",
    ".....####...",
    "....####....",
    "...####.....",
    "..##########",
    ".##########.",
    "##########..",
    ".....####...",
    "....####....",
    "...####.....",
    "..####......",
    ".####.......",
    "####........",
)


class State:
    session = None  # (pct, resets_at)
    week = None
    claude_updated = None  # board time.time() of the last Claude update
    month = None  # Copilot's This month: (pct, resets_at)
    month_length = None  # seconds from the month's start to its Reset time
    credits = None  # (AI credits used, monthly allowance)
    copilot_updated = None
    utc_offset = 0
    clock_offset = None  # add to time.time() to get Unix epoch seconds from the Mac
    changed = asyncio.Event()
    reading = None  # latest battery.Reading, on boards with a battery
    estimator = battery.Estimator()
    brightness = None
    screen = SUMMARY_SCREEN
    screen_changed = False  # the whole screen needs drawing again
    last_input = 0
    drawn_level = None  # Charge level text last drawn large on the Battery screen


state = State()
wlan = network.WLAN(network.STA_IF)


def unix_now():
    return time.time() + state.clock_offset


def text(s, x, y, width_chars, color, align_right=False, face=font):
    s = s[:width_chars]
    s = ("%" + ("" if align_right else "-") + str(width_chars) + "s") % s
    if face.WIDTH in (8, 16):
        tft.text(face, s, x, y, color, BLACK)
    else:
        mono_text(face, s, x, y, color)


_glyphs = {}


def mono_text(face, s, x, y, color):
    """Draw a MONO_HLSB font (e.g. spleen_12x24), which st7789py cannot."""
    w, h = face.WIDTH, face.HEIGHT
    glyphs = _glyphs.get(face)
    if glyphs is None:
        glyphs = _glyphs[face] = memoryview(bytearray(face.FONT))  # framebuf needs it writable
    size = h * ((w + 7) // 8)
    out = bytearray(w * len(s) * h * 2)
    line = framebuf.FrameBuffer(out, w * len(s), h, framebuf.RGB565)
    # framebuf stores pixels little-endian; the displays want big-endian.
    palette = framebuf.FrameBuffer(bytearray(4), 2, 1, framebuf.RGB565)
    palette.pixel(0, 0, ((BLACK & 0xFF) << 8) | (BLACK >> 8))
    palette.pixel(1, 0, ((color & 0xFF) << 8) | (color >> 8))
    for i, ch in enumerate(s):
        code = 0x7F if ch == "\u00b0" else ord(ch)  # make_font.py puts the degree sign there
        if not face.FIRST <= code < face.LAST:
            code = ord("?")
        start = (code - face.FIRST) * size
        glyph = framebuf.FrameBuffer(glyphs[start : start + size], w, h, framebuf.MONO_HLSB)
        line.blit(glyph, i * w, 0, -1, palette)
    tft.blit_buffer(out, x, y, w * len(s), h)


def scaled_text(face, s, x, y, color, scale):
    """Draw an st7789py font (e.g. vga2_16x32) at a whole-number scale."""
    w, h = face.WIDTH, face.HEIGHT
    row_bytes = (w + 7) // 8
    size = h * row_bytes
    on = bytes((color >> 8, color & 0xFF)) * scale
    off = bytes((BLACK >> 8, BLACK & 0xFF)) * scale
    for i, ch in enumerate(s):
        start = (ord(ch) - face.FIRST) * size
        out = bytearray()
        for r in range(h):
            row = start + r * row_bytes
            bits = int.from_bytes(bytes(face.FONT[row : row + row_bytes]), "big")
            top = row_bytes * 8 - 1
            line = b"".join(on if bits >> (top - c) & 1 else off for c in range(w))
            out += line * scale
        tft.blit_buffer(out, x + i * w * scale, y, w * scale, h * scale)


def bitmap(rows, x, y, color):
    """Draw a small picture given as strings, "#" for color and "." for black."""
    pixel = bytes((color >> 8, color & 0xFF))
    out = bytearray()
    for row in rows:
        for c in row:
            out += pixel if c == "#" else b"\x00\x00"
    tft.blit_buffer(out, x, y, len(rows[0]), len(rows))


def draw_battery_indicator():
    r = state.reading
    right, mid = layout.battery_x, layout.battery_y
    face = layout.battery_font
    body_w, body_h, nub_w, border = 45, 24, 4, 2
    body_x, top = right - nub_w - body_w, mid - body_h // 2
    for i in range(border):
        tft.rect(body_x + i, top + i, body_w - 2 * i, body_h - 2 * i, GREY)
    tft.fill_rect(right - nub_w, mid - 6, nub_w, 12, GREY)
    pad = border + 1
    inner = body_w - 2 * pad
    filled = 0 if r.level is None else round(inner * r.level / 100)
    tft.fill_rect(body_x + pad, top + pad, filled, body_h - 2 * pad, BAND_COLORS[battery.band(r.level)])
    tft.fill_rect(body_x + pad + filled, top + pad, inner - filled, body_h - 2 * pad, BLACK)

    # Bolt then "55%", right-aligned against the icon; cleared first as the width varies.
    label = "--%" if r.level is None else "%d%%" % r.level
    gap, bolt_w = 9, len(BOLT[0])
    label_x = body_x - gap - len(label) * face.WIDTH
    widest = 4 * face.WIDTH + gap + bolt_w
    tft.fill_rect(body_x - gap - widest, mid - face.HEIGHT // 2, widest, face.HEIGHT, BLACK)
    text(label, label_x, mid - face.HEIGHT // 2, len(label), WHITE, face=face)
    if r.charging:
        bitmap(BOLT, label_x - gap - bolt_w, mid - len(BOLT) // 2, WHITE)


# Battery screen positions, for the S3's 368x448 portrait screen.
CHARGE_Y = 72  # Charge level, drawn at double size
CHARGE_BAR_Y = 148
STATE_Y = 188
ESTIMATE_Y = 218
DETAILS_DIVIDER_Y = 256
DETAILS_Y = 272
WARNINGS_Y = 368
HINT_Y = 424


def draw_battery_static():
    tft.fill(BLACK)
    m = layout.column_x
    text("Battery", m, 24, 7, WHITE, face=layout.label_font)
    tft.hline(m, DETAILS_DIVIDER_Y, layout.bar_w, TRACK)
    hint = "Tap to go back"
    text(hint, (tft.width - len(hint) * font.WIDTH) // 2, HINT_Y, len(hint), GREY)
    state.drawn_level = None


def draw_battery_screen():
    r = state.reading
    m, w, face = layout.column_x, layout.bar_w, layout.message_font
    cols = w // face.WIDTH

    level = "--%" if r.level is None else "%d%%" % r.level
    if level != state.drawn_level:
        scaled_text(layout.label_font, "%-4s" % level, m, CHARGE_Y, WHITE, 2)
        state.drawn_level = level
    filled = 0 if r.level is None else round(w * r.level / 100)
    tft.fill_rect(m, CHARGE_BAR_Y, filled, layout.bar_h, BAND_COLORS[battery.band(r.level)])
    tft.fill_rect(m + filled, CHARGE_BAR_Y, w - filled, layout.bar_h, TRACK)

    text(battery.charging_state(r), m, STATE_Y, cols, WHITE, face=face)
    text(state.estimator.text(), m, ESTIMATE_Y, cols, GREY, face=face)

    details = (
        ("Battery", battery.voltage_text(r.battery_mv) if r.battery_mv else "--"),
        ("USB power", battery.usb_text(r)),
        ("Board temp", battery.temperature_text(r.chip_c)),
    )
    label_cols = 11
    for i, (label, value) in enumerate(details):
        y = DETAILS_Y + i * (face.HEIGHT + 8)
        text(label, m, y, label_cols, GREY, face=face)
        text(value, m + label_cols * face.WIDTH, y, cols - label_cols, WHITE, True, face=face)

    problems = battery.warnings(r)
    for i in range(2):
        line = problems[i] if i < len(problems) else ""
        text(line, m, WARNINGS_Y + i * (face.HEIGHT + 4), cols, ORANGE, face=face)


def draw_bar(x, y, w, h, pct):
    filled = 0 if pct is None else min(w, round(w * pct / 100))
    if filled:
        tft.fill_rect(x, y, filled, h, RED if pct >= 90 else ORANGE)
    if filled < w:
        tft.fill_rect(x + filled, y, w - filled, h, TRACK)


def pct_text(pct):
    return "--% used" if pct is None else "%d%% used" % round(pct)


def draw_row(y, label, window, now, reset_text=usage.reset_text):
    L = layout
    text(label, L.column_x, y, 15, WHITE, face=L.label_font)
    if window is None:
        pct, reset = None, ""
    else:
        pct, reset = usage.current_pct(window, now), reset_text(window, now, state.utc_offset)
    pct_x = L.column_x + L.bar_w - 9 * font.WIDTH
    text(pct_text(pct), pct_x, y + L.pct_dy, 9, WHITE, True)
    draw_bar(L.column_x, y + L.bar_dy, L.bar_w, L.bar_h, pct)
    text(reset, L.column_x, y + L.reset_dy, L.reset_chars, GREY)


def low_battery():
    return state.reading and battery.low_battery_warning(state.reading)


def agent_message(has_data, pace):
    """The Pace message line for an Agent screen, as (text, color)."""
    if low_battery():
        return (battery.LOW_BATTERY_WARNING, RED)
    if not wlan.isconnected():
        return ("Connecting to Wi-Fi...", GREY)
    if not has_data:
        return ("Waiting for data  " + wlan.ifconfig()[0], GREY)
    return (pace[0], MESSAGE_COLORS[pace[1]]) if pace else ("", WHITE)


def draw_message(message):
    face = layout.message_font
    for i, line in enumerate(usage.wrap_lines(message[0], layout.message_chars, layout.message_lines)):
        text(line, layout.message_x, layout.message_y + i * (face.HEIGHT + 2), layout.message_chars, message[1], face=face)


def draw_updated(updated, stale_after=None):
    """"Updated 12 min ago" at the foot of an Agent screen, orange once stale."""
    if updated is None:
        line, color = "", GREY
    else:
        age = time.time() - updated
        line = usage.ago_text(age)
        color = ORANGE if stale_after and age > stale_after else GREY
    text(line, layout.column_x, layout.updated_y, layout.reset_chars, color)


def now_or_zero():
    return 0 if state.clock_offset is None else unix_now()


def claude_windows():
    return [(w[0], window, w[2], w[3]) for w, window in ((usage.SESSION, state.session), (usage.WEEK, state.week))]


def copilot_windows():
    return [("This month", state.month, state.month_length, usage.MONTH_MIN_ELAPSED)]


def credits_text(now):
    if state.credits is None:
        return ""
    used, allowance = state.credits
    if now >= state.month[1]:
        used = 0  # the month has reset since the last update
    return "%d of %d AI credits" % (used, allowance)


def draw_claude():
    now = now_or_zero()
    has_data = state.session is not None or state.week is not None
    draw_message(agent_message(has_data, usage.pace_message(state.session, state.week, now, state.utc_offset)))
    draw_row(layout.row_ys[0], "Current session", state.session, now)
    draw_row(layout.row_ys[1], "This week", state.week, now)
    draw_updated(state.claude_updated)


def draw_copilot():
    now = now_or_zero()
    month = state.month
    pace = month and usage.month_pace_message(month, state.month_length, now, state.utc_offset)
    draw_message(agent_message(month is not None, pace))
    draw_row(layout.row_ys[0], "This month", month, now, usage.month_reset_text)
    cols = layout.bar_w // layout.credits_font.WIDTH
    text(credits_text(now), layout.column_x, layout.credits_y, cols, WHITE, face=layout.credits_font)
    draw_updated(state.copilot_updated, COPILOT_STALE)


def summary_rows():
    """(name, logo, windows) for each Agent, in the order the Summary screen shows them."""
    return (("Claude", claude_logo, claude_windows()), ("Copilot", copilot_logo, copilot_windows()))


def draw_summary():
    S = layout.summary
    now = now_or_zero()
    if S.warning_y is not None:
        cols = layout.bar_w // layout.message_font.WIDTH
        line = battery.LOW_BATTERY_WARNING if low_battery() else ""
        text(line, layout.column_x, S.warning_y, cols, RED, face=layout.message_font)
    for y, (name, _, windows) in zip(S.ys, summary_rows()):
        row = None if state.clock_offset is None else usage.summary(windows, now, state.utc_offset)
        right = S.bar_x + S.bar_w
        name_cols = (right - S.name_x) // S.name_font.WIDTH - 10
        text(name, S.name_x, y, name_cols, WHITE, face=S.name_font)
        pct_cols = 9
        text(pct_text(row and row[1]), right - pct_cols * S.pct_font.WIDTH, y + S.pct_dy, pct_cols, WHITE, True, face=S.pct_font)
        text(row[0] if row else "", S.label_x, y + S.label_dy, (right - S.label_x) // S.label_font.WIDTH, GREY, face=S.label_font)
        draw_bar(S.bar_x, y + S.bar_dy, S.bar_w, S.bar_h, row and row[1])
        if row is None:
            verdict = ("Connecting to Wi-Fi..." if not wlan.isconnected() else "Waiting for data", GREY)
        else:
            verdict = (row[2], WHITE if row[3] is None else MESSAGE_COLORS[row[3]])
        cols = (right - S.verdict_x) // S.verdict_font.WIDTH
        text(verdict[0], S.verdict_x, y + S.verdict_dy, cols, verdict[1], face=S.verdict_font)


def draw():
    if state.screen == BATTERY_SCREEN:
        if state.reading:
            draw_battery_screen()
        return
    {SUMMARY_SCREEN: draw_summary, CLAUDE_SCREEN: draw_claude, COPILOT_SCREEN: draw_copilot}[state.screen]()
    if state.reading:
        draw_battery_indicator()


def draw_logo(logo, x, y):
    tft.blit_buffer(logo.BUFFER, x, y, logo.WIDTH, logo.HEIGHT)


def draw_static():
    if state.screen == BATTERY_SCREEN:
        draw_battery_static()
        return
    tft.fill(BLACK)
    x = layout.message_x
    if state.screen == SUMMARY_SCREEN:
        S = layout.summary
        if S.title_y is not None:
            text("Usage", layout.column_x, S.title_y, 5, WHITE, face=layout.label_font)
        tft.hline(x, S.divider_y, tft.width - 2 * x, TRACK)
        for y, (_, logo, _) in zip(S.ys, summary_rows()):
            draw_logo(logo, S.logo_x, y)
        return
    tft.hline(x, layout.divider_y, tft.width - 2 * x, TRACK)
    draw_logo(claude_logo if state.screen == CLAUDE_SCREEN else copilot_logo, layout.logo_x, layout.logo_y)


def window_from(payload, key):
    w = payload.get(key)
    if not w:
        return None
    return (float(w["pct"]), int(w["resets_at"]))


def apply_update(payload):
    """Store an update from the Mac: Claude's windows, Copilot's This month, or both."""
    state.clock_offset = int(payload["now"]) - time.time()
    state.utc_offset = int(payload.get("utc_offset", 0))
    if "session" in payload or "week" in payload:
        # Claude Code drops a window once it resets; keep the old one so the board shows 0% itself.
        state.session = window_from(payload, "session") or state.session
        state.week = window_from(payload, "week") or state.week
        state.claude_updated = time.time()
    copilot = payload.get("copilot")
    if copilot:
        state.month = (float(copilot["pct"]), int(copilot["resets_at"]))
        state.month_length = int(copilot["resets_at"]) - int(copilot["starts_at"])
        state.credits = (int(copilot["used"]), int(copilot["entitlement"]))
        state.copilot_updated = time.time()
    state.changed.set()


async def respond(writer, status):
    writer.write(b"HTTP/1.0 " + status + b"\r\nContent-Length: 0\r\n\r\n")
    await writer.drain()


async def handle(reader, writer):
    try:
        request = await reader.readline()
        headers = {}
        while True:
            line = await reader.readline()
            if line in (b"\r\n", b"\n", b""):
                break
            key, _, value = line.decode().partition(":")
            headers[key.strip().lower()] = value.strip()
        if not request.startswith(b"POST /usage "):
            await respond(writer, b"404 Not Found")
        elif headers.get("x-token") != wifi_secrets.DEVICE_TOKEN:
            await respond(writer, b"403 Forbidden")
        else:
            length = int(headers.get("content-length", "0"))
            if not 0 < length <= MAX_BODY:
                await respond(writer, b"400 Bad Request")
            else:
                apply_update(json.loads(await reader.readexactly(length)))
                await respond(writer, b"204 No Content")
    except Exception as e:
        print("request failed:", e)
        try:
            await respond(writer, b"400 Bad Request")
        except Exception:
            pass
    finally:
        writer.close()
        await writer.wait_closed()


async def keep_wifi():
    network.hostname(HOSTNAME)
    wlan.active(True)
    while True:
        if not wlan.isconnected():
            print("connecting to", wifi_secrets.WIFI_SSID)
            wlan.connect(wifi_secrets.WIFI_SSID, wifi_secrets.WIFI_PASSWORD)
            for _ in range(30):
                if wlan.isconnected():
                    print("connected", wlan.ifconfig()[0])
                    state.changed.set()
                    break
                await asyncio.sleep(1)
            else:
                wlan.disconnect()
        await asyncio.sleep(10)


def show(screen):
    state.screen = screen
    state.screen_changed = True
    state.changed.set()


async def watch_battery():
    while True:
        try:
            r = power.read()
        except OSError as e:
            print("battery read failed:", e)  # try again next time round
            r = None
        if r:
            old, state.reading = state.reading, r
            state.estimator.update(r, time.time())
            level = battery.brightness(r)
            if level != state.brightness:
                tft.brightness(level)
                state.brightness = level
            if old is None or old.usb_connected != r.usb_connected:
                state.changed.set()  # plugging in or unplugging shows at once
        await asyncio.sleep(BATTERY_SECONDS)


def on_press(point):
    """A tap at point (x, y) on the touch screen, or a button press (point None)."""
    if point is None:
        show(BUTTON_CYCLE[(BUTTON_CYCLE.index(state.screen) + 1) % len(BUTTON_CYCLE)])
    elif state.screen != SUMMARY_SCREEN:
        show(SUMMARY_SCREEN)
    else:
        S = layout.summary
        y = point[1]
        if power and y < S.top_h:
            show(BATTERY_SCREEN)
        else:
            show(CLAUDE_SCREEN if y < S.divider_y else COPILOT_SCREEN)


async def watch_input():
    was_down = False
    while True:
        point = hw.touch.point() if hw.touch else None
        down = point is not None if hw.touch else hw.button.pressed()
        if down and not was_down:
            state.last_input = time.time()
            on_press(point)
        was_down = down
        if state.screen != SUMMARY_SCREEN and time.time() - state.last_input >= IDLE_SECONDS:
            show(SUMMARY_SCREEN)
        await asyncio.sleep_ms(INPUT_MS)


async def redraw():
    while True:
        if state.screen_changed:
            state.screen_changed = False
            draw_static()
        draw()
        state.changed.clear()
        seconds = BATTERY_SECONDS if state.screen == BATTERY_SCREEN else REDRAW_SECONDS
        try:
            await asyncio.wait_for(state.changed.wait(), seconds)
        except asyncio.TimeoutError:
            pass


async def main():
    draw_static()
    asyncio.create_task(keep_wifi())
    if power:
        asyncio.create_task(watch_battery())
    if hw.touch or hw.button:
        asyncio.create_task(watch_input())
    await asyncio.start_server(handle, "0.0.0.0", 80)
    await redraw()


if __name__ == "__main__":
    asyncio.run(main())
