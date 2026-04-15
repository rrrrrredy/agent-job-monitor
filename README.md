# agent-job-monitor

AI company Agent/LLM job monitoring system with daily automated collection, diff analysis, and report generation.

> OpenClaw Skill — works with [OpenClaw](https://github.com/openclaw/openclaw) AI agents

## What It Does

Automatically collects Agent-related job postings from 7 major AI companies (ByteDance, Tencent, Alibaba, Aliyun, Zhipu AI, Kimi, MiniMax) using a combination of direct REST APIs and Playwright browser automation. Generates daily diff reports comparing new/removed positions and supports scheduled push notifications via cron.

## Quick Start

```bash
# Install via ClawHub (recommended)
openclaw skill install agent-job-monitor

# Or clone this repo into your skills directory
git clone https://github.com/rrrrrredy/agent-job-monitor.git ~/.openclaw/skills/agent-job-monitor

# Install dependencies
bash scripts/setup.sh
```

## Features

- **7/7 companies fully supported**: Tencent, ByteDance (API), Alibaba, Aliyun, Zhipu AI, Kimi (Playwright DOM), MiniMax (Feishu ATS + Playwright)
- **Daily automated pipeline**: collect → diff → report → notify, chainable via `run_daily.sh`
- **Dual collection methods**: REST API for Tencent/ByteDance, Playwright browser automation for Alibaba/Aliyun/Zhipu/Kimi/MiniMax
- **MiniMax Feishu ATS integration**: Reusable `collect_feishu_ats()` function works with any Feishu ATS tenant (Baichuan, StepFun, 01.AI, DeepSeek, etc.)
- **Diff analysis**: Compares daily snapshots to identify new and removed job postings
- **Cron scheduling**: Beijing 18:00 daily collection with one-command cron setup
- **Resilient execution**: Single company failure skips gracefully, continues with remaining companies

## Usage

```
"How many new Agent jobs today?"     → Reads diff, reports new job count
"ByteDance Agent jobs"               → Reads snapshot, filters by company
"Trend over last week"               → Reads 7-day snapshots
"Run manual collection"              → Executes run_daily.sh
```

### Cron Setup

```bash
# Beijing 18:00 = UTC 10:00
openclaw cron add --name "Agent Job Daily" --schedule "0 10 * * *" \
  --message "Run: bash ~/.openclaw/skills/agent-job-monitor/scripts/run_daily.sh"
```

## Project Structure

```
agent-job-monitor/
├── SKILL.md                # Main skill definition
├── gotchas.md              # Known issues and solutions
├── scripts/
│   ├── setup.sh            # Dependency installer
│   ├── daily_collect.py    # Collection (7 companies)
│   ├── daily_diff.py       # Diff calculator
│   ├── push_docs.py        # Report generator + publisher
│   ├── notify_im.py        # IM notification helper
│   └── run_daily.sh        # Daily entry point
├── references/
│   ├── company-endpoints.md
│   └── schema.md
├── snapshots/              # Auto-created daily snapshots
├── diffs/                  # Auto-created daily diffs
├── reports/                # Auto-created reports
└── .gitignore
```

## Requirements

- [OpenClaw](https://github.com/openclaw/openclaw) agent runtime
- Python 3.8+
- `requests` (HTTP API calls)
- `playwright` + Chromium (browser automation for Alibaba/Aliyun/Zhipu/Kimi/MiniMax)
- Optional: HTTP proxy for MiniMax Feishu ATS if IP is blocked

## License

[MIT](LICENSE)
