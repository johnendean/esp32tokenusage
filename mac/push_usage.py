"""Send Current session and This week usage from Claude Code status line JSON to the display.

Reads the status line JSON on stdin, then detaches so Claude Code never waits on
the network and cannot cancel a send mid-flight. Silently does nothing when the
JSON has no rate limits or no board is reachable.
"""
import json
import os
import re
import sys
import tempfile
import threading
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


def utc_offset():
    """The Mac's current offset from UTC in seconds, so the board can show local times."""
    return int(datetime.now().astimezone().utcoffset().total_seconds())


def build_payload(status):
    rate_limits = status.get("rate_limits") or {}
    session, week = window(rate_limits, "five_hour"), window(rate_limits, "seven_day")
    if session is None and week is None:
        return None
    return {
        "now": int(time.time()),
        "utc_offset": utc_offset(),
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


def device_hosts(cfg):
    """Boards to update, from the comma-separated DEVICE_HOSTS setting."""
    return [h.strip() for h in cfg["DEVICE_HOSTS"].split(",") if h.strip()]


def post(host, body, token):
    req = urllib.request.Request(
        "http://%s/usage" % host,
        data=body,
        headers={"Content-Type": "application/json", "X-Token": token},
        method="POST",
    )
    urllib.request.urlopen(req, timeout=5).close()


def send_to_boards(payload):
    """Send to every board at once, so an offline one does not hold up the rest.

    Returns (hosts, errors), one error string per board that could not be reached.
    """
    cfg = settings()
    hosts = device_hosts(cfg)
    if not hosts:
        raise ValueError("DEVICE_HOSTS in wifi_secrets.py lists no boards")
    body = json.dumps(payload).encode()
    errors = []

    def attempt(host):
        try:
            post(host, body, cfg["DEVICE_TOKEN"])
        except Exception as e:
            errors.append("%s: %s" % (host, e))

    threads = [threading.Thread(target=attempt, args=(h,)) for h in hosts]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return hosts, errors


def send(payload):
    hosts, errors = send_to_boards(payload)
    if len(errors) < len(hosts):
        with open(CACHE, "w") as f:
            json.dump({"key": [payload["session"], payload["week"], payload["utc_offset"]], "sent": payload["now"]}, f)
    if errors:
        raise RuntimeError("; ".join(errors))


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
