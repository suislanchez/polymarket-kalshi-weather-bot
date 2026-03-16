#!/bin/bash
# Auto-pull merged changes from GitHub and restart services if updated
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "$(date): Checking for updates..."

# Fetch latest from main branch
git fetch origin main

# Check if there are new commits
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)

if [ "$LOCAL" = "$REMOTE" ]; then
    echo "$(date): Already up to date."
    exit 0
fi

echo "$(date): New changes found. Pulling..."
git pull origin main

# Reinstall Python dependencies if requirements changed
if git diff "$LOCAL" "$REMOTE" --name-only | grep -q "requirements.txt"; then
    echo "$(date): requirements.txt changed, installing dependencies..."
    pip3 install -r requirements.txt --quiet
fi

# Rebuild frontend if frontend files changed
if git diff "$LOCAL" "$REMOTE" --name-only | grep -q "^frontend/"; then
    echo "$(date): Frontend changed, rebuilding..."
    cd frontend
    npm install --quiet
    npm run build
    cd ..
    launchctl unload ~/Library/LaunchAgents/com.kalshi.weatherbot-frontend.plist 2>/dev/null || true
    launchctl load ~/Library/LaunchAgents/com.kalshi.weatherbot-frontend.plist
    echo "$(date): Frontend restarted."
fi

# Restart backend
echo "$(date): Restarting backend..."
launchctl unload ~/Library/LaunchAgents/com.kalshi.weatherbot.plist 2>/dev/null || true
launchctl load ~/Library/LaunchAgents/com.kalshi.weatherbot.plist

echo "$(date): Update complete."
