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
