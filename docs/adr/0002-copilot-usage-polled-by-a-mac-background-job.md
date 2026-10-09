# Copilot usage is polled by a Mac background job from an internal GitHub endpoint

Copilot's This month figure (AI credits used of the monthly allowance, and when it resets) is only available from `api.github.com/copilot_internal/user`, the undocumented endpoint VS Code and the Copilot CLI use themselves. A launchd job on the Mac fetches it every 5 minutes with the existing `gh` login and pushes it to the boards, because Copilot is used in places with no hook to piggy-back on, such as VS Code. This knowingly departs from ADR 0001's "no daemon on the Mac" and its rejection of undocumented endpoints: for Copilot there is no documented alternative.

## Considered Options

- **GitHub's documented billing API** (`/users/{user}/settings/billing/premium_request/usage`): returns no items for an individual plan within its allowance, so it cannot show This month.
- **Copilot CLI status line**: its input JSON only carries the current session's figures, not the monthly allowance, and it only runs while the CLI is open.
- **Piggy-backing on the Claude Code status line**: no new process, but Copilot figures would only refresh while Claude Code is in use.
- **The board polling GitHub itself**: would put a GitHub credential on the board.

## Consequences

The endpoint may change or disappear without notice; if it does, only the Copilot screen goes stale. The Copilot numbers refresh while the Mac is awake and logged in to `gh`, whether or not any Agent is in use.
