# Copy to wifi_secrets.py (git-ignored) and fill in. Used by the board and by mac/push_usage.py.
WIFI_SSID = "your-network"
WIFI_PASSWORD = "your-password"
# Shared secret the Mac sends with each update; the board rejects updates without it.
DEVICE_TOKEN = "change-me"
# Hostname the board announces on the network; the Mac sends updates here.
DEVICE_HOST = "claude-usage.local"
