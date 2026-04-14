---
name: agent-job-monitor
version: 2.0.5
description: "AI company Agent/LLM job monitoring system. Automatically collects Agent-related job postings from ByteDance, Tencent, Alibaba, Aliyun, Zhipu AI, Kimi, MiniMax, generates daily reports and sends IM notifications. Triggers: Agent job monitor, AI company hiring trends, ByteDance/Tencent/Alibaba Agent hiring, Zhipu/Kimi/MiniMax jobs, today's new jobs, AI talent competition landscape, daily job report, agent-job-monitor, install job monitor, configure job monitor. Not applicable: third-party job boards (BOSS/Liepin); AI news/trends/research reports; scholar background checks (use ai-talent-radar)."
tags: [job-monitor, AI, agent, recruitment]
---

# agent-job-monitor v2.0.5

AI company Agent/LLM job monitoring system — daily automated collection → analysis → report generation → IM notification.

**V2.0.0: MiniMax Feishu ATS fully integrated (7/7 complete collection)**

---

## First Use

Run the dependency check script before first use:
```bash
bash scripts/setup.sh
```
> The agent will auto-run this script on first trigger — usually no manual action needed.
> Note: Playwright Chromium download is ~150MB.

---

## Installation & Configuration

### Prerequisites

#### Dependency 1: `agent-browser` Skill (required)
Affects: Alibaba, Aliyun, Zhipu AI, Kimi collection (4/7 companies)

```bash
# Install agent-browser to OpenClaw skills directory
git clone https://github.com/rrrrrredy/agent-browser ~/.openclaw/skills/agent-browser
```

> `agent-browser` is an OpenClaw Skill for browser automation. See its README for setup.

#### Dependency 2: Python packages (required)
Affects: Tencent/ByteDance (requests), MiniMax (playwright)

```bash
pip install requests playwright
python3 -m playwright install chromium
```

> ⚠️ **Playwright Chromium download note**: `playwright install chromium` downloads ~150MB binary from `playwright.azureedge.net`. If download fails behind a corporate network:
> ```bash
> # Option 1: Use a mirror
> PLAYWRIGHT_DOWNLOAD_HOST=https://your-mirror python3 -m playwright install chromium
> # Option 2: Contact IT to allow azureedge.net access
> ```
> Only MiniMax collection depends on this; the other 6/7 companies are unaffected.

#### Dependency 3: HTTP Proxy (MiniMax only, configure if needed)
Affects: MiniMax Feishu ATS collection

**Step 1: Check if your IP is blocked by Feishu ATS**

```bash
curl -I --max-time 10 https://vrfi1sk8a0.jobs.feishu.cn/379481/
```

- Returns `HTTP/2 200` → Your IP is not blocked, set `PROXY = {}` for direct connection
- Returns `403` / `404` / timeout → Your IP is blocked, configure an HTTP proxy

**Step 2 (if blocked): Configure proxy**

Edit `scripts/daily_collect.py` line 24 `PROXY`:

```python
# daily_collect.py line 24
PROXY = {"http": "http://YOUR_PROXY:PORT", "https": "http://YOUR_PROXY:PORT"}
```

> Don't know a proxy address? Ask your IT team for an HTTP forward proxy.
> If no proxy is available, MiniMax collection will be skipped (WARNING); the other 6/7 companies are unaffected.

#### Dependency 4: Document Push (optional)
Affects: Report publishing to your docs platform

The `push_citadel.py` script supports pushing reports to a docs platform via a CLI tool.
If you don't have a docs platform integration, reports are saved locally to `reports/`.

---

### Data Directory

Script data (snapshots/diffs/reports) is written alongside the skill code:

```
~/.openclaw/skills/agent-job-monitor/
    scripts/
        daily_collect.py
        daily_diff.py
        push_citadel.py
        run_daily.sh
    snapshots/   ← daily full snapshots (auto-created)
    diffs/       ← daily changes (auto-created)
    reports/     ← local report backups (auto-created)
```

> ⚠️ **Current version does not support config.json dynamic configuration** — keywords and company lists are hardcoded in scripts.
> To modify `L1_KEYWORDS` or monitored companies, edit `scripts/daily_collect.py` line 28-29 directly.

