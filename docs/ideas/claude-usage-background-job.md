# Idea: also poll Claude usage from a Mac background job

Status: parked (2026-10-11). Nothing is built; this records the discussion so it can be picked up later.

## The gap

Claude's Current session and This week only reach the boards when Claude Code runs its status line on this Mac ([ADR 0001](../adr/0001-usage-from-status-line-pushed-over-wifi.md)). That covers most cases:

- **Using Claude Code here:** every response pushes fresh numbers.
- **Not using Claude at all:** the numbers don't change, and the board's own clock zeroes a Usage bar when its Reset time passes.

What it misses is usage elsewhere: claude.ai, the desktop or mobile apps, or Claude Code on another machine. All of it counts against the same limits, but the board doesn't see it until Claude Code next runs here.

## The option

Now that a launchd job already sends Copilot's This month ([ADR 0002](../adr/0002-copilot-usage-polled-by-a-mac-background-job.md)), a similar job could fetch Claude's usage every 5 minutes. It would call the undocumented Anthropic endpoint that Claude Code's `/usage` command uses, and send the result to the boards through the usual `POST /usage`.

ADR 0001 rejected that endpoint mainly because it would put an account credential on the board. A job on the Mac avoids that: the credential never leaves the Mac.

## Problems still open

1. **It's undocumented.** The endpoint could change or disappear without notice. Only the job would break; the status line would keep working.
2. **It needs your Claude login.** The job would read Claude Code's sign-in token from the macOS Keychain. Because it runs in the background, macOS may ask to allow that the first time.
3. **The token expires.** The token is short-lived, and Claude Code renews it while it runs. After a long break from Claude Code, the job's copy may have expired, so it would skip updates until Claude Code renews it. It would stall rather than fail outright.

## If picked up

- Run it alongside the status line, not in place of it. The status line stays the instant path while Claude Code is in use; the job fills the gaps from other devices.
- First check that the endpoint answers with the Keychain token from a launchd job. That includes whether a Keychain prompt appears, and what happens once the token has expired.
- Record the decision as a new ADR, since it partly reverses ADR 0001.
