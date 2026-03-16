#!/bin/bash
# Setup Cloudflare Tunnel for remote access to the Kalshi Weather Bot dashboard
# This allows access from anywhere (cruise ship WiFi, hotels, etc.) without VPN
#
# How it works:
#   - cloudflared creates an outbound HTTPS connection to Cloudflare's edge
#   - You get a public URL like https://random-words.trycloudflare.com
#   - No account needed, no ports to open, works through any firewall
#   - The URL changes each time the tunnel restarts (check logs for current URL)

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TUNNEL_PLIST_NAME="com.kalshi.weatherbot-tunnel"
TUNNEL_PLIST_SRC="$SCRIPT_DIR/$TUNNEL_PLIST_NAME.plist"
TUNNEL_PLIST_DEST="$HOME/Library/LaunchAgents/$TUNNEL_PLIST_NAME.plist"

echo "=== Cloudflare Tunnel Setup ==="
echo ""

# 1. Check/install cloudflared
if ! command -v cloudflared &>/dev/null; then
    echo "Installing cloudflared via Homebrew..."
    if ! command -v brew &>/dev/null; then
        echo "ERROR: Homebrew not found. Install it first:"
        echo '  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
        exit 1
    fi
    brew install cloudflared
else
    echo "cloudflared is already installed: $(which cloudflared)"
fi

# 2. Create logs directory
mkdir -p "$SCRIPT_DIR/logs"

# 3. Unload existing tunnel if running
if launchctl list | grep -q "$TUNNEL_PLIST_NAME" 2>/dev/null; then
    echo "Stopping existing tunnel..."
    launchctl unload "$TUNNEL_PLIST_DEST" 2>/dev/null || true
fi

# 4. Install plist with correct paths
echo "Installing tunnel LaunchAgent..."
mkdir -p "$HOME/Library/LaunchAgents"
sed "s|__INSTALL_DIR__|$SCRIPT_DIR|g" "$TUNNEL_PLIST_SRC" > "$TUNNEL_PLIST_DEST"

# 5. Detect cloudflared path (Intel vs Apple Silicon)
CLOUDFLARED_PATH="$(which cloudflared)"
sed -i '' "s|/opt/homebrew/bin/cloudflared|$CLOUDFLARED_PATH|g" "$TUNNEL_PLIST_DEST"

# 6. Load the tunnel service
echo "Starting tunnel..."
launchctl load "$TUNNEL_PLIST_DEST"

echo ""
echo "=== Tunnel Started ==="
echo ""
echo "The tunnel URL will appear in the logs in a few seconds."
echo "Run this to see your public URL:"
echo ""
echo "  grep -o 'https://[^ ]*\.trycloudflare\.com' $SCRIPT_DIR/logs/tunnel-stderr.log | tail -1"
echo ""
echo "Or watch the logs live:"
echo "  tail -f $SCRIPT_DIR/logs/tunnel-stderr.log"
echo ""
echo "Useful commands:"
echo "  Get URL:      grep -o 'https://[^ ]*\.trycloudflare\.com' $SCRIPT_DIR/logs/tunnel-stderr.log | tail -1"
echo "  Stop tunnel:  launchctl unload $TUNNEL_PLIST_DEST"
echo "  Start tunnel: launchctl load $TUNNEL_PLIST_DEST"
echo "  View status:  launchctl list | grep kalshi"
echo ""
echo "NOTE: The URL changes each time the tunnel restarts."
echo "      The dashboard will be available at the tunnel URL."
echo "      API docs at <tunnel-url>/docs"

# 7. Wait a moment and try to show the URL
sleep 5
TUNNEL_URL=$(grep -o 'https://[^ ]*\.trycloudflare\.com' "$SCRIPT_DIR/logs/tunnel-stderr.log" 2>/dev/null | tail -1)
if [ -n "$TUNNEL_URL" ]; then
    echo ""
    echo "========================================="
    echo "  Your dashboard URL: $TUNNEL_URL"
    echo "========================================="
fi
