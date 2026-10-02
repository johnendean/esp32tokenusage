"""
Detects which supported board this is and sets up its display.

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
    return tft, Layout(
        message_x=4,
        message_y=4,
        message_font=small,
        message_lines=1,
        message_chars=(tft.width - 8) // small.WIDTH,
        divider_y=24,
        logo_x=4,
        logo_y=74,
        column_x=column_x,
        bar_w=tft.width - column_x - 8,
        row_ys=(42, 106),
        label_font=small,
        pct_dy=0,  # "N% used" sits on the label line
        bar_dy=20,
        bar_h=8,
        reset_dy=32,
        reset_chars=(tft.width - column_x) // small.WIDTH,
    )


def _s3_amoled():
    import co5300
    import spleen_12x24 as medium
    import vga2_16x32 as big

    i2c = I2C(0, sda=Pin(15), scl=Pin(14), freq=400_000)
    # miso must be given: the default MISO pin belongs to the octal PSRAM.
    spi = SPI(2, baudrate=40_000_000, polarity=0, phase=0, sck=Pin(11), mosi=Pin(4), miso=Pin(5))
    tft = co5300.CO5300(spi, Pin(12, Pin.OUT), i2c)
    # 368x448 portrait: logo and Pace message at the top, Usage bars stacked below.
    margin = 16
    bar_w = tft.width - 2 * margin
    return tft, Layout(
        message_x=margin,
        message_y=84,
        message_font=medium,
        message_lines=2,
        message_chars=bar_w // medium.WIDTH,
        divider_y=144,
        logo_x=(tft.width - 48) // 2,
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
    )


def setup():
    """Return (display, Layout) for the board this is running on."""
    chip = os.uname().machine.upper().replace("-", "")
    if "ESP32S3" in chip:
        return _s3_amoled()
    if "ESP32C6" in chip:
        return _c6_lcd()
    raise RuntimeError("Unsupported board: " + os.uname().machine)
