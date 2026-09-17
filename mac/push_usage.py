"""Send Current session and This week usage from Claude Code status line JSON to the display.

Reads the status line JSON on stdin, then detaches so Claude Code never waits on
the network and cannot cancel a send mid-flight. Silently does nothing when the
JSON has no rate limits or the board is unreachable.
"""
import json
import os
import re
import sys
import tempfile
import time
import urllib.request
from datetime import datetime

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
CACHE = os.path.join(tempfile.gettempdir(), "claude-usage-display.json")
RESEND_SECONDS = 60


def settings():
    text = open(os.path.join(ROOT, "wifi_secrets.py")).read()
    return {k: v for k, v in re.findall(r'^(\w+)\s*=\s*"([^"]*)"', text, re.M)}


def window(rate_limits, key):
    w = rate_limits.get(key) or {}
    if w.get("used_percentage") is None or w.get("resets_at") is None:
        return None
    return {"pct": w["used_percentage"], "resets_at": int(w["resets_at"])}


def build_payload(status):
    rate_limits = status.get("rate_limits") or {}
    session, week = window(rate_limits, "five_hour"), window(rate_limits, "seven_day")
    if session is None and week is None:
        return None
    return {
        "now": int(time.time()),
        "utc_offset": int(datetime.now().astimezone().utcoffset().total_seconds()),
        "session": session,
        "week": week,
    }


def should_send(payload):
    """Skip repeats: the status line runs on every conversation change."""
    key = [payload["session"], payload["week"], payload["utc_offset"]]
    try:
        with open(CACHE) as f:
            last = json.load(f)
        if last["key"] == key and payload["now"] - last["sent"] < RESEND_SECONDS:
            return False
    except (OSError, ValueError, KeyError):
        pass
    return True


def send(payload):
    cfg = settings()
    req = urllib.request.Request(
        "http://%s/usage" % cfg["DEVICE_HOST"],
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "X-Token": cfg["DEVICE_TOKEN"]},
        method="POST",
    )
    urllib.request.urlopen(req, timeout=5).close()
    with open(CACHE, "w") as f:
        json.dump({"key": [payload["session"], payload["week"], payload["utc_offset"]], "sent": payload["now"]}, f)


def main():
    try:
        payload = build_payload(json.load(sys.stdin))
    except ValueError:
        return
    if payload is None or not should_send(payload):
        return
    if "--foreground" not in sys.argv and os.fork() != 0:
        return  # parent returns immediately; child carries on detached
    if "--foreground" not in sys.argv:
        os.setsid()
    try:
        send(payload)
    except Exception as e:
        if "--foreground" in sys.argv:
            raise
        print(e, file=sys.stderr)


if __name__ == "__main__":
    main()
