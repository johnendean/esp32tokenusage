#!/bin/bash
# Claude Code status line: forwards plan usage to the desk display, then renders ccstatusline as before.
input=$(cat)
dir="$(cd "$(dirname "$0")" && pwd)"
printf '%s' "$input" | python3 "$dir/push_usage.py" >/dev/null 2>&1
printf '%s' "$input" | npx ccstatusline@latest
