#!/bin/bash
# Setup script for running kalshi-weather-bot as a background service on macOS
# This uses launchd (the native macOS way to manage background services)

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLIST_NAME="com.kalshi.weatherbot"
PLIST_SRC="$SCRIPT_DIR/$PLIST_NAME.plist"
PLIST_DEST="$HOME/Library/LaunchAgents/$PLIST_NAME.plist"

FRONTEND_PLIST_NAME="com.kalshi.weatherbot-frontend"
FRONTEND_PLIST_SRC="$SCRIPT_DIR/$FRONTEND_PLIST_NAME.plist"
FRONTEND_PLIST_DEST="$HOME/Library/LaunchAgents/$FRONTEND_PLIST_NAME.plist"

AUTOPULL_PLIST_NAME="com.kalshi.weatherbot-autopull"
AUTOPULL_PLIST_SRC="$SCRIPT_DIR/$AUTOPULL_PLIST_NAME.plist"
AUTOPULL_PLIST_DEST="$HOME/Library/LaunchAgents/$AUTOPULL_PLIST_NAME.plist"

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

# 2. Install dependencies
echo ""
echo "Installing Python dependencies..."
pip3 install -r "$SCRIPT_DIR/requirements.txt" --quiet

echo "Installing frontend dependencies..."
cd "$SCRIPT_DIR/frontend" && npm install --silent && npm run build && cd "$SCRIPT_DIR"

# 3. Create logs directory
mkdir -p "$SCRIPT_DIR/logs"

# 4. Unload existing services if running
if launchctl list | grep -q "$PLIST_NAME" 2>/dev/null; then
    echo "Stopping existing backend service..."
    launchctl unload "$PLIST_DEST" 2>/dev/null || true
fi
if launchctl list | grep -q "$FRONTEND_PLIST_NAME" 2>/dev/null; then
    echo "Stopping existing frontend service..."
    launchctl unload "$FRONTEND_PLIST_DEST" 2>/dev/null || true
fi
if launchctl list | grep -q "$AUTOPULL_PLIST_NAME" 2>/dev/null; then
    echo "Stopping existing autopull service..."
    launchctl unload "$AUTOPULL_PLIST_DEST" 2>/dev/null || true
fi

# 5. Generate plists with correct paths
echo "Installing LaunchAgents..."
mkdir -p "$HOME/Library/LaunchAgents"
sed "s|__INSTALL_DIR__|$SCRIPT_DIR|g" "$PLIST_SRC" > "$PLIST_DEST"
sed "s|__INSTALL_DIR__|$SCRIPT_DIR|g" "$FRONTEND_PLIST_SRC" > "$FRONTEND_PLIST_DEST"
sed "s|__INSTALL_DIR__|$SCRIPT_DIR|g" "$AUTOPULL_PLIST_SRC" > "$AUTOPULL_PLIST_DEST"

# 6. Load services
echo "Starting services..."
launchctl load "$PLIST_DEST"
launchctl load "$FRONTEND_PLIST_DEST"
launchctl load "$AUTOPULL_PLIST_DEST"

echo ""
echo "=== Setup Complete ==="
echo ""
echo "The bot is now running in the background and will:"
echo "  - Start automatically when you log in"
echo "  - Restart automatically if it crashes"
echo "  - Keep running after you close the terminal"
echo ""
echo "Useful commands:"
echo "  View status:      launchctl list | grep kalshi"
echo "  Backend logs:     tail -f $SCRIPT_DIR/logs/bot-stdout.log"
echo "  Frontend logs:    tail -f $SCRIPT_DIR/logs/frontend-stdout.log"
echo "  Stop backend:     launchctl unload $PLIST_DEST"
echo "  Stop frontend:    launchctl unload $FRONTEND_PLIST_DEST"
echo "  Start backend:    launchctl load $PLIST_DEST"
echo "  Start frontend:   launchctl load $FRONTEND_PLIST_DEST"
echo ""
echo "Dashboard:  http://localhost:3000  (or http://localhost:8000 via backend)"
echo "API:        http://localhost:8000"
echo "API docs:   http://localhost:8000/docs"
echo ""
echo "For remote access (cruise ship, hotel, etc.):"
echo "  ./setup-tunnel.sh    # Sets up Cloudflare Tunnel with public URL"
