from machine import Pin, SPI
import st7789py as st7789
import vga2_16x32 as font

# Waveshare ESP32-C6-LCD-1.47 pinout (ST7789, 172x320, panel offset x=34,y=0)
spi = SPI(
    1,
    baudrate=40_000_000,
    polarity=0,
    phase=0,
    sck=Pin(7),
    mosi=Pin(6),
    miso=Pin(5),
)

tft = st7789.ST7789(
    spi,
    172,
    320,
    reset=Pin(21, Pin.OUT),
    cs=Pin(14, Pin.OUT),
    dc=Pin(15, Pin.OUT),
    backlight=Pin(22, Pin.OUT),
    rotation=0,
    custom_rotations=(
        (0x00, 172, 320, 34, 0, False),
        (0x60, 320, 172, 0, 34, False),
        (0xC0, 172, 320, 34, 0, False),
        (0xA0, 320, 172, 0, 34, False),
    ),
)

tft.fill(st7789.BLACK)

words = ("Hello", "World")
for i, word in enumerate(words):
    x = (tft.width - len(word) * font.WIDTH) // 2
    y = (tft.height - len(words) * font.HEIGHT) // 2 + i * font.HEIGHT
    tft.text(font, word, x, y, st7789.WHITE, st7789.BLACK)
