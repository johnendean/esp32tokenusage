# Copy to wifi_secrets.py (git-ignored) and fill in. Used by the board and by mac/push_usage.py.
WIFI_SSID = "your-network"
WIFI_PASSWORD = "your-password"
# Shared secret the Mac sends with each update; the board rejects updates without it.
DEVICE_TOKEN = "change-me"
# Boards announce themselves as <DEVICE_NAME>-<board>.local, e.g. claude-usage-c6.local.
DEVICE_NAME = "claude-usage"
# Boards the Mac sends updates to, separated by commas.
DEVICE_HOSTS = "claude-usage-c6.local, claude-usage-s3.local"
