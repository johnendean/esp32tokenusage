"""
CO5300 AMOLED driver for the Waveshare ESP32-S3-Touch-AMOLED-1.8 (368x448).

The panel is wired for QSPI, but it also accepts single-line SPI writes
(opcode 0x02), so a plain machine.SPI on the D0 line can drive it.

The controller ignores windows that start on an odd pixel or span an odd
number of pixels, so drawing goes into a shadow copy of the screen and the
touched area is sent out widened to even boundaries. That keeps the whole
st7789py drawing API (text, lines, blits) usable unchanged.
"""

import struct
from time import sleep_ms

import framebuf

import st7789py

_EXPANDER = 0x20  # TCA9554-compatible I/O expander
_EXPANDER_OUTPUT = 0x01
_EXPANDER_CONFIG = 0x03
_PANEL_PINS = 0x07  # EXIO0-2: panel power and reset

_INIT_CMDS = (
    (0xFE, b"\x00", 0),  # user command page
    (0xC4, b"\x80", 0),  # SPI mode control
    (0x3A, b"\x55", 0),  # 16-bit RGB565
    (0x35, b"\x00", 0),  # tearing effect on
    (0x53, b"\x20", 0),  # brightness control on
    (0x63, b"\xff", 0),  # HBM brightness
    (0x11, b"", 120),  # sleep out
    (0x29, b"", 20),  # display on
    (0x51, b"\xff", 0),  # brightness
)


class _NoPin:
    """Stands in for the DC pin st7789py toggles; QSPI panels have none."""

    def on(self):
        pass

    def off(self):
        pass


class CO5300(st7789py.ST7789):
    """
    Args:
        spi (SPI): bus with sck on the panel clock and mosi on D0. Give miso
            explicitly (e.g. D1): the ESP32-S3 default MISO pin belongs to
            the octal PSRAM and claiming it crashes the chip.
        cs (Pin): chip select
        i2c (I2C): bus with the I/O expander that powers and resets the panel
        xstart (int): first visible column in the controller's memory
    """

    def __init__(self, spi, cs, i2c, width=368, height=448, xstart=16, ystart=0):
        self.spi = spi
        self.cs = cs
        self.i2c = i2c
        self.dc = _NoPin()
        self.reset = None
        self.backlight = None
        self.physical_width = self.width = width
        self.physical_height = self.height = height
        self.xstart = xstart
        self.ystart = ystart
        self.needs_swap = False
        self._rotation = 0
        self._shadow = bytearray(width * height * 2)
        self._fb = framebuf.FrameBuffer(self._shadow, width, height, framebuf.RGB565)
        self._window = None
        self._cursor = 0
        cs.on()
        self.hard_reset()
        for command, data, delay in _INIT_CMDS:
            self._command(command, data)
            sleep_ms(delay)
        self.fill(st7789py.BLACK)

    def hard_reset(self):
        config = self.i2c.readfrom_mem(_EXPANDER, _EXPANDER_CONFIG, 1)[0]
        self.i2c.writeto_mem(_EXPANDER, _EXPANDER_CONFIG, bytes([config & ~_PANEL_PINS]))
        output = self.i2c.readfrom_mem(_EXPANDER, _EXPANDER_OUTPUT, 1)[0]
        self.i2c.writeto_mem(_EXPANDER, _EXPANDER_OUTPUT, bytes([output & ~_PANEL_PINS]))
        sleep_ms(20)
        self.i2c.writeto_mem(_EXPANDER, _EXPANDER_OUTPUT, bytes([output | _PANEL_PINS]))
        sleep_ms(150)

    def brightness(self, level):
        """Set panel brightness, 0-255."""
        self._command(0x51, bytes([level]))

    def sleep_mode(self, value):
        self._command(0x10 if value else 0x11)
        sleep_ms(120)

    def rotation(self, rotation):
        raise NotImplementedError("CO5300 driver is portrait only")

    def _command(self, command, data=b""):
        self.cs.off()
        self.spi.write(bytes((0x02, 0, command, 0)))
        if data:
            self.spi.write(data)
        self.cs.on()

    def _set_window(self, x0, y0, x1, y1):
        self._window = (x0, y0, x1, y1)
        self._cursor = 0

    def _write(self, command=None, data=None):
        """Pixel data for the current window lands in the shadow copy."""
        if data is None or self._window is None:
            return
        x0, y0, x1, y1 = self._window
        w = x1 - x0 + 1
        pos = self._cursor
        if not isinstance(data, bytearray):
            data = bytearray(data)  # framebuf needs a writable buffer
        i = 0
        while i < len(data):
            row, col = divmod(pos, w)
            left = (len(data) - i) // 2
            if col == 0 and left >= w:
                cols, rows = w, left // w  # run of whole rows in one blit
            else:
                cols, rows = min(w - col, left), 1  # partial row
            n = cols * rows
            src = framebuf.FrameBuffer(memoryview(data)[i : i + n * 2], cols, rows, framebuf.RGB565)
            self._fb.blit(src, x0 + col, y0 + row)
            i += n * 2
            pos += n
        self._cursor = pos
        if pos >= w * (y1 - y0 + 1):
            self._flush(x0, y0, x1, y1)
            self._window = None

    def fill_rect(self, x, y, width, height, color):
        # framebuf stores pixels little-endian; the panel wants big-endian.
        self._fb.fill_rect(x, y, width, height, ((color & 0xFF) << 8) | (color >> 8))
        x0, y0 = max(x, 0), max(y, 0)
        x1, y1 = min(x + width, self.width) - 1, min(y + height, self.height) - 1
        if x0 <= x1 and y0 <= y1:
            self._flush(x0, y0, x1, y1)

    def _flush(self, x0, y0, x1, y1):
        """Send a shadow region to the panel, widened to even boundaries."""
        x0 &= ~1
        y0 &= ~1
        x1 = min(x1 | 1, self.width - 1)
        y1 = min(y1 | 1, self.height - 1)
        self._command(0x2A, struct.pack(">HH", x0 + self.xstart, x1 + self.xstart))
        self._command(0x2B, struct.pack(">HH", y0 + self.ystart, y1 + self.ystart))
        stride = self.width * 2
        shadow = memoryview(self._shadow)
        self.cs.off()
        self.spi.write(b"\x02\x00\x2c\x00")
        if x0 == 0 and x1 == self.width - 1:
            self.spi.write(shadow[y0 * stride : (y1 + 1) * stride])
        else:
            for r in range(y0, y1 + 1):
                start = r * stride + x0 * 2
                self.spi.write(shadow[start : start + (x1 - x0 + 1) * 2])
        self.cs.on()
