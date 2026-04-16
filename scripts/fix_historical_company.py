#!/usr/bin/env python3
"""
一次性修复脚本：修复 04-10 ~ 04-15 历史快照中 company="" 的 MiniMax 岗位
Bug 6: 飞书 ATS 采集时 company 字段漏设，导致 49 条 MiniMax 岗位的 company 为空
"""

import json
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE_DIR = os.path.dirname(SCRIPT_DIR)
SNAPSHOTS_DIR = os.path.join(WORKSPACE_DIR, "snapshots")

# 需要修复的日期范围
TARGET_DATES = [
    "2026-04-10",
    "2026-04-11",
    "2026-04-12_partial",
    "2026-04-13",
    "2026-04-14",
    "2026-04-15",
]

def fix_snapshot(date_str: str) -> int:
    """修复单个快照文件，返回修复数量"""
    path = os.path.join(SNAPSHOTS_DIR, f"{date_str}.json")
    if not os.path.exists(path):
        print(f"  [{date_str}] 文件不存在，跳过")
        return 0

    with open(path, "r", encoding="utf-8") as f:
        snap = json.load(f)

    jobs = snap.get("jobs", [])
    fixed_count = 0

    for j in jobs:
        company = j.get("company", "")
        url = j.get("url", "")
        if company == "" and "jobs.feishu.cn" in url:
            j["company"] = "MiniMax"
            fixed_count += 1

    if fixed_count > 0:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(snap, f, ensure_ascii=False, indent=2)
        print(f"  [{date_str}] 修复 {fixed_count} 条（company=\"\" → \"MiniMax\"）")
    else:
        print(f"  [{date_str}] 无需修复（0 条匹配）")

    return fixed_count


def main():
    print("=" * 50)
    print("修复历史快照 company 字段（Bug 6）")
    print("=" * 50)

    total_fixed = 0
    for date_str in TARGET_DATES:
        total_fixed += fix_snapshot(date_str)

    print(f"\n总计修复 {total_fixed} 条记录")
    print("=" * 50)
    return 0


if __name__ == "__main__":
    sys.exit(main())
