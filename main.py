import json
import time

import asyncio
import framebuf
import network

import board
import claude_logo
import st7789py as st7789
import usage
import vga1_8x16 as font
import wifi_secrets

HOSTNAME = wifi_secrets.DEVICE_HOST.split(".")[0]
REDRAW_SECONDS = 30
MAX_BODY = 2048

tft, layout = board.setup()

BLACK = st7789.BLACK
WHITE = st7789.WHITE
ORANGE = st7789.color565(0xD9, 0x77, 0x57)
RED = st7789.color565(0xE0, 0x45, 0x3A)
GREY = st7789.color565(0x99, 0x99, 0x99)
TRACK = st7789.color565(0x33, 0x33, 0x33)
MESSAGE_COLORS = {usage.ON_TRACK: WHITE, usage.CLOSE: ORANGE, usage.LIMIT: RED}


class State:
    session = None  # (pct, resets_at)
    week = None
    utc_offset = 0
    clock_offset = None  # add to time.time() to get Unix epoch seconds from the Mac
    changed = asyncio.Event()


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
        code = ord(ch)
        if not face.FIRST <= code < face.LAST:
            code = ord("?")
        start = (code - face.FIRST) * size
        glyph = framebuf.FrameBuffer(glyphs[start : start + size], w, h, framebuf.MONO_HLSB)
        line.blit(glyph, i * w, 0, -1, palette)
    tft.blit_buffer(out, x, y, w * len(s), h)


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
    face = layout.message_font
    for i, line in enumerate(usage.wrap_lines(message[0], layout.message_chars, layout.message_lines)):
        text(line, layout.message_x, layout.message_y + i * (face.HEIGHT + 2), layout.message_chars, message[1], face=face)
    draw_row(layout.row_ys[0], "Current session", state.session, now)
    draw_row(layout.row_ys[1], "This week", state.week, now)


def draw_static():
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


async def redraw():
    while True:
        draw()
        state.changed.clear()
        try:
            await asyncio.wait_for(state.changed.wait(), REDRAW_SECONDS)
        except asyncio.TimeoutError:
            pass


async def main():
    draw_static()
    asyncio.create_task(keep_wifi())
    await asyncio.start_server(handle, "0.0.0.0", 80)
    await redraw()


if __name__ == "__main__":
    asyncio.run(main())
