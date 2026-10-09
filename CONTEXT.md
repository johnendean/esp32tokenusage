# Claude Usage Display

A desk display on an ESP32 that mirrors the Claude plan usage bars shown by Claude Code, so remaining allowance is visible at a glance.

## Language

**Current session**:
The rolling 5-hour usage limit on the Claude subscription, expressed as a percentage used.
_Avoid_: Session usage, 5-hour limit, conversation

**This week**:
The rolling 7-day usage limit on the Claude subscription (all models combined), expressed as a percentage used.
_Avoid_: Weekly usage, week limit, seven-day

**Usage bar**:
One horizontal bar plus its "N% used" figure, representing either Current session or This week.
_Avoid_: Progress bar, meter

**Reset time**:
The moment a Current session or This week window rolls over and its usage returns to zero.
_Avoid_: Renewal, refresh

**Pace message**:
A one-line verdict on whether current usage will outlast the window before its Reset time: On track, Cutting it close, or a projected limit time.
_Avoid_: Status, forecast, "on track" message

**Usage screen**:
The main screen: the Pace message and the two Usage bars.
_Avoid_: Home screen, main page

**Battery screen**:
A detail screen, on boards with a battery, showing the Charge level, Charging state and other readings in plain words. A tap toggles between it and the Usage screen; it also returns to the Usage screen by itself after a short idle time.
_Avoid_: Battery page, power screen, status page

**Battery indicator**:
The small battery icon and Charge level in the top-right corner, with a lightning bolt while charging.
_Avoid_: Battery icon, battery status

**Charge level**:
How full the battery is, as a percentage, taken from the power chip's own estimate rather than worked out from voltage.
_Avoid_: Battery percentage, battery status, SoC

**Charging state**:
A plain-words phrase saying what the battery is doing, such as "Charging", "Charged", "On battery" or "Plugged in, not charging". It's never shown as a code or number.
_Avoid_: Battery status, charge status

**Low battery warning**:
The red "Battery low, plug in" line that replaces the Pace message when the Charge level is 5% or below and USB isn't connected. From 10% down, on battery, the screen also dims to half brightness, returning to full as soon as USB is connected.
_Avoid_: Battery alert, low power message
