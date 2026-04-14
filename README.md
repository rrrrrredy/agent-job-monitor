# agent-job-monitor

AI company Agent/LLM job monitoring system — daily automated collection, analysis, report generation, and notifications.

An [OpenClaw](https://github.com/openclaw/openclaw) Skill that monitors Agent-related job postings across 7 major AI companies:
**ByteDance · Tencent · Alibaba · Aliyun · Zhipu AI · Kimi · MiniMax**

## Features

- 📊 **Daily automated collection** from 7 companies via HTTP API, Playwright DOM, and Feishu ATS interception
- 📈 **Multi-dimensional analysis**: company landscape, Agent sub-directions, recruitment types, city distribution
- 📝 **12-section reports** with deep insights on new jobs, industry signals, and strategic trends
- 🔔 **IM notifications** with concise daily summaries
- 🔄 **Smart fallback**: API → Playwright DOM → proxy bypass — per-company strategy

## Installation

### Option A: OpenClaw (recommended)
```bash
git clone https://github.com/rrrrrredy/agent-job-monitor ~/.openclaw/skills/agent-job-monitor
cd ~/.openclaw/skills/agent-job-monitor
bash scripts/setup.sh
```

### Option B: Standalone
```bash
git clone https://github.com/rrrrrredy/agent-job-monitor
cd agent-job-monitor
bash scripts/setup.sh
```

## Dependencies

| Dependency | Required | Purpose |
|-----------|----------|---------|
| Python 3.10+ | ✅ | Runtime |
| `requests` | ✅ | ByteDance/Tencent API collection |
| `playwright` + Chromium | ✅ | MiniMax Feishu ATS collection |
| `agent-browser` | ✅ | Alibaba/Zhipu/Kimi DOM collection |
| HTTP proxy | Optional | Only if your IP is blocked by Feishu ATS |

## Quick Start

```bash
# 1. Install dependencies
bash scripts/setup.sh

# 2. Run manual test
bash scripts/run_daily.sh

# 3. Register daily cron (Beijing 18:00 = UTC 10:00)
openclaw cron add --name "Agent Job Daily" --schedule "0 10 * * *" \
  --message "Run: bash ~/.openclaw/skills/agent-job-monitor/scripts/run_daily.sh"
```

## Collection Methods

| Company | Method | Speed |
|---------|--------|-------|
| ByteDance | `jobs.bytedance.com` JSON API | ⚡ Fast |
| Tencent | `careers.tencent.com` JSON API | ⚡ Fast |
| Alibaba | Playwright DOM scraping | 🐢 Slow |
| Aliyun | Playwright DOM scraping | 🐢 Slow |
| Zhipu AI | mokahr.com DOM parsing | 🐢 Slow |
| Kimi | mokahr.com DOM parsing | 🐢 Slow |
| MiniMax | Feishu ATS + request interception | ⏱️ Medium |

## Project Structure

```
agent-job-monitor/
├── SKILL.md                        # Main skill definition
├── gotchas.md                      # Troubleshooting dictionary
├── scripts/
│   ├── daily_collect.py            # Multi-company job collector
│   ├── daily_diff.py               # Day-over-day comparison
│   ├── push_citadel.py             # Report generator & publisher
│   ├── notify_im.py                # IM notification sender
│   ├── run_daily.sh                # Daily entry point
│   └── setup.sh                    # Dependency installer
├── references/
│   ├── company-endpoints.md        # API endpoints & strategies
│   └── schema.md                   # Data schema docs
├── snapshots/                      # Daily snapshots (auto-created)
├── diffs/                          # Daily diffs (auto-created)
└── reports/                        # Local report backups (auto-created)
```

## License

MIT
