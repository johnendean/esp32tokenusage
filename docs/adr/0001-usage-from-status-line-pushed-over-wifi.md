# Usage comes from the Claude Code status line, pushed to the board over Wi-Fi

The only documented source of Current session and This week usage is the `rate_limits` field in Claude Code's status line input, so a wrapper around the existing status line command forwards the raw percentages and Reset times to the board over Wi-Fi. The board keeps its own clock (NTP plus a UTC offset from the Mac) and derives the reset text and Pace message itself, so the screen stays correct between updates.

## Considered Options

- **Undocumented OAuth usage endpoint that `/usage` calls**: would let the board poll without Claude Code running, but it is undocumented, may change without notice, and would put an account credential on the board.
- **USB serial instead of Wi-Fi**: no network setup, but the board has no clock, so reset text and the Pace message would freeze between status line updates; opening the port can also reset the board and clashes with `mpremote`.

## Consequences

The display only receives new numbers while a Claude Code session is active and has had at least one response.
