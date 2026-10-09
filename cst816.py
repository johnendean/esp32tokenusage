"""
CST816-family touch controller on the Waveshare ESP32-S3-Touch-AMOLED-1.8.

Only "is a finger down?" is needed, so it is polled rather than wired to the
interrupt pin.
"""

_ADDRESS = 0x15
_FINGERS = 0x02
_DISABLE_AUTO_SLEEP = 0xFE


class CST816:
    def __init__(self, i2c, address=_ADDRESS):
        self.i2c = i2c
        self.address = address
        try:
            # Asleep, the controller stops answering until touched.
            i2c.writeto_mem(address, _DISABLE_AUTO_SLEEP, b"\x01")
        except OSError:
            pass

    def touched(self):
        try:
            return self.i2c.readfrom_mem(self.address, _FINGERS, 1)[0] & 0x0F > 0
        except OSError:
            return False
