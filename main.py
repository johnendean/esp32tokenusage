import json
import time

import asyncio
import network
from machine import Pin, SPI

import claude_logo
import st7789py as st7789
import usage
import vga1_8x16 as font
import wifi_secrets

HOSTNAME = wifi_secrets.DEVICE_HOST.split(".")[0]
REDRAW_SECONDS = 30
MAX_BODY = 2048

# Waveshare ESP32-C6-LCD-1.47 pinout (ST7789, 172x320, panel offset 34 px)
spi = SPI(1, baudrate=40_000_000, polarity=0, phase=0, sck=Pin(7), mosi=Pin(6), miso=Pin(5))
tft = st7789.ST7789(
    spi,
    172,
    320,
    reset=Pin(21, Pin.OUT),
    cs=Pin(14, Pin.OUT),
    dc=Pin(15, Pin.OUT),
    backlight=Pin(22, Pin.OUT),
    rotation=1,  # landscape, verified the right way up with the board as mounted
    custom_rotations=(
        (0x00, 172, 320, 34, 0, False),
        (0x60, 320, 172, 0, 34, False),
        (0xC0, 172, 320, 34, 0, False),
        (0xA0, 320, 172, 0, 34, False),
    ),
)

BLACK = st7789.BLACK
WHITE = st7789.WHITE
ORANGE = st7789.color565(0xD9, 0x77, 0x57)
RED = st7789.color565(0xE0, 0x45, 0x3A)
GREY = st7789.color565(0x99, 0x99, 0x99)
TRACK = st7789.color565(0x33, 0x33, 0x33)
MESSAGE_COLORS = {usage.ON_TRACK: WHITE, usage.CLOSE: ORANGE, usage.LIMIT: RED}

# Layout (320x172): Pace message across the top, logo left, two Usage bar rows right.
MARGIN = 4
MESSAGE_Y = 4
DIVIDER_Y = 24
COLUMN_X = 60
BAR_W = tft.width - COLUMN_X - 8
BAR_H = 8
ROW_YS = (42, 106)
LOGO_Y = 74
MESSAGE_CHARS = (tft.width - 2 * MARGIN) // font.WIDTH
RESET_CHARS = (tft.width - COLUMN_X) // font.WIDTH


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


def text(s, x, y, width_chars, color, align_right=False):
    s = s[:width_chars]
    s = ("%" + ("" if align_right else "-") + str(width_chars) + "s") % s
    tft.text(font, s, x, y, color, BLACK)


def draw_row(y, label, window, now):
    text(label, COLUMN_X, y, 15, WHITE)
    if window is None:
        pct, reset = None, ""
    else:
        pct, reset = usage.current_pct(window, now), usage.reset_text(window, now, state.utc_offset)
    text("--% used" if pct is None else "%d%% used" % round(pct), tft.width - 8 - 9 * font.WIDTH, y, 9, WHITE, True)

    filled = 0 if pct is None else min(BAR_W, round(BAR_W * pct / 100))
    bar_y = y + 20
    if filled:
        tft.fill_rect(COLUMN_X, bar_y, filled, BAR_H, RED if pct >= 90 else ORANGE)
    if filled < BAR_W:
        tft.fill_rect(COLUMN_X + filled, bar_y, BAR_W - filled, BAR_H, TRACK)
    text(reset, COLUMN_X, y + 32, RESET_CHARS, GREY)


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
    text(message[0], MARGIN, MESSAGE_Y, MESSAGE_CHARS, message[1])
    draw_row(ROW_YS[0], "Current session", state.session, now)
    draw_row(ROW_YS[1], "This week", state.week, now)


def draw_static():
    tft.fill(BLACK)
    tft.hline(MARGIN, DIVIDER_Y, tft.width - 2 * MARGIN, TRACK)
    tft.blit_buffer(claude_logo.BUFFER, MARGIN, LOGO_Y, claude_logo.WIDTH, claude_logo.HEIGHT)


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
