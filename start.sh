#!/bin/bash
# Weather Edge launcher for macOS / Linux.
# Creates a local venv, installs Python requirements, and starts the dashboard.
set -e

cd "$(dirname "$0")"

echo "Starting Weather Edge..."
echo

PYTHON_BIN="${PYTHON_BIN:-python3}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    echo "ERROR: $PYTHON_BIN not found. Install Python 3.10+ and try again."
    exit 1
fi

if [ ! -d venv ]; then
    echo "Creating virtual environment..."
    "$PYTHON_BIN" -m venv venv
fi

# shellcheck disable=SC1091
source venv/bin/activate

echo "Installing/updating Python dependencies..."
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements.txt

if [ ! -f frontend/dist/index.html ] && [ -f frontend/package.json ]; then
    if command -v npm >/dev/null 2>&1; then
        echo "Building frontend..."
        (cd frontend && npm install && npm run build)
    else
        echo "ERROR: frontend/dist is missing and npm is not installed."
        exit 1
    fi
fi

PORT="${PORT:-8765}"
HOST="${HOST:-127.0.0.1}"

echo
echo "Launching Weather Edge..."
echo "Open http://localhost:${PORT} in your browser."
echo
exec python run.py
