---
name: agent-job-monitor
version: 2.1.0
description: "AI company Agent/LLM job monitoring system. Automatically collects Agent-related job postings from ByteDance, Tencent, Alibaba, Aliyun, Zhipu AI, Kimi, MiniMax using direct APIs and Playwright browser automation. Generates daily reports with competitive analysis. Triggers: Agent job monitor, AI company hiring trends, ByteDance/Tencent/Alibaba Agent hiring, Zhipu/Kimi/MiniMax jobs, today's new jobs, AI talent competition landscape, daily job report. Not applicable: third-party job boards (BOSS/Liepin); AI news/trends/research reports; scholar background checks (use ai-talent-radar)."
tags: [job-monitor, AI, agent, recruitment]
---

# agent-job-monitor 2.1.0

AI company Agent/LLM job monitoring system — daily automated collection → analysis → report generation → notification.

**7/7 companies fully supported**: Tencent, ByteDance (API), Alibaba, Aliyun, Zhipu AI, Kimi (Playwright DOM), MiniMax (Feishu ATS + Playwright)

---

## First Use

```bash
bash scripts/setup.sh
```
> Installs Python packages (`requests`, `playwright`) and downloads Chromium (~150MB).

---

## Prerequisites

### 1. Browser automation (required for Alibaba/Aliyun/Zhipu/Kimi/MiniMax)

**Option A — Playwright (default, used by `daily_collect.py`):**
```bash
pip install requests playwright
python3 -m playwright install chromium
```

**Option B — agent-browser (alternative CLI):**
If you have [agent-browser](https://clawhub.com) installed, you can use it for ad-hoc browser-based job page access. Install: `npm i -g agent-browser` or `npx clawhub install agent-browser`.

> The collection scripts use Playwright programmatically. agent-browser is useful for manual exploration and debugging of job pages.

> ⚠️ If `playwright install chromium` fails behind a corporate network:
> ```bash
> PLAYWRIGHT_DOWNLOAD_HOST=https://your-mirror python3 -m playwright install chromium
> ```

### 2. HTTP Proxy (optional, MiniMax only)

Check if your IP is blocked by Feishu ATS:
```bash
curl -I --max-time 10 https://vrfi1sk8a0.jobs.feishu.cn/379481/
```
- `HTTP/2 200` → Not blocked, no proxy needed
- `403` / timeout → Blocked, set `HTTP_PROXY` environment variable:
```bash
export HTTP_PROXY=http://your-proxy:port
export HTTPS_PROXY=http://your-proxy:port
```

### 3. Document Push CLI (optional)

`push_docs.py` can publish reports to a docs platform via a `docs-push` CLI tool.
Without it, reports are saved locally to `reports/`.

---

## Daily Execution Flow

Cron triggers `run_daily.sh`, chaining three scripts:

```
Step 1: daily_collect.py  → Collect 7 companies → snapshots/{date}.json
Step 2: daily_diff.py     → Compare with yesterday → diffs/{date}-diff.json
Step 3: push_docs.py      → Generate report → save locally (+ publish if docs-push available)
```

### Cron Setup

```bash
# Beijing 18:00 = UTC 10:00
openclaw cron add --name "Agent Job Daily" --schedule "0 10 * * *" \
  --message "Run: bash ~/.openclaw/skills/agent-job-monitor/scripts/run_daily.sh"
```

### Manual Test

```bash
bash scripts/run_daily.sh
```

---

## Collection Methods

| Company | Method | Dependencies | Status |
|---------|--------|-------------|--------|
| Tencent | `careers.tencent.com` REST API | `requests` | ✅ Stable |
| ByteDance | `jobs.bytedance.com` REST API | `requests` | ✅ Stable |
| Alibaba | `talent-holding.alibaba.com` Playwright DOM | `playwright` (or agent-browser) | ✅ Stable |
| Aliyun | `careers.aliyun.com` Playwright DOM | `playwright` (or agent-browser) | ✅ Stable |
| Zhipu AI | `app.mokahr.com/zphz` Playwright DOM | `playwright` (or agent-browser) | ✅ Stable |
| Kimi | `app.mokahr.com/moonshot` Playwright DOM | `playwright` (or agent-browser) | ✅ Stable |
| MiniMax | `vrfi1sk8a0.jobs.feishu.cn` Playwright + proxy | `playwright` (or agent-browser) + optional proxy | ✅ Stable |

**Note**: Tencent/ByteDance APIs return 405 through HTTP proxy — these always use direct connection.

### MiniMax Feishu ATS Details

Feishu ATS Portal is a CSR app — `_signature` is JS-generated, can't be replicated via curl.

`collect_feishu_ats()` uses Playwright Chromium + optional proxy, intercepts `/api/v1/search/job/posts` responses. Reusable for any Feishu ATS tenant (Baichuan, StepFun, 01.AI, DeepSeek, etc.).

---

## Query Interface

| Query | Action |
|-------|--------|
| "How many new Agent jobs today" | Read diff, report new_jobs count |
| "ByteDance Agent jobs" | Read snapshot, filter company |
| "Trend over last week" | Read 7-day snapshots |
| "Run manual collection" | Execute `run_daily.sh` |

---

## Hard Stop

- Single company fails 3× → WARNING, skip, continue others
- Docs push fails → Save locally, note in output
- All companies fail → Stop, alert user

---

## Gotchas

See `references/gotchas.md`. Key points:

| Issue | Solution |
|-------|----------|
| ByteDance/Tencent API 405 through proxy | Direct connection (no proxy for these) |
| Alibaba 403 on direct API | Playwright DOM bypasses IP blocking |
| Feishu ATS `_signature` unforgeable | Must use Playwright browser execution |
| MiniMax jobs lack `id` field | Uses `url` as dedup key |
| cron `--tz` doesn't affect `--at` | Write UTC time: Beijing 18:00 = `0 10 * * *` |

---

## Directory Structure

```
agent-job-monitor/
├── SKILL.md
├── scripts/
│   ├── setup.sh            # Dependency installer
│   ├── daily_collect.py    # Collection (7 companies)
│   ├── daily_diff.py       # Diff calculator
│   ├── push_docs.py        # Report generator + publisher
│   ├── notify_im.py        # IM notification helper
│   └── run_daily.sh        # Daily entry point
├── references/
│   ├── company-endpoints.md
│   ├── gotchas.md          # Known issues & workarounds
│   └── schema.md
├── snapshots/               # Auto-created
├── diffs/                   # Auto-created
└── reports/                 # Auto-created
```

---

## Changelog

### 2.1.0
- **Breaking**: Replaced proprietary browser automation CLI with standard Playwright
- All 7 companies now use either direct API or standard Playwright — no external skill dependencies
- Renamed report publisher script to `push_docs.py` (generic docs publishing)
- Simplified setup: only `requests` + `playwright` needed

### 2.0.5
- Fix: Playwright Chromium corporate network download docs
- Fix: Proxy config self-check step

### 2.0.0
- MiniMax Feishu ATS integration (7/7 complete)
- Generic `collect_feishu_ats()` function
- 12-section report template

### 1.0.0
- Initial release: 6/7 companies, detailed report + notification
