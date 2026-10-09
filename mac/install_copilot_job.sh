#!/bin/bash
# Install (or reinstall) the launchd job that sends Copilot usage to the display every 5 minutes.
# Remove it with: launchctl bootout gui/$(id -u)/local.agent-usage-display.copilot
set -euo pipefail
dir="$(cd "$(dirname "$0")" && pwd)"
label="local.agent-usage-display.copilot"
plist="$HOME/Library/LaunchAgents/$label.plist"
python="$(command -v python3)"
log="$HOME/Library/Logs/agent-usage-display-copilot.log"

mkdir -p "$HOME/Library/LaunchAgents"
cat > "$plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$label</string>
  <key>ProgramArguments</key>
  <array><string>$python</string><string>$dir/push_copilot.py</string></array>
  <key>StartInterval</key><integer>300</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>$log</string>
  <key>StandardErrorPath</key><string>$log</string>
</dict>
</plist>
PLIST

launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$plist"
echo "Installed $label: runs every 5 minutes, logs to $log"
