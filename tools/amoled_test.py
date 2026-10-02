# Test pattern for the Waveshare ESP32-S3-Touch-AMOLED-1.8.
# Run with: .venv/bin/mpremote connect <port> cp co5300.py st7789py.py vga1_8x16.py vga2_16x32.py claude_logo.py : + run tools/amoled_test.py
import time

from machine import I2C, SPI, Pin

import claude_logo
import co5300
import st7789py as st7789
import vga1_8x16 as small
import vga2_16x32 as big

i2c = I2C(0, sda=Pin(15), scl=Pin(14), freq=400_000)
spi = SPI(2, baudrate=40_000_000, polarity=0, phase=0, sck=Pin(11), mosi=Pin(4), miso=Pin(5))
start = time.ticks_ms()
tft = co5300.CO5300(spi, Pin(12, Pin.OUT), i2c)

ORANGE = st7789.color565(0xD9, 0x77, 0x57)
GREY = st7789.color565(0x33, 0x33, 0x33)

tft.rect(0, 0, tft.width, tft.height, st7789.WHITE)
tft.rect(3, 3, tft.width - 6, tft.height - 6, ORANGE)
tft.blit_buffer(claude_logo.BUFFER, (tft.width - claude_logo.WIDTH) // 2, 30, claude_logo.WIDTH, claude_logo.HEIGHT)
tft.text(big, "AMOLED", (tft.width - 6 * 16) // 2, 95, st7789.WHITE)
tft.text(small, "368 x 448  CO5300", 49, 140, st7789.WHITE)
tft.text(small, "odd x/y text", 37, 165, ORANGE)

for i, (name, color) in enumerate((("red", st7789.RED), ("green", st7789.GREEN), ("blue", st7789.BLUE))):
    y = 200 + i * 40
    tft.text(small, name, 20, y + 4, st7789.WHITE)
    tft.fill_rect(80, y, 260, 24, GREY)
    tft.fill_rect(80, y, 65 * (i + 2), 24, color)

for i in range(0, 120, 3):
    tft.hline(40, 330 + i // 3 * 2, 1 + i * 2, st7789.WHITE if i % 2 else ORANGE)
tft.line(20, 420, tft.width - 21, 330, st7789.CYAN)

print("drawn in", time.ticks_diff(time.ticks_ms(), start), "ms")
