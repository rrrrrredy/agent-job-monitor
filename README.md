# agent-job-monitor

AI company Agent/LLM job monitoring system — automated daily collection, analysis, and reporting.

## Features

- **7/7 companies monitored**: ByteDance, Tencent, Alibaba, Aliyun, Zhipu AI, Kimi (Moonshot), MiniMax
- **Dual collection modes**: Direct REST API (Tencent/ByteDance) + Playwright browser automation (others)
- **Daily diff analysis**: Tracks new/removed jobs, generates competitive landscape reports
- **12-section reports**: Company distribution, sub-direction analysis, city strategy, trend insights
- **Generic Feishu ATS collector**: Reusable for any company using Feishu recruitment (Baichuan, StepFun, etc.)

## Quick Start

```bash
# 1. Install dependencies
bash scripts/setup.sh

# 2. Manual test run
bash scripts/run_daily.sh

# 3. Set up daily cron (Beijing 18:00 = UTC 10:00)
openclaw cron add --name "Agent Job Daily" --schedule "0 10 * * *" \
  --message "Run: bash scripts/run_daily.sh"
```

## Dependencies

- Python 3.10+
- `requests` — REST API collection
- `playwright` + Chromium — browser-based collection
- HTTP proxy (optional) — only needed if your IP is blocked by Feishu ATS

## Directory Structure

```
agent-job-monitor/
├── scripts/
│   ├── setup.sh            # Dependency installer
│   ├── daily_collect.py    # Collection engine (7 companies)
│   ├── daily_diff.py       # Diff calculator
│   ├── push_docs.py        # Report generator
│   ├── notify_im.py        # IM notification helper
│   └── run_daily.sh        # Daily entry point
├── references/             # Technical documentation
├── snapshots/              # Daily full snapshots (auto-created)
├── diffs/                  # Daily changes (auto-created)
└── reports/                # Local report backups (auto-created)
```

## License

MIT
