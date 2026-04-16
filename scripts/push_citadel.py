#!/usr/bin/env python3
"""
Agent 岗位docs push script（V2 — 增强 insights 版）
读取今日 diff + snapshot，生成精细分析报告，push report to docs platform
用法：python3 push_citadel.py [--date YYYY-MM-DD] [--parent-id <parentId>]
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone, timedelta

# ─────────────────────────────────────────
# 依赖自检（启动时提示，不强制退出）
# ─────────────────────────────────────────
def _check_dependencies():
    # oa-skills（docs push tool）
    if shutil.which("oa-skills") is None:
        print("=" * 60)
        print("⚠️  未找到 'oa-skills' 命令（docs push will be skipped）")
        print("   Install command：npm i -g @it/oa-skills")
        print("   docs push unavailable, reports saved to local reports/ 目录")
        print("=" * 60)

_check_dependencies()

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE_DIR = os.path.dirname(SCRIPT_DIR)
DIFFS_DIR = os.path.join(WORKSPACE_DIR, "diffs")
REPORTS_DIR = os.path.join(WORKSPACE_DIR, "reports")
SNAPSHOTS_DIR = os.path.join(WORKSPACE_DIR, "snapshots")

CST = timezone(timedelta(hours=8))

# 已知 BU / 产品线 → 业务解读映射
BU_INSIGHT = {
    "CSIG": "腾讯云智慧产业",
    "WXG": "微信事业群",
    "IEG": "互动娱乐（游戏）",
    "TEG": "技术工程（基础平台）",
    "CDG": "企业发展（广告/增值）",
    "PCG": "平台与内容",
    "火山引擎": "字节企业服务",
    "扣子": "字节 CozeAI",
    "元宝": "腾讯元宝",
    "CodeBuddy": "字节 CodeBuddy",
    "WorkBuddy": "字节 WorkBuddy",
    "抖音": "字节抖音",
    "TikTok": "字节 TikTok（海外）",
    "商业化": "广告/商业化",
    "Data": "数据平台",
}

# Agent 子方向关键词（按优先级排序，靠前的方向优先匹配，"工程" 作为兜底放最后）
AGENT_DIRECTION_KEYWORDS = {
    "基础设施/Infra": ["Infra", "基础设施", "Runtime", "Framework", "SDK", "调度", "编排", "Orchestration"],
    "算法/模型": ["算法", "模型", "LLM", "大模型", "预训练", "RLHF", "fine-tuning", "微调"],
    "研究员": ["Researcher", "Research Scientist", "研究员", "算法专家"],
    "评测/安全": ["评测", "Evaluation", "安全", "红队"],
    "数据运营": ["数据运营", "数据评测", "数据标注", "标注"],
    "产品经理": ["产品经理", "PM", "产品运营", "产品leader", "产品负责人"],
    "SRE/运维": ["SRE", "运维", "DevOps"],
    "架构": ["架构", "Architect", "系统设计", "解决方案"],
    "后端": ["后端", "Backend", "服务端", "Server"],
    "前端": ["前端", "Frontend", "Web"],
    "全栈": ["全栈", "Full Stack", "Fullstack", "全链路"],
    "测试/QA": ["测试", "QA", "Testing", "质量"],
    "策划/运营": ["策划", "运营"],
    "应用开发": ["应用开发", "开发工程师", "集成", "业务"],
    "工程": ["工程师", "Engineer", "开发", "Developer"],
}


CITY_NAMES = {
    "北京", "上海", "深圳", "杭州", "广州", "成都", "武汉", "南京",
    "西安", "长沙", "合肥", "苏州", "珠海", "天津", "重庆", "厦门",
    "济南", "郑州", "大连", "中国香港", "贝尔维尤", "新加坡", "海外",
    "北京市", "上海市", "深圳市",
}

_CITY_NORMALIZE = {
    "北京市": "北京", "上海市": "上海", "深圳市": "深圳",
    "杭州市": "杭州", "广州市": "广州", "成都市": "成都",
}

def clean_location(loc: str) -> str:
    """清洗 location 字段：截取城市名，过滤 JD 全文污染，归一化'市'后缀"""
    if not loc:
        return ""
    # 如果 location 很长（>30字符），说明是 JD 全文污染
    if len(loc) > 30:
        # 尝试提取开头的城市名
        for city in CITY_NAMES:
            if loc.startswith(city):
                return _CITY_NORMALIZE.get(city, city)
        return ""  # 无法提取有效城市
    # 去掉重复城市名（如 "北京市 北京市 xxx"）
    parts = loc.split()
    if len(parts) >= 2 and parts[0] == parts[1]:
        loc = parts[0]
    # 如果 location 后面跟了 JD 内容，只取第一部分
    for city in CITY_NAMES:
        if loc.startswith(city) and len(loc) > len(city) + 5:
            loc = city
            break
    loc = loc.strip()
    return _CITY_NORMALIZE.get(loc, loc)


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


def load_yesterday_snapshot(date_str: str) -> dict | None:
    from datetime import date
    d = date.fromisoformat(date_str)
    yesterday = (d - timedelta(days=1)).isoformat()
    return load_snapshot(yesterday)


def jobs_to_table(jobs: list, max_rows: int = 50) -> str:
    """将岗位列表渲染为 Markdown 表格"""
    if not jobs:
        return "_（无）_\n"
    lines = ["| 公司 | 职位 | 城市 | 部门/BU |", "|------|------|------|---------|"]
    for j in jobs[:max_rows]:
        company = j.get("company", "")
        title = j.get("title", "")
        location = clean_location(j.get("location", "")) or "—"
        dept = j.get("department", "") or "—"
        lines.append(f"| {company} | {title} | {location} | {dept} |")
    if len(jobs) > max_rows:
        lines.append(f"| ... | _（共 {len(jobs)} 条，截断显示）_ | | |")
    return "\n".join(lines) + "\n"


def analyze_directions(jobs: list) -> dict:
    """分析岗位子方向分布"""
    direction_count = Counter()
    for j in jobs:
        title = j.get("title", "") + " " + j.get("department", "")
        matched = False
        for direction, keywords in AGENT_DIRECTION_KEYWORDS.items():
            for kw in keywords:
                if kw.lower() in title.lower():
                    direction_count[direction] += 1
                    matched = True
                    break
            if matched:
                break
        if not matched:
            direction_count["其他"] += 1
    return dict(direction_count.most_common())


def analyze_bu_distribution(jobs: list) -> dict:
    """分析业务线/BU 分布"""
    bu_count = Counter()
    for j in jobs:
        title = j.get("title", "") + " " + (j.get("department", "") or "")
        matched = False
        for bu_kw in BU_INSIGHT.keys():
            if bu_kw in title:
                bu_count[bu_kw] += 1
                matched = True
                break
        if not matched:
            dept = j.get("department", "") or "未知部门"
            bu_count[dept] += 1
    return dict(bu_count.most_common(10))


def generate_insights(jobs: list, new_jobs: list, removed_jobs: list,
                      yesterday_jobs: list | None, date_str: str,
                      companies_meta: dict | None = None) -> list:
    """生成多维度 insights（纯数据驱动，无硬编码套话）"""
    insights = []

    if not jobs:
        return ["⚠️ 当日无数据，所有渠道均采集失败，请检查采集日志"]

    total = len(jobs)

    # Insight 1: 整体规模解读（纯数据）
    if len(new_jobs) > 20:
        insights.append(
            f"📈 **今日新增 {len(new_jobs)} 个岗位，属于高活跃日**，"
            f"同时消失 {len(removed_jobs)} 个，净变动 {len(new_jobs) - len(removed_jobs):+d}。"
        )
    elif len(new_jobs) > 5:
        insights.append(
            f"📊 今日新增 {len(new_jobs)} 个岗位，消失 {len(removed_jobs)} 个，"
            f"净变动 {len(new_jobs) - len(removed_jobs):+d}。"
        )
    elif len(new_jobs) == 0 and len(removed_jobs) == 0:
        insights.append(
            f"🔁 今日岗位零变动（新增/消失均为 0），可能原因：周末/节假日效应或 HC 审批阻塞。"
        )

    # Insight 2: 公司格局（纯数据描述）
    company_counts = Counter(j.get("company", "") for j in jobs)
    if company_counts:
        top3 = company_counts.most_common(3)
        desc_parts = [f"{c}({n}条)" for c, n in top3]
        insights.append(
            f"🏢 **公司格局**：{' > '.join(desc_parts)}，"
            f"共 {len(company_counts)} 家公司在招。"
        )

    # Insight 3: 城市分布（纯数据，清洗+拆分多城市）
    city_counts = Counter()
    for j in jobs:
        loc = clean_location(j.get("location", "")) or "未知"
        for city in loc.split(" / "):
            city = city.strip()
            if city:
                city_counts[city] += 1
    top_cities = [(c, n) for c, n in city_counts.most_common(5) if c not in ("未知", "")]
    if top_cities:
        city_str = "、".join(f"{c}({n})" for c, n in top_cities)
        insights.append(f"📍 **城市分布 Top5**：{city_str}。")

    # Insight 4: Agent 子方向分析（纯数据）
    directions = analyze_directions(jobs)
    if directions:
        top_dir = list(directions.items())[:3]
        dir_str = "、".join(f"{k}({v}条)" for k, v in top_dir)
        other_pct = directions.get("其他", 0) / sum(directions.values()) * 100
        insights.append(
            f"🔬 **Agent 子方向 Top3**：{dir_str}。未归类占比 {other_pct:.1f}%。"
        )

    # Insight 5: 新增岗位特征（纯数据 + Bug5 数据修复标注）
    if new_jobs:
        new_companies = Counter(j.get("company", "") for j in new_jobs)
        top_new = new_companies.most_common(1)[0]

        # Bug 5 修复：昨日为 0 但今日大量"新增"时标注数据修复
        yesterday_company_counts = Counter(j.get("company", "") for j in yesterday_jobs) if yesterday_jobs else Counter()
        recovery_notes = []
        for co, cnt in new_companies.most_common():
            if cnt >= 5 and yesterday_company_counts.get(co, 0) == 0:
                recovery_notes.append(co)

        # 产品线热度
        product_lines = []
        for j in new_jobs:
            for bu in ["火山引擎", "扣子", "Coze", "CodeBuddy", "WorkBuddy", "元宝", "抖音", "TikTok", "PICO"]:
                if bu in j.get("title", ""):
                    product_lines.append(bu)
        product_counter = Counter(product_lines).most_common(3)

        insight_text = (
            f"🆕 **新增岗位聚焦**：{top_new[0]} 主导今日新增（{top_new[1]}条）。"
        )
        if product_counter:
            pl_str = "、".join(f"{p}({n}条)" for p, n in product_counter)
            insight_text += f"产品线热度：{pl_str}。"

        if recovery_notes:
            insight_text += (
                f" ⚠️ 注意：{', '.join(recovery_notes)} 昨日数据为 0，"
                f"今日大量\"新增\"可能为数据修复导致的回归，非真正新增。"
            )

        insights.append(insight_text)

    # Insight 6: 招聘类型信号（仅有效数据时输出）
    recruit_types = Counter(j.get("recruit_type", "") or "未知" for j in jobs)
    social = recruit_types.get("社招", 0)
    campus = recruit_types.get("校招", 0)
    intern = recruit_types.get("实习", 0)
    if social + campus + intern > 0:
        insights.append(
            f"🎓 **招聘类型**：社招 {social} 条 / 校招 {campus} 条 / 实习 {intern} 条。"
        )

    # Insight 7: 缺失渠道说明
    cmeta = companies_meta or {}
    ALL_EXPECTED = ["腾讯", "字节跳动", "阿里巴巴", "阿里云", "智谱AI", "Kimi", "MiniMax"]
    missing = [c for c in ALL_EXPECTED if c not in cmeta]
    blocked = [c for c in cmeta if cmeta[c].get("blocked") or cmeta[c].get("total", 0) == 0]
    no_data = list(set(missing + blocked))
    if no_data:
        effective = len([c for c in cmeta if cmeta[c].get("total", 0) > 0])
        insights.append(
            f"⚠️ **数据盲区**：{', '.join(no_data)} 本次采集为 0 或异常，"
            f"本日有效采集 {effective} / 7 家。"
        )

    # Insight 8（新增）: 异常检测——环比变动超过 50% 的公司
    if yesterday_jobs:
        yesterday_cc = Counter(j.get("company", "") for j in yesterday_jobs)
        anomalies = []
        all_cos = set(list(company_counts.keys()) + list(yesterday_cc.keys()))
        for co in sorted(all_cos):
            if not co:
                continue
            y_cnt = yesterday_cc.get(co, 0)
            t_cnt = company_counts.get(co, 0)
            if y_cnt == 0 and t_cnt == 0:
                continue
            if y_cnt == 0:
                anomalies.append((co, 0, t_cnt, "新出现"))
            elif t_cnt == 0:
                anomalies.append((co, y_cnt, 0, "全部消失"))
            else:
                change_pct = abs(t_cnt - y_cnt) / y_cnt * 100
                if change_pct >= 50:
                    direction = "增长" if t_cnt > y_cnt else "下降"
                    anomalies.append((co, y_cnt, t_cnt, f"{direction} {change_pct:.0f}%"))
        if anomalies:
            parts = [f"{co}（{y}→{t}，{desc}）" for co, y, t, desc in anomalies]
            insights.append(
                f"🚨 **异常检测**：以下公司环比变动超过 50%：{'、'.join(parts)}。"
                f"建议关注是否为采集波动或真实变化。"
            )

    return insights



def _build_trend_section(date_str: str) -> list:
    """生成近 7 天趋势分析章节（Problem 8 新增）"""
    from datetime import date as _date
    d = _date.fromisoformat(date_str)
    # 收集最近 7 天的快照数据
    trend_data = []  # [(date_str, {company: count}, total)]
    for i in range(6, -1, -1):  # 从 7 天前到今天
        check_date = (d - timedelta(days=i)).isoformat()
        snap = load_snapshot(check_date)
        if snap and snap.get("jobs"):
            company_counts = Counter(j.get("company", "") for j in snap["jobs"])
            # 排除空 company
            company_counts.pop("", None)
            trend_data.append((check_date, dict(company_counts), snap.get("total", len(snap["jobs"]))))

    if len(trend_data) < 2:
        return []  # 不足 2 天数据，不生成趋势

    lines = [
        "---",
        "",
        f"## 趋势分析（近 {len(trend_data)} 天）",
        "",
    ]

    # 收集所有出现过的公司
    all_companies_set = set()
    for _, cc, _ in trend_data:
        all_companies_set.update(cc.keys())
    # 按最新一天的数量排序
    latest_cc = trend_data[-1][1]
    sorted_companies = sorted(all_companies_set, key=lambda c: latest_cc.get(c, 0), reverse=True)

    # 按公司的 7 天岗位数变化表格
    # 表头：日期列
    date_headers = [td[0][-5:] for td in trend_data]  # MM-DD 格式
    header = "| 公司 | " + " | ".join(date_headers) + " | 变化 |"
    separator = "|------" + "|-----" * len(date_headers) + "|------|"
    lines += [header, separator]

    for co in sorted_companies:
        row_values = []
        for _, cc, _ in trend_data:
            row_values.append(cc.get(co, 0))
        cells = [str(v) if v > 0 else "—" for v in row_values]
        # 变化列：对比前一天（昨日环比），非第一天 vs 最后一天
        if len(row_values) >= 2:
            prev_val = row_values[-2]
            last_val = row_values[-1]
            if prev_val == 0 and last_val == 0:
                change = "—"
            elif prev_val == 0:
                change = f"+{last_val}"
            else:
                delta = last_val - prev_val
                change = f"{delta:+d}" if delta != 0 else "持平"
        else:
            change = "—"
        lines.append(f"| {co} | " + " | ".join(cells) + f" | {change} |")

    # 总量变化（昨日环比）
    total_row = []
    for _, _, t in trend_data:
        total_row.append(str(t))
    if len(trend_data) >= 2:
        prev_total = trend_data[-2][2]
        last_total = trend_data[-1][2]
        total_delta = last_total - prev_total
        total_change = f"{total_delta:+d}" if total_delta != 0 else "持平"
    else:
        total_change = "—"
    lines.append(f"| **总计** | " + " | ".join(total_row) + f" | **{total_change}** |")
    lines.append("")

    return lines


def _build_deep_analysis(
    date_str: str,
    all_jobs: list,
    new_jobs: list,
    removed_jobs: list,
    yesterday_jobs: list | None,
    company_stats: Counter,
    yesterday_company_stats: Counter,
    directions: dict,
    new_directions: dict,
    city_stats: Counter,
    companies_meta: dict,
) -> list:
    """
    深度分析报告：竞争格局、战略信号、风险提示、趋势研判。
    不重复前面章节的数据罗列，而是做跨维度交叉分析和研判。
    """
    if not all_jobs:
        return []

    lines = [
        "---",
        "",
        "# Part 3：深度分析报告",
        "",
        "> 以下分析基于多日数据趋势和当日快照的交叉研判，旨在揭示岗位数字背后的战略逻辑。",
        "",
    ]

    total = len(all_jobs)
    yesterday_total = len(yesterday_jobs) if yesterday_jobs else 0
    net_delta = len(new_jobs) - len(removed_jobs)

    # ── 1. 竞争格局分析 ──────────────────────
    lines += [
        "## 1. 竞争格局分析",
        "",
    ]

    # 按公司归类：第一梯队 / 第二梯队 / 观望
    tier1, tier2, watching = [], [], []
    for co, cnt in company_stats.most_common():
        if not co:
            continue
        if cnt >= 40:
            tier1.append((co, cnt))
        elif cnt >= 10:
            tier2.append((co, cnt))
        else:
            watching.append((co, cnt))

    if tier1:
        t1_str = "、".join(f"**{co}**({cnt}条)" for co, cnt in tier1)
        lines.append(f"**第一梯队（≥40条）**：{t1_str}")
        lines.append(f"- 特征：全栈布局，同时招 Infra/应用/算法/产品，说明 Agent 已升级为公司级战略而非实验性项目。")
        lines.append("")

    if tier2:
        t2_str = "、".join(f"{co}({cnt}条)" for co, cnt in tier2)
        lines.append(f"**第二梯队（10-39条）**：{t2_str}")
        lines.append(f"- 特征：聚焦特定方向投入，尚未形成全栈覆盖，但投入力度已超过常规业务线。")
        lines.append("")

    if watching:
        w_str = "、".join(f"{co}({cnt}条)" for co, cnt in watching)
        lines.append(f"**早期探索（<10条）**：{w_str}")
        lines.append(f"- 特征：HC 有限，以研究或单点突破为主，尚未规模化投入。")
        lines.append("")

    # 公司间竞争对标
    if len(company_stats) >= 2:
        sorted_cos = company_stats.most_common()
        leader = sorted_cos[0]
        runner = sorted_cos[1]
        gap = leader[1] - runner[1]
        gap_pct = gap / runner[1] * 100 if runner[1] > 0 else float('inf')

        if gap_pct > 50:
            lines.append(
                f"📊 **格局判断**：{leader[0]} 以 {leader[1]} 条岗位遥遥领先，"
                f"领先第二名 {runner[0]} 达 {gap_pct:.0f}%（{gap} 条差距）。"
                f"表明 {leader[0]} 在 Agent 方向已形成规模化招聘，战略地位明确。"
            )
        elif gap_pct > 20:
            lines.append(
                f"📊 **格局判断**：{leader[0]}({leader[1]}条) 略领先 {runner[0]}({runner[1]}条)，"
                f"差距 {gap_pct:.0f}%。两家均在重度投入，属于直接竞争状态。"
            )
        else:
            lines.append(
                f"📊 **格局判断**：{leader[0]}({leader[1]}条) 与 {runner[0]}({runner[1]}条) 体量接近，"
                f"差距仅 {gap_pct:.0f}%。行业处于「群雄逐鹿」阶段，格局尚未定型。"
            )
        lines.append("")

    # ── 2. 战略信号解读 ──────────────────────
    lines += [
        "## 2. 战略信号解读",
        "",
    ]

    # 信号 A：方向集中度——是否有某个方向在多家公司同时爆发
    direction_by_company = {}
    for j in all_jobs:
        co = j.get("company", "")
        dirs = analyze_directions([j])
        for d in dirs:
            direction_by_company.setdefault(d, set()).add(co)

    consensus_directions = [
        (d, cos) for d, cos in direction_by_company.items()
        if len(cos) >= 4 and d not in ("其他", "工程")
    ]
    if consensus_directions:
        for d, cos in sorted(consensus_directions, key=lambda x: -len(x[1])):
            lines.append(
                f"🔥 **行业共识方向 —— 「{d}」**：{len(cos)} 家公司同时在招"
                f"（{', '.join(sorted(cos))}），属于全行业确定性需求，"
                f"说明这一方向已过了「要不要做」的争论阶段，进入「怎么做得更好」的执行期。"
            )
            lines.append("")

    # 信号 B：差异化方向——只有 1-2 家在招的方向
    niche_directions = [
        (d, cos) for d, cos in direction_by_company.items()
        if 1 <= len(cos) <= 2 and d not in ("其他", "工程")
        and sum(directions.get(d, 0) for _ in [1]) >= 3  # 至少 3 条岗位
    ]
    if niche_directions:
        for d, cos in niche_directions[:3]:
            cos_str = "、".join(sorted(cos))
            cnt = directions.get(d, 0)
            lines.append(
                f"🎯 **差异化信号 —— 「{d}」**：仅 {cos_str} 在招（{cnt}条），"
                f"可能代表这些公司的独特战略押注或先发探索。"
            )
            lines.append("")

    # 信号 C：今日新增特征——新增方向 vs 存量方向的差异
    if new_directions and directions:
        new_dir_set = set(new_directions.keys())
        stock_dir_set = set(directions.keys())
        # 计算新增中占比上升的方向
        shifting = []
        for d in new_dir_set:
            stock_pct = directions.get(d, 0) / sum(directions.values()) * 100 if sum(directions.values()) > 0 else 0
            new_pct = new_directions.get(d, 0) / sum(new_directions.values()) * 100 if sum(new_directions.values()) > 0 else 0
            if new_pct > stock_pct + 10:  # 新增中占比比存量高 10pp 以上
                shifting.append((d, stock_pct, new_pct))

        if shifting:
            lines.append("📈 **新增结构性偏移**：以下方向在今日新增中占比显著高于存量，可能是正在加速的方向：")
            for d, sp, np in shifting:
                lines.append(f"  - 「{d}」：存量占比 {sp:.1f}% → 今日新增占比 {np:.1f}%（偏移 +{np-sp:.1f}pp）")
            lines.append("")

    # ── 3. 城市格局研判 ──────────────────────
    lines += [
        "## 3. 城市格局研判",
        "",
    ]

    # 城市集中度（排除"未知"）
    _known_cities = Counter({c: n for c, n in city_stats.items() if c and c != "未知"})
    total_with_city = sum(_known_cities.values())
    top3_cities = _known_cities.most_common(3)
    if top3_cities and total_with_city > 0:
        top3_sum = sum(cnt for _, cnt in top3_cities)
        concentration = top3_sum / total_with_city * 100
        city_names = "、".join(c for c, _ in top3_cities)

        if concentration > 80:
            lines.append(
                f"🏙️ **高度集中**：{city_names} 三城囊括 {concentration:.0f}% 的岗位，"
                f"Agent 人才市场呈「超级城市」格局，非北上深杭的团队招人难度极大。"
            )
        elif concentration > 60:
            lines.append(
                f"🏙️ **适度集中**：{city_names} 三城占 {concentration:.0f}% 的岗位，"
                f"有一定外溢到二线城市趋势，但核心岗位仍集中在一线。"
            )
        else:
            lines.append(
                f"🏙️ **分散布局**：Top3 城市（{city_names}）仅占 {concentration:.0f}%，"
                f"多中心布局特征明显，Agent 研发正向二线城市扩展。"
            )
        lines.append("")

    # 城市对比：各公司的城市偏好
    co_city_map = {}
    for j in all_jobs:
        co = j.get("company", "")
        city = clean_location(j.get("location", "")) or "未知"
        co_city_map.setdefault(co, Counter())[city] += 1

    city_insights = []
    for co, cities in sorted(co_city_map.items(), key=lambda x: -sum(x[1].values())):
        if not co:
            continue
        top_city = cities.most_common(1)
        if top_city:
            top_c, top_cnt = top_city[0]
            co_total = sum(cities.values())
            if top_cnt / co_total > 0.6 and co_total >= 5 and top_c != "未知":
                city_insights.append(f"  - {co}：{top_cnt / co_total * 100:.0f}% 集中在{top_c}")

    if city_insights:
        lines.append("📍 **公司城市偏好**：")
        lines += city_insights[:5]
        lines.append("")

    # ── 4. 供需信号与风险提示 ──────────────────
    lines += [
        "## 4. 供需信号与风险提示",
        "",
    ]

    # 净变动趋势分析
    if yesterday_jobs:
        if net_delta > 20:
            lines.append(
                f"📈 **扩张信号**：净新增 {net_delta:+d} 条，属于强扩张。"
                f"多家公司同时释放 HC，市场整体需求上行。"
            )
        elif net_delta > 0:
            lines.append(
                f"📊 **温和增长**：净变动 {net_delta:+d} 条，市场稳步扩招中。"
            )
        elif net_delta == 0:
            lines.append(
                f"🔁 **动态平衡**：新增 {len(new_jobs)} 条 = 消失 {len(removed_jobs)} 条，"
                f"HC 有进有出，市场处于结构性调整而非规模扩张。"
            )
        elif net_delta > -10:
            lines.append(
                f"📉 **轻微收缩**：净变动 {net_delta:+d} 条，少量岗位关闭 > 新增。"
                f"可能是个别公司 HC 调整，暂不构成趋势性信号。"
            )
        else:
            lines.append(
                f"🚨 **收缩信号**：净变动 {net_delta:+d} 条，需关注是采集波动还是真实 HC 收缩。"
            )
        lines.append("")

    # 消失岗位分析——如果大量消失集中在某公司
    if removed_jobs:
        removed_by_co = Counter(j.get("company", "") for j in removed_jobs)
        top_removed = removed_by_co.most_common(1)[0] if removed_by_co else ("", 0)
        if top_removed[1] >= 10:
            lines.append(
                f"⚠️ **集中消失**：{top_removed[0]} 消失 {top_removed[1]} 个岗位"
                f"（占全部消失的 {top_removed[1]/len(removed_jobs)*100:.0f}%），"
                f"需区分：①岗位合并/标题调整 ②HC 冻结 ③已完成招聘关闭。"
            )
            lines.append("")

    # 数据质量风险
    data_risks = []
    effective_count = len([c for c in company_stats if company_stats[c] > 0 and c])
    if effective_count < 5:
        data_risks.append(
            f"仅 {effective_count}/7 家公司有效采集，数据覆盖度不足，"
            f"总量变动可能因采集缺失而失真。"
        )

    # 检查是否有公司从 0 跳到大量岗位（数据回补而非真正新增）
    if yesterday_jobs:
        for co, cnt in company_stats.most_common():
            if not co:
                continue
            y_cnt = yesterday_company_stats.get(co, 0)
            if y_cnt == 0 and cnt >= 20:
                data_risks.append(
                    f"{co} 昨日 0 条→今日 {cnt} 条，大概率是数据回补（昨日采集失败），"
                    f"不代表真正新增了 {cnt} 个岗位。"
                )

    if data_risks:
        lines.append("⚠️ **数据质量提示**：")
        for risk in data_risks:
            lines.append(f"  - {risk}")
        lines.append("")

    # ── 5. 趋势研判与关注点 ──────────────────
    lines += [
        "## 5. 趋势研判与关注建议",
        "",
    ]

    # 加载近 7 天快照做趋势判断
    from datetime import date as _date
    d = _date.fromisoformat(date_str)
    weekly_totals = []
    for i in range(6, -1, -1):
        check_date = (d - timedelta(days=i)).isoformat()
        snap = load_snapshot(check_date)
        if snap and snap.get("jobs"):
            weekly_totals.append(len(snap["jobs"]))

    if len(weekly_totals) >= 3:
        avg = sum(weekly_totals) / len(weekly_totals)
        latest = weekly_totals[-1]
        trend_pct = (latest - avg) / avg * 100 if avg > 0 else 0

        if trend_pct > 15:
            lines.append(
                f"📈 **周趋势**：当前 {latest} 条，高于 {len(weekly_totals)} 日均值 {avg:.0f} 条"
                f"（+{trend_pct:.0f}%），市场处于扩张上行期。"
            )
        elif trend_pct < -15:
            lines.append(
                f"📉 **周趋势**：当前 {latest} 条，低于 {len(weekly_totals)} 日均值 {avg:.0f} 条"
                f"（{trend_pct:.0f}%），可能受采集波动或季节性因素影响。"
            )
        else:
            lines.append(
                f"➡️ **周趋势**：当前 {latest} 条，与 {len(weekly_totals)} 日均值 {avg:.0f} 条基本持平"
                f"（{trend_pct:+.0f}%），市场供需稳定。"
            )
        lines.append("")

    # 关注建议
    lines += [
        "### 🔭 关注建议",
        "",
    ]

    suggestions = []

    # 基于方向的建议
    infra_pct = directions.get("基础设施/Infra", 0) / sum(directions.values()) * 100 if directions and sum(directions.values()) > 0 else 0
    if infra_pct > 25:
        suggestions.append(
            f"**Infra 占比 {infra_pct:.0f}%**：各家 Agent Infra（Runtime/SDK/编排框架）竞争白热化，"
            f"这是平台型公司的核心壁垒，建议持续关注这一赛道的公司间差距变化。"
        )

    product_pct = directions.get("产品经理", 0) / sum(directions.values()) * 100 if directions and sum(directions.values()) > 0 else 0
    if product_pct > 5:
        suggestions.append(
            f"**产品岗占比 {product_pct:.0f}%**：Agent PM 需求上升，说明行业已开始从技术驱动转向产品驱动，"
            f"关注点从「能不能做」转向「用户要不要用」。PMF 验证期信号。"
        )

    eval_pct = directions.get("评测/安全", 0) / sum(directions.values()) * 100 if directions and sum(directions.values()) > 0 else 0
    if eval_pct > 3:
        suggestions.append(
            f"**评测/安全岗占比 {eval_pct:.0f}%**：监管预期和产品质量压力驱动，"
            f"预计后续还会持续增长，红队测试和评测工程将成为 Agent 领域的标配岗位。"
        )

    # 基于公司动态的建议
    if new_jobs:
        new_cos = Counter(j.get("company", "") for j in new_jobs)
        top_new_co = new_cos.most_common(1)[0] if new_cos else ("", 0)
        if top_new_co[1] >= 10:
            suggestions.append(
                f"**{top_new_co[0]} 今日密集发布 {top_new_co[1]} 个新岗位**："
                f"通常意味着该公司刚完成 Agent 战略升级或拿到新一轮 HC 审批，"
                f"建议关注其未来 1-2 周是否有产品或技术发布。"
            )

    if not suggestions:
        suggestions.append("今日数据波动在正常范围内，无特殊信号需要重点关注。持续监控即可。")

    for s in suggestions:
        lines.append(f"- {s}")
        lines.append("")

    return lines


def build_report(date_str: str, diff: dict, snapshot: dict | None,
                 yesterday_snapshot: dict | None = None) -> str:
    """生成精细化 Markdown 报告"""
    total = snapshot.get("total", diff.get("today_total", 0)) if snapshot else diff.get("today_total", 0)
    new_jobs = diff.get("new_jobs", [])
    removed_jobs = diff.get("removed_jobs", [])
    first_run = diff.get("first_run", False)
    all_jobs = snapshot.get("jobs", []) if snapshot else []
    yesterday_jobs = yesterday_snapshot.get("jobs", []) if yesterday_snapshot else None

    # 各公司统计
    company_stats = Counter(j.get("company", "未知") for j in all_jobs)

    # 城市统计（过滤空值，清洗脏数据，拆分多城市如 "北京 / 杭州"）
    city_stats = Counter()
    for j in all_jobs:
        loc = clean_location(j.get("location", "")) or "未知"
        for city in loc.split(" / "):
            city = city.strip()
            if city:
                city_stats[city] += 1

    # 子方向分析
    directions = analyze_directions(all_jobs)

    # BU分析
    bu_dist = analyze_bu_distribution(all_jobs)

    # 新增岗位按公司分组
    new_by_company = {}
    for j in new_jobs:
        c = j.get("company", "")
        new_by_company.setdefault(c, []).append(j)

    # Insights
    companies_meta = snapshot.get("companies", {}) if snapshot else {}
    insights = generate_insights(all_jobs, new_jobs, removed_jobs, yesterday_jobs, date_str,
                                  companies_meta=companies_meta)

    lines = [
        f"# Agent 岗位日报 · {date_str}",
        "",
        f"> **监控范围**：字节跳动 · 腾讯 · 阿里巴巴 · 阿里云 · 智谱AI · Kimi（月之暗面）· MiniMax",
        f"> **采集口径**：L1 精准过滤（职位标题含 Agent/agent/智能体）",
        f"> **生成时间**：{datetime.now(CST).strftime('%Y-%m-%d %H:%M:%S')} CST",
        "",
        "---",
        "",
        "## 一、今日总览",
        "",
        f"| 指标 | 数值 |",
        f"|------|------|",
        f"| 今日 L1 监控岗位 | **{total}** 个 |",
        f"| 较昨日新增 | **+{len(new_jobs)}** 个 |",
        f"| 较昨日消失 | **-{len(removed_jobs)}** 个 |",
        f"| 有效采集公司 | {len([c for c in company_stats if company_stats[c] > 0])} / 7 家 |",
        "",
    ]

    # 各公司分布表
    lines += [
        "### 各公司岗位分布",
        "",
        "| 公司 | 今日 L1 岗位数 | 环比昨日 |",
        "|------|--------------|---------|",
    ]

    # 计算昨日各公司数
    yesterday_company_stats = Counter()
    if yesterday_jobs:
        yesterday_company_stats = Counter(j.get("company", "") for j in yesterday_jobs)

        # 显示名 → 快照中实际 company 字段值的映射
    company_display_map = {
        "字节跳动": "字节跳动",
        "腾讯": "腾讯",
        "阿里巴巴": "阿里巴巴",
        "阿里云": "阿里云",
        "智谱AI": "智谱AI",
        "MiniMax": "MiniMax",
        "Kimi（月之暗面）": "Kimi",  # 快照中 company 为 "Kimi"
    }
    all_companies = list(company_display_map.keys())
    for company in all_companies:
        snapshot_key = company_display_map[company]
        today_cnt = company_stats.get(snapshot_key, 0)
        yesterday_cnt = yesterday_company_stats.get(snapshot_key, 0)
        if today_cnt == 0:
            status = "⚠️ 未采集"
        elif yesterday_cnt == 0:
            status = "首次采集"
        else:
            delta = today_cnt - yesterday_cnt
            status = f"+{delta}" if delta > 0 else (f"{delta}" if delta < 0 else "持平")
        lines.append(f"| {company} | {today_cnt} | {status} |")
    lines.append("")

    # Insights 区
    lines += [
        "---",
        "",
        "## 二、深度 Insights",
        "",
    ]
    for i, insight in enumerate(insights, 1):
        lines.append(f"{i}. {insight}")
        lines.append("")

    # 趋势分析（近7天）—— Problem 8 新增
    trend_lines = _build_trend_section(date_str)
    if trend_lines:
        lines += trend_lines

    # Agent 子方向分析
    if directions:
        lines += [
            "---",
            "",
            "## 三、Agent 子方向分析",
            "",
            "| 方向 | 岗位数 | 占比 | 解读 |",
            "|------|--------|------|------|",
        ]
        direction_total = sum(directions.values())
        direction_interpretations = {
            "基础设施/Infra": "底层框架搭建，各家竞争最激烈的技术护城河",
            "应用开发": "产品落地加速，Agent 已进入工程化阶段",
            "算法/模型": "能力提升，专注模型侧 Agent 推理/规划能力",
            "产品经理": "产品化信号，Agent 从技术 Demo 走向 PMF 阶段",
            "评测/安全": "质量与安全并重，监管预期下的防御性布局",
            "数据运营": "高质量训练数据是差距所在，数据飞轮构建",
            "研究员": "前沿探索，下一代 Agent 能力预研",
            "SRE/运维": "稳定性工程，Agent 大规模部署的基础保障",
            "架构": "系统顶层设计，Agent 平台化所需的架构能力",
            "后端": "服务端工程能力，支撑 Agent 业务逻辑和接口",
            "前端": "交互层开发，Agent 产品的用户界面",
            "全栈": "端到端交付能力，适合小团队快速迭代",
            "测试/QA": "质量保障，Agent 产品的可靠性验证",
            "策划/运营": "产品策划与运营推广，非技术侧支撑",
            "工程": "通用工程岗位，技术执行层",
            "其他": "未归类",
        }
        for direction, count in directions.items():
            pct = f"{count / direction_total * 100:.1f}%"
            interpretation = direction_interpretations.get(direction, "")
            lines.append(f"| {direction} | {count} | {pct} | {interpretation} |")
        lines.append("")

    # 招聘类型分析
    recruit_type_stats = Counter(j.get("recruit_type", "") or "未知" for j in all_jobs)
    if recruit_type_stats:
        lines += [
            "---",
            "",
            "## 四、招聘类型分析",
            "",
        ]
        total_typed = sum(recruit_type_stats.values())
        unknown_ratio = recruit_type_stats.get("未知", 0) / total_typed if total_typed > 0 else 0
        if unknown_ratio > 0.8:
            # "未知"占比过高时，输出说明文字而非无意义表格
            lines += [
                "> 当前多数采集渠道未提供招聘类型字段，本章节暂无有效数据。",
                f'> （"未知"占比 {unknown_ratio * 100:.0f}%，仅飞书 ATS 渠道提供该字段）',
                "",
            ]
        else:
            lines += [
                "| 类型 | 岗位数 | 占比 | 策略解读 |",
                "|------|--------|------|---------|",
            ]
            type_interpretation = {
                "社招": "即战力需求，Agent 方向已进入产品落地阶段",
                "校招": "长期人才储备，培养成本低，应届生可快速适应新范式",
                "实习": "低成本试错，兼顾校招转化通道",
                "未知": "平台未标注类型",
            }
            for rtype, cnt in recruit_type_stats.most_common():
                pct = f"{cnt / total_typed * 100:.1f}%"
                interp = type_interpretation.get(rtype, "")
                lines.append(f"| {rtype} | {cnt} | {pct} | {interp} |")
            lines.append("")

    # 城市分布
    top_cities = [(c, n) for c, n in city_stats.most_common(10) if c and c != "未知"]
    if top_cities:
        lines += [
            "---",
            "",
            "## 五、城市分布",
            "",
            "| 城市 | 岗位数 | 主要来源 |",
            "|------|--------|---------|",
        ]
        city_source = {
            "深圳": "腾讯（CSIG/WXG/IEG 总部）",
            "北京": "字节/MiniMax/智谱（算法/Infra/产品）",
            "上海": "字节/MiniMax/Kimi（应用开发为主）",
            "杭州": "阿里/阿里云",
            "广州": "腾讯（微信BG）",
            "成都": "字节/腾讯（研发中心）",
            "中国香港": "腾讯（国际业务）",
            "贝尔维尤": "腾讯（北美）",
        }
        for city, count in top_cities:
            source = city_source.get(city, "混合")
            lines.append(f"| {city} | {count} | {source} |")
        lines.append("")

    # 岗位变动明细（Part1 的一部分）
    lines += [
        "---",
        "",
        "## 六、岗位变动明细",
        "",
    ]

    if first_run:
        lines += [
            "> 首次采集，无历史对比数据，以下展示全量 L1 岗位。",
            "",
        ]
        lines.append(jobs_to_table(all_jobs[:100]))
    else:
        lines += [f"### 🆕 新增岗位（{len(new_jobs)} 个）", ""]
        if new_by_company:
            for company, cjobs in sorted(new_by_company.items(), key=lambda x: -len(x[1])):
                lines.append(f"**{company}**（{len(cjobs)} 条）")
                lines.append("")
                lines += ["| 职位 | 城市 | 部门 |", "|------|------|------|"]
                for j in cjobs[:30]:
                    title = j.get("title", "")
                    loc = clean_location(j.get("location", "")) or "—"
                    dept = j.get("department", "") or "—"
                    lines.append(f"| {title} | {loc} | {dept} |")
                if len(cjobs) > 30:
                    lines.append(f"| _...（共 {len(cjobs)} 条）_ | | |")
                lines.append("")
        else:
            lines += ["_（今日无新增）_", ""]

        lines += [f"### ❌ 消失岗位（{len(removed_jobs)} 个）", ""]
        lines.append(jobs_to_table(removed_jobs))

    # ─────────────────────────────────────
    # Part 2: 今日新增专项分析
    # ─────────────────────────────────────
    lines += [
        "---",
        "",
        "# Part 2：今日新增深度分析",
        "",
    ]

    if first_run or not new_jobs:
        if first_run:
            lines += [
                "> 首次采集日，无前日对比，以下对全量数据进行结构性分析。",
                "",
            ]
            new_jobs_for_analysis = all_jobs
        else:
            lines += ["> 今日无新增岗位，Part 2 暂无数据。", ""]
            new_jobs_for_analysis = []
    else:
        new_jobs_for_analysis = new_jobs

    if new_jobs_for_analysis:
        # 新增数量对比
        yesterday_total = len(yesterday_jobs) if yesterday_jobs else 0
        delta = (len(new_jobs) - len(removed_jobs)) if not first_run else 0
        lines += [
            "## 七、今日新增总量",
            "",
            f"| 指标 | 数值 |",
            f"|------|------|",
            f"| 今日新增 L1 岗位 | **{len(new_jobs_for_analysis)}** 条 |",
        ]
        if not first_run:
            lines += [
                f"| 昨日总量 | {yesterday_total} 条 |",
                f"| 今日总量 | {total} 条 |",
                f"| 净变动 | {'+' if delta >= 0 else ''}{delta} 条 |",
            ]
        lines.append("")

        # 新增岗位公司分布
        new_company_stats = Counter(j.get("company", "未知") for j in new_jobs_for_analysis)
        lines += [
            "## 八、今日新增公司分布",
            "",
            "| 公司 | 新增条数 | 占比 |",
            "|------|---------|------|",
        ]
        for co, cnt in new_company_stats.most_common():
            pct = f"{cnt / len(new_jobs_for_analysis) * 100:.1f}%"
            lines.append(f"| {co} | {cnt} | {pct} |")
        lines.append("")

        # 新增岗位方向分析
        new_directions = analyze_directions(new_jobs_for_analysis)
        if new_directions:
            lines += [
                "## 九、今日新增方向分布",
                "",
                "| 方向 | 新增条数 | 占比 | 战略信号 |",
                "|------|---------|------|---------|",
            ]
            new_dir_total = sum(new_directions.values())
            new_dir_signals = {
                "基础设施/Infra": "底层能力补强，平台化扩张信号",
                "应用开发": "业务落地加速，产品化成熟",
                "算法/模型": "模型能力迭代，核心差异化投入",
                "产品经理": "PMF 验证阶段，用户体验驱动",
                "评测/安全": "质量压力增大，监管敏感度提升",
                "数据运营": "训练数据飞轮启动，数据工程化",
                "研究员": "下一代能力预研，高优先级探索",
                "SRE/运维": "大规模部署稳定性保障",
                "架构": "系统架构扩张，平台化需求",
                "后端": "服务端工程扩招",
                "前端": "交互层扩充",
                "全栈": "端到端交付加速",
                "测试/QA": "质量保障补强",
                "策划/运营": "产品运营配套",
                "工程": "通用工程补充",
                "其他": "多元化补充",
            }
            for d, cnt in new_directions.items():
                pct = f"{cnt / new_dir_total * 100:.1f}%"
                signal = new_dir_signals.get(d, "")
                lines.append(f"| {d} | {cnt} | {pct} | {signal} |")
            lines.append("")

        # 新增岗位招聘类型
        new_recruit_stats = Counter(j.get("recruit_type", "") or "未知" for j in new_jobs_for_analysis)
        lines += [
            "## 十、今日新增招聘类型",
            "",
            "| 类型 | 新增条数 | 占比 |",
            "|------|---------|------|",
        ]
        for rtype, cnt in new_recruit_stats.most_common():
            pct = f"{cnt / len(new_jobs_for_analysis) * 100:.1f}%"
            lines.append(f"| {rtype} | {cnt} | {pct} |")
        lines.append("")

        # 新增岗位关键词词频（词表匹配法，避免正则碎片问题）
        import re as _re
        # 已知有意义的关键词词表（中英文）
        _KNOWN_KEYWORDS = [
            # 英文关键词
            "Agent", "LLM", "Infra", "RLHF", "Coding", "RAG", "MCP",
            "Engineer", "Researcher", "Scientist", "DevOps", "SRE",
            "TikTok", "Coze", "CodeBuddy", "WorkBuddy", "PICO",
            # 中文关键词（按长度降序，长词优先匹配）
            "解决方案架构师", "研发工程师", "算法工程师", "产品经理",
            "大模型", "智能体", "多模态", "具身智能", "强化学习",
            "架构师", "全栈", "前端", "后端", "测试", "运维",
            "评测", "安全", "训练", "推理", "数据", "运营",
            "阿里云", "腾讯云", "百炼", "通义", "元宝", "火山引擎",
        ]
        # 按长度降序排（长词优先匹配）
        _KNOWN_KEYWORDS.sort(key=lambda x: -len(x))

        title_words = []
        for j in new_jobs_for_analysis:
            title = j.get("title", "") or ""
            title_lower = title.lower()
            matched_positions = set()  # 避免重叠匹配
            for kw in _KNOWN_KEYWORDS:
                kw_lower = kw.lower()
                start = 0
                while True:
                    idx = title_lower.find(kw_lower, start)
                    if idx == -1:
                        break
                    # 检查是否与已匹配位置重叠
                    positions = set(range(idx, idx + len(kw)))
                    if not positions & matched_positions:
                        title_words.append(kw.lower() if kw.isascii() else kw)
                        matched_positions |= positions
                    start = idx + 1
        word_freq = Counter(title_words).most_common(20)
        if word_freq:
            lines += [
                "## 十一、今日新增岗位标题高频词",
                "",
                "| 关键词 | 出现次数 | 说明 |",
                "|--------|---------|------|",
            ]
            word_explain = {
                "agent": "Agent 类岗位核心词",
                "llm": "大语言模型方向",
                "infra": "基础设施类岗位",
                "rlhf": "强化学习人类反馈，对齐方向",
                "multimodal": "多模态能力方向",
                "大模型": "LLM 应用/研究岗位",
                "智能体": "Agent 应用层开发",
                "推理": "模型推理优化",
                "评测": "模型/产品质量保障",
                "训练": "模型训练工程",
                "数据": "数据工程/标注",
                "架构": "系统架构设计",
                "算法": "算法研究方向",
                "测试": "测试开发",
                "产品": "产品设计",
                "运营": "内容/数据运营",
            }
            for word, cnt in word_freq[:15]:
                explain = word_explain.get(word, "")
                lines.append(f"| {word} | {cnt} | {explain} |")
            lines.append("")

        # 今日新增 insights
        lines += [
            "## 十二、今日新增 Insights",
            "",
        ]
        if not first_run and new_jobs:
            # 找今日最活跃公司
            top_new_co = new_company_stats.most_common(1)[0] if new_company_stats else ("未知", 0)
            lines.append(
                f"- 📈 **今日新增主力**：{top_new_co[0]}（{top_new_co[1]}条），"
                f"占今日新增 {top_new_co[1] / len(new_jobs) * 100:.1f}%。"
            )
            # 新增方向集中度
            if new_directions:
                top_dir_new = list(new_directions.items())[0]
                lines.append(
                    f"- 🎯 **方向集中度**：今日新增最多的方向是「{top_dir_new[0]}」（{top_new_co[1]}条），"
                    f"说明该方向 HC 在本日集中释放。"
                )
            # 多家同向信号
            same_dir_companies = {}
            for j in new_jobs:
                dirs = analyze_directions([j])
                for d in dirs:
                    same_dir_companies.setdefault(d, set()).add(j.get("company", ""))
            multi_co_dirs = [(d, cos) for d, cos in same_dir_companies.items() if len(cos) >= 3]
            if multi_co_dirs:
                for d, cos in multi_co_dirs:
                    lines.append(
                        f"- 🔥 **行业级信号**：「{d}」方向今日在 {len(cos)} 家公司同时有新增"
                        f"（{', '.join(cos)}），属于全行业性需求共振，非单点现象。"
                    )
        elif first_run:
            lines.append(
                f"- 📊 首次采集全量数据共 {len(all_jobs)} 条，已建立基准线，后续每日对比此基准。"
            )
        lines.append("")

    # 采集状态说明（动态生成，根据实际采集结果判断状态）
    _channel_info = {
        "字节跳动": ("jobs.bytedance.com", "API 直连", "直连，不走代理"),
        "腾讯": ("careers.tencent.com", "API 直连", "直连"),
        "阿里巴巴": ("talent-holding.alibaba.com", "Playwright DOM", "沙箱 IP 403，UA 绕过"),
        "阿里云": ("careers.aliyun.com", "Playwright DOM", "同上"),
        "智谱AI": ("app.mokahr.com/zphz", "Playwright DOM", "飞书封锁，改用 mokahr 官网"),
        "Kimi": ("app.mokahr.com/moonshot", "Playwright DOM", "飞书封锁，改用 mokahr 官网"),
        "MiniMax": ("vrfi1sk8a0.jobs.feishu.cn", "Playwright + 上游代理", "飞书封锁，catclaw-search 降级"),
    }
    lines += [
        "---",
        "",
        "## 采集状态与数据说明",
        "",
        "| 公司 | 采集渠道 | 方式 | 状态 | 备注 |",
        "|------|---------|------|------|------|",
    ]
    for co_name, (channel, method, note) in _channel_info.items():
        snap_key = company_display_map.get(co_name, co_name)
        co_count = company_stats.get(snap_key, 0)
        # 检查 companies_meta 是否有错误信息
        co_meta = companies_meta.get(snap_key, companies_meta.get(co_name, {}))
        has_error = co_meta.get("error") or co_meta.get("blocked") or co_meta.get("warning")
        is_fallback = co_meta.get("source") == "catclaw-search-fallback"
        if co_count > 0 and is_fallback:
            status = "⚠️ 搜索降级"
            note = co_meta.get("note", "BOSS直聘搜索降级，覆盖率约60-80%")[:60]
        elif co_count > 0:
            status = "✅ 正常"
        elif has_error:
            err_reason = co_meta.get("error") or co_meta.get("reason", "采集异常")
            status = f"❌ 失败"
            note = str(err_reason)[:50]
        else:
            status = "⚠️ 0条"
        lines.append(f"| {co_name} | {channel} | {method} | {status} | {note} |")
    # ─────────────────────────────────────
    # 深度分析报告（研究级）
    # ─────────────────────────────────────
    # new_directions 在 new_jobs_for_analysis 为空时未定义，需兜底
    _new_dir = analyze_directions(new_jobs_for_analysis) if new_jobs_for_analysis else {}
    deep_analysis = _build_deep_analysis(
        date_str, all_jobs, new_jobs, removed_jobs,
        yesterday_jobs, company_stats, yesterday_company_stats,
        directions, _new_dir,
        city_stats, companies_meta,
    )
    if deep_analysis:
        lines += deep_analysis

    lines += [
        "",
        "---",
        "",
        f"*本报告由 Agent 岗位监控系统 V4.3 自动生成 · 数据口径：L1 精准过滤 · {date_str}*",
    ]

    return "\n".join(lines)


def push_to_citadel(title: str, content: str, parent_id: str | None) -> tuple[bool, str]:
    """push to docs，返回 (success, doc_url)"""
    oa_skills_path = shutil.which("oa-skills")
    if not oa_skills_path:
        print("[WARNING] oa-skills 命令不存在，跳过docs push")
        return False, ""

    cmd = [
        oa_skills_path, "citadel", "createDocument",
        "--title", title,
        "--content", content,
    ]
    if parent_id and parent_id.lower() not in ("null", "none", ""):
        cmd += ["--parentId", parent_id]

    print(f"[docs] 执行推送：{' '.join(cmd[:4])} ...")
    import re as _re

    def _try_push() -> tuple[bool, str]:
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
            output = result.stdout.strip()
            if result.returncode == 0:
                print(f"[docs] 推送成功！\n{output}")
                # Parse document URL from oa-skills CLI output (customize for your docs platform)
                m = _re.search(r'https://[^/]+/collabpage/(\d+)', output)
                url = m.group(0) if m else ""
                return True, url
            else:
                print(f"[docs] 推送失败（返回码 {result.returncode}）：\n{result.stderr.strip()}")
                return False, ""
        except subprocess.TimeoutExpired:
            print("[docs] 推送超时（90s）")
            return False, ""
        except Exception as e:
            print(f"[docs] 推送异常：{e}")
            return False, ""

    success, url = _try_push()
    # oa-skills 自动升级后 returncode=0 但无 collabpage 链接，自动重试一次
    if success and not url:
        print("[docs] 未提取到文档链接（可能触发了 oa-skills 自动升级），等待 5s 后自动重试...")
        import time; time.sleep(5)
        success, url = _try_push()
    return success, url


def save_local_report(date_str: str, content: str) -> str:
    os.makedirs(REPORTS_DIR, exist_ok=True)
    path = os.path.join(REPORTS_DIR, f"{date_str}-report.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def main():
    parser = argparse.ArgumentParser(description="Agent 岗位docs push script V2")
    parser.add_argument("--date", default=None, help="日期 YYYY-MM-DD，默认今天")
    parser.add_argument("--parent-id", default="2755367648",
                        help="docs parent document ID，默认 Agent岗位监控父文档")
    args = parser.parse_args()

    today = datetime.now(CST).strftime("%Y-%m-%d") if args.date is None else args.date

    print(f"\n{'='*50}")
    print(f"Agent 岗位docs push {today}")
    print(f"{'='*50}")

    diff = load_diff(today)
    if diff is None:
        print(f"[ERROR] 今日 diff 不存在，请先运行 daily_diff.py")
        return 1

    snapshot = load_snapshot(today)
    yesterday_snapshot = load_yesterday_snapshot(today)

    report_md = build_report(today, diff, snapshot, yesterday_snapshot)
    local_path = save_local_report(today, report_md)
    print(f"本地报告已保存：{local_path}")

    title = f"Agent岗位日报 {today}"
    success, doc_url = push_to_citadel(title, report_md, args.parent_id)

    if not success:
        print(f"[WARNING] docs push失败，本地报告已保存：{local_path}")

    print(f"{'='*50}\n")
    # 输出结构化结果供 cron session 使用
    result = {
        "success": success,
        "doc_url": doc_url,
        "local_path": local_path,
        "total": snapshot.get("total", 0) if snapshot else 0,
        "new_count": len(diff.get("new_jobs", [])),
        "removed_count": len(diff.get("removed_jobs", [])),
    }
    print(f"RESULT_JSON: {json.dumps(result, ensure_ascii=False)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
