#!/bin/bash
# Setup script for running kalshi-weather-bot as a background service on macOS
# This uses launchd (the native macOS way to manage background services)

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLIST_NAME="com.kalshi.weatherbot"
PLIST_SRC="$SCRIPT_DIR/$PLIST_NAME.plist"
PLIST_DEST="$HOME/Library/LaunchAgents/$PLIST_NAME.plist"

echo "=== Kalshi Weather Bot - macOS Service Setup ==="
echo ""
echo "Project directory: $SCRIPT_DIR"

# 1. Check for .env file
if [ ! -f "$SCRIPT_DIR/.env" ]; then
    echo ""
    echo "WARNING: No .env file found!"
    echo "Copy .env.example to .env and fill in your API keys first:"
    echo "  cp .env.example .env"
    echo "  nano .env"
    echo ""
    read -p "Continue anyway? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# 2. Install Python dependencies if needed
echo ""
echo "Installing Python dependencies..."
pip3 install -r "$SCRIPT_DIR/requirements.txt" --quiet

# 3. Create logs directory
mkdir -p "$SCRIPT_DIR/logs"

# 4. Unload existing service if running
if launchctl list | grep -q "$PLIST_NAME" 2>/dev/null; then
    echo "Stopping existing service..."
    launchctl unload "$PLIST_DEST" 2>/dev/null || true
fi

# 5. Generate plist with correct paths
echo "Installing LaunchAgent..."
mkdir -p "$HOME/Library/LaunchAgents"
sed "s|__INSTALL_DIR__|$SCRIPT_DIR|g" "$PLIST_SRC" > "$PLIST_DEST"

# 6. Load the service
echo "Starting service..."
launchctl load "$PLIST_DEST"

echo ""
echo "=== Setup Complete ==="
echo ""
echo "The bot is now running in the background and will:"
echo "  - Start automatically when you log in"
echo "  - Restart automatically if it crashes"
echo "  - Keep running after you close the terminal"
echo ""
echo "Useful commands:"
echo "  View status:    launchctl list | grep kalshi"
echo "  View logs:      tail -f $SCRIPT_DIR/logs/bot-stdout.log"
echo "  View errors:    tail -f $SCRIPT_DIR/logs/bot-stderr.log"
echo "  Stop service:   launchctl unload $PLIST_DEST"
echo "  Start service:  launchctl load $PLIST_DEST"
echo "  Restart:        launchctl unload $PLIST_DEST && launchctl load $PLIST_DEST"
echo ""
echo "API will be available at: http://localhost:8000"
echo "API docs at:              http://localhost:8000/docs"
