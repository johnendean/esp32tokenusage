#!/bin/bash
# Upload the display program to the board over USB and restart it.
set -euo pipefail
cd "$(dirname "$0")"
port="${1:-/dev/cu.usbmodem1101}"
[ -f wifi_secrets.py ] || { echo "Create wifi_secrets.py from wifi_secrets_example.py first" >&2; exit 1; }
.venv/bin/mpremote connect "$port" \
  cp board.py co5300.py axp2101.py cst816.py battery.py spleen_12x24.py st7789py.py vga1_8x16.py vga2_16x32.py claude_logo.py usage.py wifi_secrets.py main.py : + reset
