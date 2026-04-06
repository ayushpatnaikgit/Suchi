#!/bin/bash
# Suchi — one-command setup for developers
# Usage: ./setup.sh

set -e

echo "[ suchi ] — Setting up..."
echo ""

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3.11+ is required. Install from https://python.org"
    exit 1
fi

PY_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "✓ Python $PY_VERSION"

# Check Node
if ! command -v node &> /dev/null; then
    echo "Error: Node.js 18+ is required. Install from https://nodejs.org"
    exit 1
fi

NODE_VERSION=$(node --version)
echo "✓ Node $NODE_VERSION"

# Install backend
echo ""
echo "Installing backend..."
cd backend
pip install -e ".[dev]" --quiet
cd ..
echo "✓ Backend installed (suchi CLI available)"

# Install frontend
echo ""
echo "Installing frontend..."
cd frontend
npm install --silent
cd ..
echo "✓ Frontend installed"

# Create default config if it doesn't exist
CONFIG_DIR="$HOME/.config/suchi"
if [ ! -f "$CONFIG_DIR/config.yaml" ]; then
    mkdir -p "$CONFIG_DIR"
    cat > "$CONFIG_DIR/config.yaml" << 'YAML'
library_dir: ~/Documents/Suchi Library
sync:
  backend: none
ai:
  gemini_api_key: ""
  model: gemini-2.5-flash
default_export_format: bibtex
YAML
    echo "✓ Config created at $CONFIG_DIR/config.yaml"
else
    echo "✓ Config exists at $CONFIG_DIR/config.yaml"
fi

# Create library directory
LIBRARY_DIR=$(python3 -c "from suchi.config import get_config; print(get_config().library_dir)" 2>/dev/null || echo "$HOME/Documents/Suchi Library")
mkdir -p "$LIBRARY_DIR"
echo "✓ Library at $LIBRARY_DIR"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  [ suchi ] is ready!"
echo ""
echo "  CLI:       suchi --help"
echo "  Add paper: suchi add 10.1038/nature12373"
echo "  Search:    suchi search 'machine learning'"
echo "  Web UI:    suchi serve  (then open localhost:9876)"
echo ""
echo "  To set up AI chat:"
echo "    suchi config set ai.gemini_api_key YOUR_KEY"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
