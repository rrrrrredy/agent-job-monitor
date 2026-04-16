#!/bin/bash
# 每日 Agent 岗位监控主入口
# Cron: 0 10 * * * (UTC) = 北京时间 18:00

set -e

DATE=$(date +%Y-%m-%d)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE="$SCRIPT_DIR/.."

echo "=== Agent 岗位监控 $DATE ==="
echo "工作目录: $WORKSPACE"
echo "开始时间: $(date '+%Y-%m-%d %H:%M:%S')"
echo ""

# ─────────────────────────────────────────
# 依赖自检（shell 层，快速失败）
# ─────────────────────────────────────────
MISSING_DEPS=0

if ! command -v python3 &>/dev/null; then
    echo "❌ 缺少 python3 — 安装：https://python.org/downloads/"
    MISSING_DEPS=1
fi

if ! python3 -c "import requests" &>/dev/null 2>&1; then
    echo "❌ 缺少 Python 包 requests — 安装：pip install requests"
    MISSING_DEPS=1
fi

if ! command -v agent-browser &>/dev/null; then
    echo "⚠️  缺少 agent-browser（阿里/智谱/Kimi 采集将降级跳过）"
    echo "   安装：npm i -g agent-browser && agent-browser install"
fi

if ! python3 -c "import playwright" &>/dev/null 2>&1; then
    echo "⚠️  缺少 playwright（MiniMax 采集将降级跳过）"
    echo "   安装：pip install playwright && python3 -m playwright install chromium"
fi


if [ "$MISSING_DEPS" -eq 1 ]; then
    echo ""
    echo "❌ 存在必要依赖缺失，请先安装后重新运行。"
    exit 1
fi

echo ""

# Step 1: 采集
echo "--- Step 1: 采集 ---"
python3 "$SCRIPT_DIR/daily_collect.py" --date "$DATE"

# Step 2: Diff
echo "--- Step 2: Diff ---"
python3 "$SCRIPT_DIR/daily_diff.py" --date "$DATE"

# Step 3: Push report to docs platform (optional, requires oa-skills CLI)
echo "--- Step 3: Push report ---"
if command -v oa-skills &>/dev/null; then
    python3 "$SCRIPT_DIR/push_citadel.py" --date "$DATE" || echo "⚠️ Docs push failed (non-fatal), continuing"
else
    echo "⚠️ oa-skills not installed, docs push skipped. Report saved to reports/ directory."
    # Still generate local report
    python3 "$SCRIPT_DIR/push_citadel.py" --date "$DATE" --local-only 2>/dev/null || echo "⚠️ Local report generation also failed"
fi

# Step 4: IM notification (handled by cron agent's message tool)
# Note: Script does not embed IM push. The cron agent's internal message tool
# uses the main process bridge client, which is more reliable than subprocess CLI.
echo "--- Step 4: IM notification (handled by cron agent) ---"
echo "Collection + diff + docs push complete. IM notification delegated to cron agent."

echo ""
echo "结束时间: $(date '+%Y-%m-%d %H:%M:%S')"
echo "=== 完成 ==="
