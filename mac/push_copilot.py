"""Send Copilot's This month usage to the display.

Run every 5 minutes by a launchd job (see install_copilot_job.sh). The figures
come from the internal endpoint VS Code and the Copilot CLI use, read with the
existing `gh` login: see docs/adr/0002-copilot-usage-polled-by-a-mac-background-job.md.
"""
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone

import push_usage

# launchd starts jobs with a bare PATH, so look where Homebrew installs gh too.
SEARCH_PATH = os.pathsep.join([os.environ.get("PATH", ""), "/opt/homebrew/bin", "/usr/local/bin"])


def fetch():
    gh = shutil.which("gh", path=SEARCH_PATH)
    if gh is None:
        raise RuntimeError("gh not found: install the GitHub CLI and run 'gh auth login'")
    out = subprocess.run(
        [gh, "api", "/copilot_internal/user"], capture_output=True, text=True, timeout=30, check=True
    ).stdout
    return json.loads(out)


def month_start(resets_at):
    """Midnight UTC on the 1st of the month before the reset."""
    year, month = (resets_at.year, resets_at.month - 1) if resets_at.month > 1 else (resets_at.year - 1, 12)
    return datetime(year, month, 1, tzinfo=timezone.utc)


def build_payload(user, now):
    """The board's update for This month, or None if the plan has no monthly AI credit limit."""
    quota = (user.get("quota_snapshots") or {}).get("premium_interactions")
    reset = user.get("quota_reset_date")
    if not quota or quota.get("unlimited") or not quota.get("entitlement") or not reset:
        return None
    resets_at = datetime.strptime(reset, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    entitlement = quota["entitlement"]
    return {
        "now": int(now),
        "utc_offset": push_usage.utc_offset(),
        "copilot": {
            "pct": round(100 - quota["percent_remaining"], 1),
            "used": round(entitlement - quota["quota_remaining"]),
            "entitlement": entitlement,
            "resets_at": int(resets_at.timestamp()),
            "starts_at": int(month_start(resets_at).timestamp()),
        },
    }


def main():
    payload = build_payload(fetch(), time.time())
    if payload is None:
        print("Copilot plan has no monthly AI credit limit; nothing to show", file=sys.stderr)
        return
    _, errors = push_usage.send_to_boards(payload)
    if errors:
        print("; ".join(errors), file=sys.stderr)


if __name__ == "__main__":
    main()
