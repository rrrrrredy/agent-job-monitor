#!/bin/bash
# Daily Agent Job Monitor entry point
# Cron: 0 10 * * * (UTC) = Beijing time 18:00

set -e

DATE=$(date +%Y-%m-%d)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE="$SCRIPT_DIR/.."

echo "=== Agent Job Monitor $DATE ==="
echo "Working directory: $WORKSPACE"
echo "Start time: $(date '+%Y-%m-%d %H:%M:%S')"
echo ""

# ─────────────────────────────────────────
# Dependency check (shell layer, fail-fast)
# ─────────────────────────────────────────
MISSING_DEPS=0

if ! command -v python3 &>/dev/null; then
    echo "❌ Missing python3 — install: https://python.org/downloads/"
    MISSING_DEPS=1
fi

if ! python3 -c "import requests" &>/dev/null 2>&1; then
    echo "❌ Missing Python package requests — install: pip install requests"
    MISSING_DEPS=1
fi

if ! command -v agent-browser &>/dev/null; then
    echo "⚠️  Missing agent-browser (Alibaba/Zhipu/Kimi collection will be skipped)"
    echo "   Install: npm i -g agent-browser && agent-browser install"
fi

if ! python3 -c "import playwright" &>/dev/null 2>&1; then
    echo "⚠️  Missing playwright (MiniMax collection will be skipped)"
    echo "   Install: pip install playwright && python3 -m playwright install chromium"
fi


if [ "$MISSING_DEPS" -eq 1 ]; then
    echo ""
    echo "❌ Required dependencies missing. Please install them first."
    exit 1
fi

echo ""

# Step 1: Collect
echo "--- Step 1: Collect ---"
python3 "$SCRIPT_DIR/daily_collect.py" --date "$DATE"

# Step 2: Diff
echo "--- Step 2: Diff ---"
python3 "$SCRIPT_DIR/daily_diff.py" --date "$DATE"

# Step 3: IM Notification
# Note: IM notification is handled by the cron agent via the message tool.
# Reason: subprocess-launched CLI is a separate process without bridge connection, cannot send IM.
# The cron agent's internal message tool uses the main process bridge client, which is stable and reliable.
echo "--- Step 3: IM Notification (handled by cron agent message tool) ---"
echo "Collection + diff complete. IM notification delegated to cron agent."

echo ""
echo "End time: $(date '+%Y-%m-%d %H:%M:%S')"
echo "=== Done ==="
