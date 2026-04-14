#!/usr/bin/env python3
"""
Agent 岗位每日 Diff 脚本
对比今日 vs 昨日快照，输出新增/消失岗位
用法：python3 daily_diff.py [--date YYYY-MM-DD]
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone, timedelta, date as date_cls

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE_DIR = os.path.dirname(SCRIPT_DIR)
SNAPSHOTS_DIR = os.path.join(WORKSPACE_DIR, "snapshots")
DIFFS_DIR = os.path.join(WORKSPACE_DIR, "diffs")

CST = timezone(timedelta(hours=8))


def load_snapshot(date_str: str) -> dict | None:
    """加载指定日期的快照，不存在返回 None"""
    path = os.path.join(SNAPSHOTS_DIR, f"{date_str}.json")
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def prev_date(date_str: str) -> str:
    """返回前一天日期字符串"""
    d = date_cls.fromisoformat(date_str)
    return (d - timedelta(days=1)).isoformat()


def main():
    parser = argparse.ArgumentParser(description="Agent 岗位每日 Diff 脚本")
    parser.add_argument("--date", default=None, help="今日日期 YYYY-MM-DD，默认今天")
    args = parser.parse_args()

    today = datetime.now(CST).strftime("%Y-%m-%d") if args.date is None else args.date
    yesterday = prev_date(today)

    print(f"\n{'='*50}")
    print(f"Agent 岗位 Diff {yesterday} → {today}")
    print(f"{'='*50}")

    # 加载今日快照
    today_snap = load_snapshot(today)
    if today_snap is None:
        print(f"[ERROR] 今日快照不存在：{SNAPSHOTS_DIR}/{today}.json")
        print("请先运行 daily_collect.py")
        return 1

    # 加载昨日快照
    yesterday_snap = load_snapshot(yesterday)
    if yesterday_snap is None:
        print(f"[INFO] 昨日快照不存在（{yesterday}），首次采集，无 diff。")
        # 写一个"首次采集"的 diff 文件
        os.makedirs(DIFFS_DIR, exist_ok=True)
        diff_path = os.path.join(DIFFS_DIR, f"{today}-diff.json")
        diff_result = {
            "date": today,
            "yesterday": yesterday,
            "first_run": True,
            "new_jobs": [],
            "removed_jobs": [],
            "unchanged_count": today_snap.get("total", 0),
            "summary": f"首次采集，共 {today_snap.get('total', 0)} 个 Agent 岗位，无 diff",
        }
        with open(diff_path, "w", encoding="utf-8") as f:
            json.dump(diff_result, f, ensure_ascii=False, indent=2)
        print(f"首次采集，diff 已写入：{diff_path}")
        return 0

    def job_key(j: dict) -> str:
        """兼容无 id 字段的岗位（如飞书 ATS 的 MiniMax 岗位），用 url 或 title+company 作 key"""
        return j.get("id") or j.get("url") or f"{j.get('title','')}_{j.get('company','')}"

    # 构建 id set
    today_jobs_map = {job_key(j): j for j in today_snap.get("jobs", [])}
    yesterday_jobs_map = {job_key(j): j for j in yesterday_snap.get("jobs", [])}

    today_ids = set(today_jobs_map.keys())
    yesterday_ids = set(yesterday_jobs_map.keys())

    new_ids = today_ids - yesterday_ids
    removed_ids = yesterday_ids - today_ids
    unchanged_count = len(today_ids & yesterday_ids)

    new_jobs = [today_jobs_map[i] for i in sorted(new_ids)]
    removed_jobs = [yesterday_jobs_map[i] for i in sorted(removed_ids)]

    summary = f"新增 {len(new_jobs)} 个 Agent 岗位，消失 {len(removed_jobs)} 个"

    print(f"今日总计：{len(today_ids)} 个岗位")
    print(f"昨日总计：{len(yesterday_ids)} 个岗位")
    print(f"新增：{len(new_jobs)} 个")
    print(f"消失：{len(removed_jobs)} 个")
    print(f"不变：{unchanged_count} 个")

    # 打印新增岗位摘要
    if new_jobs:
        print("\n🆕 新增岗位：")
        for j in new_jobs[:20]:  # 最多显示20条
            co = j.get('company', j.get('source_keyword', ''))
            loc = j.get('location', j.get('city', ''))
            print(f"  [{co}] {j['title']} - {loc}")
        if len(new_jobs) > 20:
            print(f"  ... 共 {len(new_jobs)} 条（截断显示）")

    if removed_jobs:
        print("\n❌ 消失岗位：")
        for j in removed_jobs[:10]:
            co = j.get('company', j.get('source_keyword', ''))
            loc = j.get('location', j.get('city', ''))
            print(f"  [{co}] {j['title']} - {loc}")
        if len(removed_jobs) > 10:
            print(f"  ... 共 {len(removed_jobs)} 条（截断显示）")

    # 写 diff 文件
    os.makedirs(DIFFS_DIR, exist_ok=True)
    diff_path = os.path.join(DIFFS_DIR, f"{today}-diff.json")
    diff_result = {
        "date": today,
        "yesterday": yesterday,
        "first_run": False,
        "new_jobs": new_jobs,
        "removed_jobs": removed_jobs,
        "unchanged_count": unchanged_count,
        "today_total": len(today_ids),
        "yesterday_total": len(yesterday_ids),
        "summary": summary,
    }
    with open(diff_path, "w", encoding="utf-8") as f:
        json.dump(diff_result, f, ensure_ascii=False, indent=2)

    print(f"\nDiff 已写入：{diff_path}")
    print(f"{'='*50}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
