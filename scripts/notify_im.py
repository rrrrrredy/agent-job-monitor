#!/usr/bin/env python3
"""
Agent Job IM Notification Script
Reads today's diff + snapshot, generates concise daily report message, sends via openclaw message
Usage: python3 notify_im.py [--date YYYY-MM-DD]
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


def send_im_message(message: str, user_id: str = "") -> bool:
    """Send notification via openclaw message tool"""
    if not user_id:
        print("[IM] No user ID configured, skipping notification")
        return False
    try:
        result = subprocess.run(
            [
                "openclaw", "message", "send",
                "--target", user_id,
                "--message", message,
            ],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            print(f"[IM] Notification sent successfully")
            return True
        else:
            print(f"[IM] Notification failed (returncode={result.returncode}): {result.stderr.strip()}")
            return False
    except subprocess.TimeoutExpired:
        print("[IM] Notification timeout (30s)")
        return False
    except Exception as e:
        print(f"[IM] Notification error: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Agent Job IM Notification Script")
    parser.add_argument("--date", default=None, help="Date YYYY-MM-DD, defaults to today")
    parser.add_argument("--user-id", default="", help="IM user ID for notifications")
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

    success = send_im_message(message, args.user_id)
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
