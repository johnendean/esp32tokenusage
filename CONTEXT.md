# Agent Usage Display

A desk display on an ESP32 that shows how much of each coding Agent's usage allowance is left, so it is visible at a glance.

## Language

**Agent**:
A coding assistant subscription whose usage allowance the display shows: Claude or Copilot.
_Avoid_: Tool, provider, service, monitor

**Current session**:
Claude's rolling 5-hour usage limit, expressed as a percentage used.
_Avoid_: Session usage, 5-hour limit, conversation

**This week**:
Claude's rolling 7-day usage limit (all models combined), expressed as a percentage used.
_Avoid_: Weekly usage, week limit, seven-day

**This month**:
Copilot's monthly allowance of AI credits, expressed as credits and a percentage used. It resets on the 1st of each month.
_Avoid_: Monthly quota, premium requests, billing period

**AI credits**:
The unit Copilot measures its monthly allowance in, e.g. "893 of 1500 AI credits".
_Avoid_: Premium requests, interactions, tokens

**Usage bar**:
One horizontal bar plus its "N% used" figure, representing one usage window: Current session, This week or This month.
_Avoid_: Progress bar, meter

**Reset time**:
The moment a usage window rolls over and its usage returns to zero.
_Avoid_: Renewal, refresh

**Pace message**:
A one-line verdict on whether current usage will outlast the window before its Reset time: On track, Cutting it close, or a projected limit time.
_Avoid_: Status, forecast, "on track" message

**Summary screen**:
The screen the display starts on: one row per Agent with its most pressing Usage bar and a short pace verdict.
_Avoid_: Home screen, main page, overview, dashboard

**Agent screen**:
One Agent's detail screen: its logo, Pace message and every Usage bar it has. The Claude screen shows Current session and This week; the Copilot screen shows This month and AI credits used.
_Avoid_: Usage screen, detail page, status page

**Battery screen**:
A detail screen, on boards with a battery, showing the Charge level, Charging state and other readings in plain words. Tapping the Battery indicator opens it; a tap anywhere returns to the Summary screen, as does a short idle time.
_Avoid_: Battery page, power screen, status page

**Battery indicator**:
The small battery icon and Charge level in the top-right corner of the Summary screen and Agent screens, with a lightning bolt while charging.
_Avoid_: Battery icon, battery status

**Charge level**:
How full the battery is, as a percentage, taken from the power chip's own estimate rather than worked out from voltage.
_Avoid_: Battery percentage, battery status, SoC

**Charging state**:
A plain-words phrase saying what the battery is doing, such as "Charging", "Charged", "On battery" or "Plugged in, not charging". It's never shown as a code or number.
_Avoid_: Battery status, charge status

**Low battery warning**:
The red "Battery low, plug in" line shown when the Charge level is 5% or below and USB isn't connected: across the top of the Summary screen, and in place of the Pace message on Agent screens. From 10% down, on battery, the screen also dims to half brightness, returning to full as soon as USB is connected.
_Avoid_: Battery alert, low power message
