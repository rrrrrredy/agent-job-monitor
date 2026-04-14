#!/usr/bin/env bash
# setup.sh - First-use dependency detection and installation
# Usage: bash scripts/setup.sh

set -e

echo "🔍 Checking agent-job-monitor dependencies..."

MISSING=0

# Dependency 1: Python packages (requests + playwright)
echo ""
echo "--- Dependency 1: Python packages ---"
PIP_MISSING=0

if python3 -c "import requests" &>/dev/null; then
  echo "✅ requests"
else
  echo "⚠️  requests not installed"
  PIP_MISSING=1
fi

if python3 -c "import playwright" &>/dev/null; then
  echo "✅ playwright"
else
  echo "⚠️  playwright not installed"
  PIP_MISSING=1
fi

if [ "$PIP_MISSING" -eq 1 ]; then
  MISSING=1
  echo "📦 Installing Python dependencies..."
  pip install requests playwright
fi

# Dependency 2: Playwright Chromium browser
echo ""
echo "--- Dependency 2: Playwright Chromium Browser ---"
if python3 -c "
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    b.close()
    print('ok')
" &>/dev/null 2>&1; then
  echo "✅ Playwright Chromium installed"
else
  echo "⚠️  Playwright Chromium not installed (~150MB download)"
  MISSING=1
  echo "📦 Downloading Playwright Chromium..."
  python3 -m playwright install chromium || {
    echo "❌ Chromium download failed. Behind corporate network? Try:"
    echo "   PLAYWRIGHT_DOWNLOAD_HOST=https://your-mirror python3 -m playwright install chromium"
  }
fi

# Dependency 3: HTTP Proxy (optional, for MiniMax Feishu ATS)
echo ""
echo "--- Dependency 3: HTTP Proxy (optional) ---"
if [ -n "$HTTP_PROXY" ] || [ -n "$HTTPS_PROXY" ]; then
  echo "✅ HTTP_PROXY configured: ${HTTP_PROXY:-$HTTPS_PROXY}"
else
  echo "ℹ️  No HTTP_PROXY set (only needed if your IP is blocked by Feishu ATS for MiniMax)"
  echo "   To configure: export HTTP_PROXY=http://your-proxy:port"
fi

if [ "$MISSING" -eq 0 ]; then
  echo ""
  echo "✅ All dependencies ready"
else
  echo ""
  echo "✅ Dependency installation complete (check above for any failures)"
fi

# Final verification
echo ""
echo "🔍 Final verification..."
python3 -c "import requests; print('✅ requests')" 2>/dev/null || echo "❌ requests missing"
python3 -c "import playwright; print('✅ playwright')" 2>/dev/null || echo "❌ playwright missing"

echo "🎉 Setup complete, agent-job-monitor is ready to use"
