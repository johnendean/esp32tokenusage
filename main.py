import json
import time

import asyncio
import framebuf
import network

import battery
import board
import claude_logo
import st7789py as st7789
import usage
import vga1_8x16 as font
import wifi_secrets

# Each board announces its own name, e.g. claude-usage-s3.local, so several can share a network.
HOSTNAME = "%s-%s" % (wifi_secrets.DEVICE_NAME, board.detect())
REDRAW_SECONDS = 30
MAX_BODY = 2048
BATTERY_SECONDS = 2  # how often the power chip is read and the Battery screen redrawn
TOUCH_MS = 50
BATTERY_SCREEN_IDLE = 30  # seconds without a touch before the Usage screen comes back
USAGE_SCREEN, BATTERY_SCREEN = "usage", "battery"

tft, layout, power, touch = board.setup()

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
    utc_offset = 0
    clock_offset = None  # add to time.time() to get Unix epoch seconds from the Mac
    changed = asyncio.Event()
    reading = None  # latest battery.Reading, on boards with a battery
    estimator = battery.Estimator()
    brightness = None
    screen = USAGE_SCREEN
    screen_changed = False  # the whole screen needs drawing again
    last_touch = 0
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


def draw_row(y, label, window, now):
    L = layout
    text(label, L.column_x, y, 15, WHITE, face=L.label_font)
    if window is None:
        pct, reset = None, ""
    else:
        pct, reset = usage.current_pct(window, now), usage.reset_text(window, now, state.utc_offset)
    pct_x = L.column_x + L.bar_w - 9 * font.WIDTH
    text("--% used" if pct is None else "%d%% used" % round(pct), pct_x, y + L.pct_dy, 9, WHITE, True)

    filled = 0 if pct is None else min(L.bar_w, round(L.bar_w * pct / 100))
    bar_y = y + L.bar_dy
    if filled:
        tft.fill_rect(L.column_x, bar_y, filled, L.bar_h, RED if pct >= 90 else ORANGE)
    if filled < L.bar_w:
        tft.fill_rect(L.column_x + filled, bar_y, L.bar_w - filled, L.bar_h, TRACK)
    text(reset, L.column_x, y + L.reset_dy, L.reset_chars, GREY)


def draw():
    if state.clock_offset is None:
        if wlan.isconnected():
            message = ("Waiting for data  " + wlan.ifconfig()[0], GREY)
        else:
            message = ("Connecting to Wi-Fi...", GREY)
        now = 0
    else:
        now = unix_now()
        message = usage.pace_message(state.session, state.week, now, state.utc_offset)
        message = (message[0], MESSAGE_COLORS[message[1]]) if message else ("", WHITE)
    if state.reading and battery.low_battery_warning(state.reading):
        message = (battery.LOW_BATTERY_WARNING, RED)
    face = layout.message_font
    for i, line in enumerate(usage.wrap_lines(message[0], layout.message_chars, layout.message_lines)):
        text(line, layout.message_x, layout.message_y + i * (face.HEIGHT + 2), layout.message_chars, message[1], face=face)
    draw_row(layout.row_ys[0], "Current session", state.session, now)
    draw_row(layout.row_ys[1], "This week", state.week, now)
    if state.reading:
        draw_battery_indicator()


def draw_static():
    if state.screen == BATTERY_SCREEN:
        draw_battery_static()
        return
    tft.fill(BLACK)
    x = layout.message_x
    tft.hline(x, layout.divider_y, tft.width - 2 * x, TRACK)
    tft.blit_buffer(claude_logo.BUFFER, layout.logo_x, layout.logo_y, claude_logo.WIDTH, claude_logo.HEIGHT)


def window_from(payload, key):
    w = payload.get(key)
    if not w:
        return None
    return (float(w["pct"]), int(w["resets_at"]))


def apply_update(payload):
    state.clock_offset = int(payload["now"]) - time.time()
    state.utc_offset = int(payload.get("utc_offset", 0))
    # Claude Code drops a window once it resets; keep the old one so the board shows 0% itself.
    state.session = window_from(payload, "session") or state.session
    state.week = window_from(payload, "week") or state.week
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
        if state.screen == BATTERY_SCREEN and time.time() - state.last_touch >= BATTERY_SCREEN_IDLE:
            show(USAGE_SCREEN)
        await asyncio.sleep(BATTERY_SECONDS)


async def watch_touch():
    was_down = False
    while True:
        down = touch.touched()
        if down and not was_down:
            state.last_touch = time.time()
            show(USAGE_SCREEN if state.screen == BATTERY_SCREEN else BATTERY_SCREEN)
        was_down = down
        await asyncio.sleep_ms(TOUCH_MS)


async def redraw():
    while True:
        if state.screen_changed:
            state.screen_changed = False
            draw_static()
        if state.screen == BATTERY_SCREEN:
            if state.reading:
                draw_battery_screen()
        else:
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
    if touch:
        asyncio.create_task(watch_touch())
    await asyncio.start_server(handle, "0.0.0.0", 80)
    await redraw()


if __name__ == "__main__":
    asyncio.run(main())
