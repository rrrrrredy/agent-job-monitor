#!/usr/bin/env python3
"""
Agent Job IM Notification Script
Reads today's diff + snapshot, generates concise daily report message.
Outputs to stdout by default. Optionally sends via webhook or saves to file.
Usage: python3 notify_im.py [--date YYYY-MM-DD] [--webhook URL] [--output FILE]
"""

import argparse
import json
import os
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone, timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE_DIR = os.path.dirname(SCRIPT_DIR)
DIFFS_DIR = os.path.join(WORKSPACE_DIR, "diffs")
SNAPSHOTS_DIR = os.path.join(WORKSPACE_DIR, "snapshots")

CST = timezone(timedelta(hours=8))


def load_diff(date_str: str) -> dict | None:
    path = os.path.join(DIFFS_DIR, f"{date_str}-diff.json")
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_snapshot(date_str: str) -> dict | None:
    path = os.path.join(SNAPSHOTS_DIR, f"{date_str}.json")
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_im_message(date_str: str, diff: dict, snapshot: dict | None) -> str:
    """Generate a concise daily report suitable for IM messaging"""
    new_jobs = diff.get("new_jobs", [])
    removed_jobs = diff.get("removed_jobs", [])
    first_run = diff.get("first_run", False)
    all_jobs = snapshot.get("jobs", []) if snapshot else []
    total = snapshot.get("total", diff.get("today_total", 0)) if snapshot else diff.get("today_total", 0)

    # Per-company stats
    company_stats = Counter(j.get("company", "Unknown") for j in all_jobs)

    lines = [f"📊 **AI Agent Job Daily Report · {date_str}**", ""]

    # Overview
    if first_run:
        lines.append(f"First collection: {total} L1 jobs baseline established")
    else:
        lines.append(f"L1 inventory: {total}　New: +{len(new_jobs)}　Removed: -{len(removed_jobs)}")

    lines.append("")

    # Per-company distribution
    COMPANIES = ["ByteDance", "Tencent", "Alibaba", "Aliyun", "Zhipu AI", "Kimi", "MiniMax"]
    COMPANY_MAP = {"字节跳动": "ByteDance", "腾讯": "Tencent", "阿里巴巴": "Alibaba",
                   "阿里云": "Aliyun", "智谱AI": "Zhipu", "Kimi（月之暗面）": "Kimi", "MiniMax": "MiniMax"}
    company_line_parts = []
    for c_cn, c_en in COMPANY_MAP.items():
        cnt = company_stats.get(c_cn, 0)
        company_line_parts.append(f"{c_en} {cnt}")
    lines.append(" | ".join(company_line_parts))
    lines.append("")

    # New jobs list (max 10)
    if new_jobs:
        lines.append(f"🆕 New {len(new_jobs)} jobs:")
        for j in new_jobs[:10]:
            company = j.get("company", "")
            title = j.get("title", "")
            location = j.get("location", "") or ""
            short_co = COMPANY_MAP.get(company, company)
            loc_str = f" · {location}" if location else ""
            lines.append(f"• {short_co} | {title}{loc_str}")
        if len(new_jobs) > 10:
            lines.append(f"• ...({len(new_jobs)} total, showing first 10)")
        lines.append("")

    # Removed jobs (count only)
    if removed_jobs and not first_run:
        removed_by_co = Counter(j.get("company", "") for j in removed_jobs)
        removed_parts = [f"{COMPANY_MAP.get(c, c)} -{n}" for c, n in removed_by_co.most_common()]
        lines.append(f"❌ Removed {len(removed_jobs)} jobs: {' | '.join(removed_parts)}")
        lines.append("")

    # Zero-change notice
    if not first_run and not new_jobs and not removed_jobs:
        lines.append("No changes today, maintaining yesterday's state.")
        lines.append("")

    lines.append(f"_Collection time: {datetime.now(CST).strftime('%H:%M')} CST_")

    return "\n".join(lines)


def send_via_webhook(message: str, webhook_url: str) -> bool:
    """Send notification via webhook (Slack/Discord/Feishu/Lark/generic webhook)."""
    import requests as _req
    try:
        # Attempt Slack/Discord-style payload first
        payload = {"text": message, "content": message}
        r = _req.post(webhook_url, json=payload, timeout=15)
        if r.status_code < 300:
            print(f"[IM] Notification sent via webhook (HTTP {r.status_code})")
            return True
        else:
            print(f"[IM] Webhook returned HTTP {r.status_code}: {r.text[:200]}")
            return False
    except Exception as e:
        print(f"[IM] Webhook error: {e}")
        return False


def save_to_file(message: str, output_path: str) -> bool:
    """Save notification message to a local file."""
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(message)
        print(f"[IM] Message saved to {output_path}")
        return True
    except Exception as e:
        print(f"[IM] File save error: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Agent Job IM Notification Script")
    parser.add_argument("--date", default=None, help="Date YYYY-MM-DD, defaults to today")
    parser.add_argument("--webhook", default="", help="Webhook URL for Slack/Discord/Feishu/Lark notifications")
    parser.add_argument("--output", default="", help="Save message to file instead of sending")
    args = parser.parse_args()

    today = datetime.now(CST).strftime("%Y-%m-%d") if args.date is None else args.date

    print(f"\n{'='*50}")
    print(f"Agent Job IM Notification {today}")
    print(f"{'='*50}")

    diff = load_diff(today)
    if diff is None:
        print(f"[ERROR] Today's diff not found, run daily_diff.py first")
        return 1

    snapshot = load_snapshot(today)
    new_jobs = diff.get("new_jobs", [])
    removed_jobs = diff.get("removed_jobs", [])
    first_run = diff.get("first_run", False)

    # Silent on zero changes (except first collection)
    if not first_run and not new_jobs and not removed_jobs:
        print("[IM] No changes today, staying silent")
        return 0

    message = build_im_message(today, diff, snapshot)
    print(f"[IM] Message preview:\n{message}\n")

    # Delivery: webhook > file > stdout
    if args.webhook:
        success = send_via_webhook(message, args.webhook)
        return 0 if success else 1
    elif args.output:
        success = save_to_file(message, args.output)
        return 0 if success else 1
    else:
        # Default: print to stdout (can be piped to any notification tool)
        print("---")
        print(message)
        print("---")
        print("[IM] No --webhook or --output specified. Message printed to stdout.")
        print("     To send via webhook: --webhook https://hooks.slack.com/services/...")
        return 0


if __name__ == "__main__":
    sys.exit(main())
