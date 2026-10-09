"""
CST816-family touch controller on the Waveshare ESP32-S3-Touch-AMOLED-1.8.

Only "where is the finger, if any?" is needed, so it is polled rather than
wired to the interrupt pin.
"""

_ADDRESS = 0x15
_FINGERS = 0x02  # followed by X high, X low, Y high, Y low
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

    def point(self):
        """(x, y) of the finger on the screen, or None when nothing is touching it."""
        try:
            b = self.i2c.readfrom_mem(self.address, _FINGERS, 5)
        except OSError:
            return None
        if not b[0] & 0x0F:
            return None
        return ((b[1] & 0x0F) << 8 | b[2], (b[3] & 0x0F) << 8 | b[4])