### First-Time Setup Steps

1. **Install all dependencies** (see Prerequisites above)

2. **Configure proxy** (if needed): Edit `scripts/daily_collect.py` line 24 `PROXY`

3. **Register cron** (Beijing time 18:00 = UTC 10:00):
   ```
   openclaw cron add --name "Agent Job Daily Report" --schedule "0 10 * * *" \
     --message "Run Agent job daily report: bash ~/.openclaw/skills/agent-job-monitor/scripts/run_daily.sh"
   ```

4. **Manual test run** (verify all dependencies are installed):
   ```bash
   bash ~/.openclaw/skills/agent-job-monitor/scripts/run_daily.sh
   ```

**Ask user during setup (2 required confirmations)**:

1. **Parent document ID** (`parent_doc_id`): Reports will be nested under this document. Override with `--parent-id` parameter in `push_citadel.py`
2. **IM notification user ID**: After cron triggers, the agent session sends IM messages — confirm your user ID is correct

---

## Daily Execution Flow

Cron triggers `run_daily.sh`, chaining three scripts:

```
Step 1: daily_collect.py    → Collect company jobs → snapshots/{date}.json
Step 2: daily_diff.py       → Compare with yesterday → diffs/{date}-diff.json
Step 3: push_citadel.py     → Generate detailed report → push to docs → send IM notification
```

**Report dimensions (V2 full version, 12 sections)**:

**Part 1 Overall Analysis**:
1. Today's overview (job counts per company, 7/7 collection status)
2. Company competitive landscape (scale tiers, strategic insights)
3. Agent sub-direction distribution (Infra/Application/Algorithm/Product/Evaluation/Data/Researcher)
4. Recruitment type analysis (experienced/campus/intern ratios and strategy insights)
5. City strategic distribution (with business source analysis)
6. Collection status (transparent data blind spots, fallback strategies)

**Part 2 Today's New Jobs Analysis**:
7. Today's new total vs. yesterday comparison
8. Today's new jobs by company
9. Today's new direction distribution (strategic signal analysis)
10. Today's new recruitment types
11. Today's new job title high-frequency keywords
12. Today's new insights (industry signals, multi-company resonance, anomaly monitoring)

---

## Collection Methods per Company (V2.0.0 Full)

| Company | Collection Method | Proxy | Status |
|---------|------------------|-------|--------|
| Tencent | `careers.tencent.com` API direct GET | None | ✅ Stable |
| ByteDance | `jobs.bytedance.com` API direct POST | None (proxy returns 405) | ✅ Stable |
| Alibaba | `talent-holding.alibaba.com` Playwright DOM | agent-browser | ✅ Stable |
| Aliyun | `careers.aliyun.com` Playwright DOM | agent-browser | ✅ Stable |
| Zhipu AI | `app.mokahr.com/zphz` DOM parsing | agent-browser | ✅ Stable |
| Kimi | `app.mokahr.com/moonshot` DOM parsing | agent-browser | ✅ Stable |
| MiniMax | `vrfi1sk8a0.jobs.feishu.cn` Feishu ATS + proxy | Configurable (see Dependency 3) | ✅ **V2.0.0 New** |

### MiniMax Feishu ATS Technical Details (V2.0.0)

Feishu ATS Portal is a pure CSR application — the `_signature` parameter is dynamically generated by browser JS and cannot be replicated via curl.

**Approach**: `playwright` Chromium + HTTP proxy (supports CONNECT tunnel), intercepts
`/api/v1/search/job/posts` responses to get structured JSON.

```python
def collect_feishu_ats(
    tenant_id: str,       # e.g. "vrfi1sk8a0"
    website_path: str,    # e.g. "379481"
    company: str,
    keywords: list,
    proxy: str = "",      # HTTP proxy address, empty for direct connection
) -> dict:
    """
    Generic Feishu ATS collector.
    Reusable for: Baichuan AI, StepFun, 01.AI, DeepSeek, etc.
    """
```

**Verified API**:
```
POST https://<tenant>.jobs.feishu.cn/api/v1/search/job/posts
    ?keyword=<keyword>&limit=10&offset=0&portal_entrance=1&_signature=<JS-generated>
Response: { "data": { "job_post_list": [...], "count": <total> } }
```

