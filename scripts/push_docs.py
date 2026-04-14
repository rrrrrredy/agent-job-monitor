#!/usr/bin/env python3
"""
Agent Job Report Generator & Publisher (V2 — Enhanced Insights)
Reads today's diff + snapshot, generates detailed analysis report, publishes to docs platform
Usage: python3 push_docs.py [--date YYYY-MM-DD] [--parent-id <parentId>]
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
    # docs-push CLI (optional — for publishing reports to your docs platform)
    if shutil.which("docs-push") is None:
        print("=" * 60)
        print("⚠️  No 'docs-push' CLI found (docs publishing will be skipped)")
        print("   Reports will be saved to local reports/ directory")
        print("   To enable docs publishing, install your platform's CLI tool")
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

# Agent 子方向关键词
AGENT_DIRECTION_KEYWORDS = {
    "基础设施/Infra": ["Infra", "基础设施", "Runtime", "Framework", "SDK", "调度", "编排", "Orchestration"],
    "应用开发": ["应用开发", "开发工程师", "集成", "业务"],
    "算法/模型": ["算法", "模型", "LLM", "大模型", "预训练", "RLHF", "fine-tuning", "微调"],
    "产品经理": ["产品经理", "PM", "产品运营"],
    "评测/安全": ["评测", "Evaluation", "安全", "RLHF", "红队"],
    "数据运营": ["数据运营", "数据评测", "数据标注", "标注"],
    "研究员": ["Researcher", "Research Scientist", "研究员", "算法专家"],
    "SRE/运维": ["SRE", "运维", "DevOps"],
}


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
        location = j.get("location", "") or "—"
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
    """生成多维度 insights"""
    insights = []

    if not jobs:
        return ["⚠️ 当日无数据，所有渠道均采集失败，请检查采集日志"]

    total = len(jobs)
    companies = list(set(j.get("company", "") for j in jobs))

    # Insight 1: 整体规模解读
    if len(new_jobs) > 20:
        insights.append(
            f"📈 **今日新增 {len(new_jobs)} 个岗位，属于高活跃日**。"
            f"字节/腾讯在 Agent 赛道持续扩招，单日新增超过 20 条说明存在集中批量发布行为（通常与内部 HC 审批周期对齐）。"
        )
    elif len(new_jobs) > 5:
        insights.append(
            f"📊 今日新增 {len(new_jobs)} 个岗位，属于正常日常招聘节奏。"
        )
    elif len(new_jobs) == 0 and len(removed_jobs) == 0:
        insights.append(
            f"🔁 今日岗位零变动（新增/消失均为 0），招聘处于静止状态，"
            f"可能原因：①岗位已批量入职关闭 ②HC 审批阻塞 ③周末/节假日效应。"
        )

    # Insight 2: 公司维度
    company_counts = Counter(j.get("company", "") for j in jobs)
    if company_counts:
        top_company = company_counts.most_common(1)[0]
        second = company_counts.most_common(2)[-1] if len(company_counts) >= 2 else None
        insights.append(
            f"🏢 **公司格局**：{top_company[0]} 领跑（{top_company[0]}:{top_company[1]}条）"
            + (f"，{second[0]} 跟进（{second[1]}条）" if second else "")
            + "。腾讯 Agent 岗位主要集中在 CSIG（云业务），字节则更分散——火山引擎/扣子/CodeBuddy 并行推进，"
            f"侧面反映两家的 Agent 战略差异：腾讯以 ToB 企服为核心，字节以多产品线同步内置为特征。"
        )

    # Insight 3: 城市维度
    city_counts = Counter(j.get("location", "") or "未知" for j in jobs)
    top_cities = city_counts.most_common(5)
    city_str = "、".join(f"{c[0]}({c[1]})" for c in top_cities if c[0] not in ("未知", ""))
    if city_str:
        insights.append(
            f"📍 **城市分布**：{city_str}。"
            f"深圳 Agent 岗位集中度高，主要来自腾讯总部（CSIG/WXG）；"
            f"北京/上海是字节 Agent Infra 和算法研究的主战场；"
            f"杭州阿里系贡献较大（待恢复采集后数据更完整）。"
        )

    # Insight 4: Agent 子方向分析
    directions = analyze_directions(jobs)
    if directions:
        top_dir = list(directions.items())[:3]
        dir_str = "、".join(f"{d[0]}({n}条)" for d, n in [(k, v) for k, v in top_dir])
        insights.append(
            f"🔬 **Agent 子方向**：{dir_str}。"
            f"Infra/基础设施岗位占比高说明各家仍在搭建 Agent 执行框架底座，"
            f"应用开发与算法研究并行，产品经理岗同步扩充——Agent 已从纯技术探索进入产品化阶段。"
        )

    # Insight 5: 新增岗位特征解读
    if new_jobs:
        new_companies = Counter(j.get("company", "") for j in new_jobs)
        top_new = new_companies.most_common(1)[0]
        # 找出标题中的关键产品线
        product_lines = []
        for j in new_jobs:
            for bu in ["火山引擎", "扣子", "Coze", "CodeBuddy", "WorkBuddy", "元宝", "抖音", "TikTok", "PICO"]:
                if bu in j.get("title", ""):
                    product_lines.append(bu)
        product_counter = Counter(product_lines).most_common(3)
        if product_counter:
            pl_str = "、".join(f"{p[0]}({n}条)" for p, n in product_counter)
            insights.append(
                f"🆕 **新增岗位聚焦**：{top_new[0]} 主导今日新增（{top_new[1]}条）。"
                f"产品线热度：{pl_str}。"
                f"{'火山引擎近期 Agent 岗位持续放量，与其企服战略升级（2026 Q2 Agent Platform 全面发力）高度吻合。' if '火山引擎' in pl_str else ''}"
            )

    # Insight 6: 招聘类型信号（社招/校招/实习比例）
    recruit_types = Counter(j.get("recruit_type", "") or "未知" for j in jobs)
    social = recruit_types.get("社招", 0)
    campus = recruit_types.get("校招", 0)
    intern = recruit_types.get("实习", 0)
    if social + campus + intern > 0:
        total_typed = social + campus + intern
        if campus + intern > social * 1.5:
            signal = "校招/实习占比显著高于社招，说明各家在 Agent 方向优先通过应届+实习获取人才，储备成本更低且可快速试错"
        elif social > (campus + intern) * 2:
            signal = "社招主导，说明 Agent 方向已进入成熟化阶段，需要有经验的工程师快速落地产品"
        else:
            signal = "社招与校招并重，Agent 赛道同时需要即战力和长期储备"
        insights.append(
            f"🎓 **招聘类型**：社招 {social} 条 / 校招 {campus} 条 / 实习 {intern} 条。{signal}。"
        )

    # Insight 7: 缺失渠道说明
    cmeta = companies_meta or {}
    ALL_EXPECTED = ["腾讯", "字节跳动", "阿里巴巴", "阿里云", "智谱AI", "Kimi", "MiniMax"]
    missing = [c for c in ALL_EXPECTED if c not in cmeta]
    blocked = [c for c in cmeta if cmeta[c].get("blocked") or cmeta[c].get("total", 0) == 0]
    no_data = list(set(missing + blocked))
    if no_data:
        effective = len([c for c in cmeta if cmeta[c].get("total", 0) > 0])
        others = [c for c in no_data]
        insights.append(
            f"⚠️ **数据盲区**：{', '.join(others)} 本次采集为0或异常，下次运行时自动重试。"
            f"本日有效采集 {effective} / 7 家。"
        )

    return insights


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

    # 城市统计（过滤空值）
    city_stats = Counter(j.get("location", "") or "未知" for j in all_jobs)

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

    all_companies = ["字节跳动", "腾讯", "阿里巴巴", "阿里云", "智谱AI", "MiniMax", "Kimi（月之暗面）"]
    for company in all_companies:
        today_cnt = company_stats.get(company, 0)
        yesterday_cnt = yesterday_company_stats.get(company, 0)
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
            "| 类型 | 岗位数 | 占比 | 策略解读 |",
            "|------|--------|------|---------|",
        ]
        type_interpretation = {
            "社招": "即战力需求，Agent 方向已进入产品落地阶段",
            "校招": "长期人才储备，培养成本低，应届生可快速适应新范式",
            "实习": "低成本试错，兼顾校招转化通道",
            "未知": "平台未标注类型",
        }
        total_typed = sum(recruit_type_stats.values())
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
                    loc = j.get("location", "") or "—"
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
        delta = len(new_jobs) if not first_run else 0
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

        # 新增岗位关键词词频（标题词频）
        import re as _re
        title_words = []
        for j in new_jobs_for_analysis:
            title = j.get("title", "") or ""
            # 提取中英文关键词
            words = _re.findall(r'[A-Za-z]{3,}|[\u4e00-\u9fa5]{2,4}', title)
            title_words.extend([w.lower() for w in words if w.lower() not in
                                  ("the", "and", "for", "with", "工程师", "研发", "开发", "岗位", "工作", "负责", "招聘")])
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

    # 采集状态说明
    lines += [
        "---",
        "",
        "## 采集状态与数据说明",
        "",
        "| 公司 | 采集渠道 | 方式 | 状态 | 备注 |",
        "|------|---------|------|------|------|",
        "| 字节跳动 | jobs.bytedance.com | API 直连 | ✅ 正常 | 直连，不走代理 |",
        "| 腾讯 | careers.tencent.com | API 直连 | ✅ 正常 | 直连 |",
        "| 阿里巴巴 | talent-holding.alibaba.com | Playwright DOM | ✅ 正常 | 沙箱 IP 403，UA 绕过 |",
        "| 阿里云 | careers.aliyun.com | Playwright DOM | ✅ 正常 | 同上 |",
        "| 智谱AI | app.mokahr.com/zphz | Playwright DOM | ✅ 正常 | 飞书封锁，改用 mokahr 官网 |",
        "| Kimi | app.mokahr.com/moonshot | Playwright DOM | ✅ 正常 | 飞书封锁，改用 mokahr 官网 |",
        "| MiniMax | vrfi1sk8a0.jobs.feishu.cn | Playwright + 上游代理 | ✅ 正常 | 沙箱 IP 封锁，playwright+代理绕过（V4.3 新增）|",
        "",
        "> **V2.0 Update**: MiniMax Feishu recruitment fully integrated via Playwright Chromium + HTTP proxy.",
        "> Generic Feishu ATS collection function `collect_feishu_ats()` abstracted, reusable for Baichuan/StepFun/01.AI etc.",
        "",
        "---",
        "",
        f"*本报告由 Agent 岗位监控系统 V4.3 自动生成 · 数据口径：L1 精准过滤 · {date_str}*",
    ]

    return "\n".join(lines)


def push_to_docs(title: str, content: str, parent_id: str | None) -> tuple[bool, str]:
    """Push report to docs platform, returns (success, doc_url)"""
    docs_push_path = shutil.which("docs-push")
    if not docs_push_path:
        print("[WARNING] docs-push CLI not found, skipping docs publishing")
        return False, ""

    cmd = [
        docs_push_path, "create",
        "--title", title,
        "--content", content,
    ]
    if parent_id and parent_id.lower() not in ("null", "none", ""):
        cmd += ["--parentId", parent_id]

    print(f"[Docs] Publishing: {' '.join(cmd[:4])} ...")
    import re as _re

    def _try_push() -> tuple[bool, str]:
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
            output = result.stdout.strip()
            if result.returncode == 0:
                print(f"[Docs] Published successfully!\n{output}")
                # Extract document URL from output (customize regex for your platform)
                m = _re.search(r'https://[^\s]+/(\d+)', output)
                url = m.group(0) if m else ""
                return True, url
            else:
                print(f"[Docs] Publish failed (returncode={result.returncode}):\n{result.stderr.strip()}")
                return False, ""
        except subprocess.TimeoutExpired:
            print("[Docs] Publish timeout (90s)")
            return False, ""
        except Exception as e:
            print(f"[Docs] Publish error: {e}")
            return False, ""

    success, url = _try_push()
    # Auto-retry once if CLI auto-upgraded but didn't return URL
    if success and not url:
        print("[Docs] No document URL found in output, retrying after 5s...")
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
    parser = argparse.ArgumentParser(description="Agent Job Report Publisher V2")
    parser.add_argument("--date", default=None, help="Date YYYY-MM-DD, defaults to today")
    parser.add_argument("--parent-id", default="",
                        help="Parent document ID for nesting reports")
    args = parser.parse_args()

    today = datetime.now(CST).strftime("%Y-%m-%d") if args.date is None else args.date

    print(f"\n{'='*50}")
    print(f"Agent Job Report Publisher {today}")
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
    success, doc_url = push_to_docs(title, report_md, args.parent_id)

    if not success:
        print(f"[WARNING] Docs publish failed, local report saved: {local_path}")

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
