"""
AXP2101 power chip on the Waveshare ESP32-S3-Touch-AMOLED-1.8: charges the
battery and measures it. Register meanings follow the AXP2101 datasheet.
"""

import battery

_ADDRESS = 0x34
_STATUS1 = 0x00
_STATUS2 = 0x01
_GAUGE_CONTROL = 0x18
_ADC_ENABLE = 0x30
_BATTERY_MV = 0x34
_USB_MV = 0x38
_CHIP_TEMP = 0x3C
_LEVEL = 0xA4

_GAUGE_ON = 0x08
_ADC_ON = 0x15  # battery voltage, USB voltage, chip temperature
_STAGES = (battery.TRICKLE, battery.PRECHARGE, battery.FAST, battery.TOP_UP, battery.DONE, battery.STOPPED)


class AXP2101:
    def __init__(self, i2c, address=_ADDRESS):
        self.i2c = i2c
        self.address = address
        self._set_bits(_GAUGE_CONTROL, _GAUGE_ON)
        self._set_bits(_ADC_ENABLE, _ADC_ON)

    def _read(self, register, n=1):
        return self.i2c.readfrom_mem(self.address, register, n)

    def _set_bits(self, register, bits):
        value = self._read(register)[0]
        if value & bits != bits:
            self.i2c.writeto_mem(self.address, register, bytes([value | bits]))

    def _adc(self, register, high_bits):
        high, low = self._read(register, 2)
        return ((high & ((1 << high_bits) - 1)) << 8) | low

    def read(self):
        """Return a battery.Reading of the chip right now."""
        status1, status2 = self._read(_STATUS1, 2)
        present = bool(status1 & 0x08)
        usb = bool(status1 & 0x20)
        return battery.Reading(
            battery_present=present,
            usb_connected=usb,
            charging=(status2 >> 5) & 0x03 == 0x01,
            stage=_STAGES[status2 & 0x07] if status2 & 0x07 < len(_STAGES) else battery.STOPPED,
            level=min(100, self._read(_LEVEL)[0]) if present else None,
            battery_mv=self._adc(_BATTERY_MV, 5) if present else None,
            usb_mv=self._adc(_USB_MV, 6) if usb else None,
            chip_c=22 + (7274 - self._adc(_CHIP_TEMP, 6)) / 20,
            hot=bool(status1 & 0x02),
            usb_limited=bool(status1 & 0x01),
        )