---

## Query Interface (Natural Language Triggers)

| Query Intent | Action |
|-------------|--------|
| "How many new Agent jobs today" | Read today's diff, report new_jobs count and company distribution |
| "How many Agent jobs does ByteDance have" | Read today's snapshot, filter ByteDance entries |
| "Trend over last week" | Read 7-day snapshots, calculate company trends |
| "View today's report" | Output today's report.md summary + docs link |
| "Run manual collection" | Execute `bash scripts/run_daily.sh` |
| "What MiniMax jobs are there today" | Read snapshot MiniMax entries, output job list |

---

## Hard Stop

- Single company fails **3 times** → Mark WARNING, skip, don't interrupt overall flow
- Docs push fails → Report saved locally to `reports/{date}-report.md`, IM notification includes local summary
- **Proxy failure** → MiniMax marked WARNING, report notes "Feishu collection proxy unavailable"
- All companies fail → Stop, send IM alert: "Today's collection all failed, check network/IP"

---

## Gotchas

See `gotchas.md` — key points:

| Gotcha | Correct Approach |
|--------|-----------------|
| ByteDance/Tencent API returns 405 through proxy | Direct connection (`proxies={}`) |
| Alibaba IP blocked by talent.alibaba.com 403 | Use agent-browser Playwright DOM to bypass |
| Feishu ATS blocked by exit IP | Zhipu/Kimi use mokahr.com; MiniMax uses playwright + proxy |
| MiniMax Feishu `_signature` can't be curl'd | Must use browser JS execution then intercept requests |
| `dedup_jobs()` requires id field | MiniMax Feishu jobs have no `id`, use `url` as unique key |
| `daily_diff.py` location vs city field | MiniMax uses `city`, others use `location`, diff script handles both |
| cron `--tz` doesn't affect `--at` | Beijing 18:00 = UTC 10:00, write `0 10 * * *` |

---

## Data Directory Structure

```
~/.openclaw/skills/agent-job-monitor/
├── scripts/
│   ├── daily_collect.py
│   ├── daily_diff.py
│   ├── push_citadel.py
│   └── run_daily.sh
├── snapshots/
│   └── YYYY-MM-DD.json        # Daily full snapshot (L1 jobs)
├── diffs/
│   └── YYYY-MM-DD-diff.json   # Daily changes (new/removed)
└── reports/
    └── YYYY-MM-DD-report.md   # Daily report Markdown (local backup)
```

---

## Reference Docs

- `references/company-endpoints.md`: Company API paths + collection strategies + status (V2 updated)
- `references/schema.md`: Snapshot JSON field documentation
- `gotchas.md`: Hard-won troubleshooting dictionary (continuously updated)

---

## Changelog

### v2.0.5 (2026-04-10)
- **Fix**: Dependency 2 `playwright install chromium` added corporate network download failure docs
- **Fix**: Dependency 4 proxy config added self-check step (`curl -I` test)
- **Security**: `references/company-endpoints.md` removed private proxy IPs, replaced with generic instructions
- **Docs**: `references/schema.md` added `id` field MiniMax url fallback note

### v2.0.0 (2026-04-10)
- **MiniMax integration**: playwright Chromium + HTTP proxy (CONNECT tunnel), intercept Feishu ATS API, 7/7 full collection
- **`collect_feishu_ats()` generic function**: Reusable for all Feishu ATS companies
- **Report upgraded to 12 sections**: Added Part 2 new jobs deep analysis (sections 7-12)
- **Bug fixes**: `dedup_jobs()` handles missing `id` field; `daily_diff.py` handles `city` vs `location`
- First full 7/7 collection: 305 L1 jobs

### v1.0.0 (2026-04-10)
- ByteDance/Tencent HTTP API + Alibaba/Zhipu/Kimi agent-browser DOM, 6/7 companies live
- Detailed report template (6 dimensions + insights + BU analysis)
- Docs push + IM notification integration
- Cron registration (daily 18:00 Beijing time)
- MiniMax: Feishu CSR + IP blocking, V1 blocked
