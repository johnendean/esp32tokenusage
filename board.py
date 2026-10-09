"""
Detects which supported board this is and sets up its display and controls:
the BOOT button on the C6, the touch screen and power chip on the S3.

The chip family tells the boards apart: the Waveshare ESP32-C6-LCD-1.47 and
the Waveshare ESP32-S3-Touch-AMOLED-1.8.
"""

import os

from machine import I2C, SPI, Pin

import vga1_8x16 as small


class Layout:
    """Where the usage display puts things on a given screen."""

    def __init__(self, **kwargs):
        for name, value in kwargs.items():
            setattr(self, name, value)


class Board:
    """What setup() found: display, Layout, and the parts only some boards have
    (power chip, touch controller, button), None where missing."""

    def __init__(self, tft, layout, power=None, touch=None, button=None):
        self.tft = tft
        self.layout = layout
        self.power = power
        self.touch = touch
        self.button = button


class Button:
    """A push button wired to pull its pin low when pressed."""

    def __init__(self, pin):
        self.pin = Pin(pin, Pin.IN, Pin.PULL_UP)

    def pressed(self):
        return self.pin.value() == 0


def _c6_lcd():
    import st7789py as st7789

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
    # 320x172: Pace message across the top, logo left, two Usage bar rows right.
    column_x = 60
    bar_w = tft.width - column_x - 8
    layout = Layout(
        message_x=4,
        message_y=4,
        message_font=small,
        message_lines=1,
        message_chars=(tft.width - 8) // small.WIDTH,
        divider_y=24,
        logo_x=4,
        logo_y=74,
        column_x=column_x,
        bar_w=bar_w,
        row_ys=(42, 106),
        label_font=small,
        pct_dy=0,  # "N% used" sits on the label line
        bar_dy=20,
        bar_h=8,
        reset_dy=32,
        reset_chars=(tft.width - column_x) // small.WIDTH,
        credits_y=106,  # Copilot screen: where the second Usage bar would be
        credits_font=small,
        updated_y=156,
        # Summary screen: one row per Agent, logo left, text and bar right.
        summary=Layout(
            ys=(12, 96),
            divider_y=86,
            title_y=None,
            warning_y=None,
            logo_x=4,
            name_x=column_x,
            name_font=small,
            pct_dy=0,
            pct_font=small,
            label_x=column_x,
            label_dy=32,
            label_font=small,
            bar_x=column_x,
            bar_w=bar_w,
            bar_dy=20,
            bar_h=8,
            verdict_x=column_x,
            verdict_dy=48,
            verdict_font=small,
        ),
    )
    return Board(tft, layout, button=Button(9))  # BOOT: also selects download mode if held at reset


def _s3_amoled():
    import axp2101
    import co5300
    import cst816
    import spleen_12x24 as medium
    import vga2_16x32 as big

    i2c = I2C(0, sda=Pin(15), scl=Pin(14), freq=400_000)
    # miso must be given: the default MISO pin belongs to the octal PSRAM.
    spi = SPI(2, baudrate=40_000_000, polarity=0, phase=0, sck=Pin(11), mosi=Pin(4), miso=Pin(5))
    tft = co5300.CO5300(spi, Pin(12, Pin.OUT), i2c)
    # 368x448 portrait: logo top left, Battery indicator top right, Pace message
    # below them, Usage bars stacked under that.
    margin = 16
    bar_w = tft.width - 2 * margin
    layout = Layout(
        message_x=margin,
        message_y=84,
        message_font=medium,
        message_lines=2,
        message_chars=bar_w // medium.WIDTH,
        divider_y=144,
        logo_x=margin,
        logo_y=24,
        column_x=margin,
        bar_w=bar_w,
        row_ys=(176, 326),
        label_font=big,
        pct_dy=76,  # "N% used" shares the reset line, right-aligned
        bar_dy=42,
        bar_h=24,
        reset_dy=76,
        reset_chars=(bar_w - 10 * small.WIDTH) // small.WIDTH,
        # Battery indicator, top right, level with the middle of the logo: its right edge.
        battery_x=tft.width - margin,
        battery_y=40,
        battery_font=medium,
        credits_y=286,  # Copilot screen: under its only Usage bar
        credits_font=medium,
        updated_y=428,
        # Summary screen: title and Battery indicator on top, then one row per Agent.
        summary=Layout(
            ys=(112, 280),
            divider_y=260,
            title_y=24,
            warning_y=76,
            top_h=100,  # a tap above this opens the Battery screen
            logo_x=margin,
            name_x=80,
            name_font=big,
            pct_dy=4,
            pct_font=medium,
            label_x=80,
            label_dy=36,
            label_font=medium,
            bar_x=margin,
            bar_w=bar_w,
            bar_dy=72,
            bar_h=24,
            verdict_x=margin,
            verdict_dy=104,
            verdict_font=medium,
        ),
    )
    return Board(tft, layout, power=axp2101.AXP2101(i2c), touch=cst816.CST816(i2c))


def detect():
    """Short name for the board this is running on: "c6" or "s3"."""
    chip = os.uname().machine.upper().replace("-", "")
    if "ESP32S3" in chip:
        return "s3"
    if "ESP32C6" in chip:
        return "c6"
    raise RuntimeError("Unsupported board: " + os.uname().machine)


def setup():
    """Return the Board this is running on."""
    return _s3_amoled() if detect() == "s3" else _c6_lcd()
