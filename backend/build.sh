#!/bin/bash
# ── TokenOps — Build Standalone Executable ──
# Creates a single binary that runs without Python installed.
#
# Prerequisites:
#   pip install pyinstaller
#   pip install -r requirements.txt
#
# Usage:
#   cd backend
#   chmod +x build.sh
#   ./build.sh
#
# Output:
#   dist/TokenOps       (macOS/Linux — ~30MB)
#   dist/TokenOps.exe   (Windows — ~30MB)

set -e

echo ""
echo "╔══════════════════════════════════╗"
echo "║    TokenOps — Building...        ║"
echo "╚══════════════════════════════════╝"
echo ""

# Check we're in the right directory
if [ ! -f "run.py" ]; then
    echo "ERROR: Run this from the backend/ directory"
    echo "  cd backend && ./build.sh"
    exit 1
fi

# Install build dependencies
echo "Installing dependencies..."
pip install pyinstaller -q
pip install -r requirements.txt -q

# Clean previous builds
rm -rf build/ dist/ __pycache__

# Build
echo "Building standalone executable..."
pyinstaller tokenops.spec --clean --noconfirm 2>&1 | tail -5

# Check output
if [ -f "dist/TokenOps" ] || [ -f "dist/TokenOps.exe" ]; then
    echo ""
    echo "╔══════════════════════════════════╗"
    echo "║    Build successful!             ║"
    echo "╚══════════════════════════════════╝"
    echo ""
    ls -lh dist/TokenOps* 2>/dev/null
    echo ""
    echo "To run:  ./dist/TokenOps"
    echo "Dashboard opens at http://localhost:8000/dashboard"
    echo ""
    echo "To distribute:"
    echo "  macOS:   zip dist/TokenOps and send the .zip"
    echo "  Windows: send dist/TokenOps.exe directly"
    echo "  Linux:   tar -czf TokenOps.tar.gz -C dist TokenOps"
else
    echo "ERROR: Build failed. Check output above."
    exit 1
fi
