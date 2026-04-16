#!/usr/bin/env python3
"""
Agent 岗位每日采集脚本 v2.0
支持：腾讯、字节跳动（直连 API）
     阿里巴巴控股、阿里云（agent-browser DOM 方式，Playwright）
     智谱AI、Kimi（mokahr DOM 方式）
     MiniMax（飞书 ATS + Playwright + 上游代理，V2.0 新增）
用法：python3 daily_collect.py [--date YYYY-MM-DD] [--company 腾讯]
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta

# ─────────────────────────────────────────
# 依赖自检（启动时执行，缺失则给出安装指引）
# ─────────────────────────────────────────
def _check_dependencies():
    errors = []
    warnings = []

    # 1. requests
    try:
        import requests as _r  # noqa: F401
    except ImportError:
        errors.append(
            "缺少 Python 包 'requests'（腾讯/字节采集依赖）\n"
            "  安装命令：pip install requests"
        )

    # 2. agent-browser CLI（阿里/智谱/Kimi 采集依赖）
    if shutil.which("agent-browser") is None:
        errors.append(
            "缺少命令 'agent-browser'（阿里/智谱/Kimi DOM 采集依赖）\n"
            "  安装命令：npm i -g agent-browser && agent-browser install"
        )

    # 3. playwright（MiniMax 飞书 ATS 依赖，缺失降级为 WARNING）
    try:
        import playwright  # noqa: F401
    except ImportError:
        warnings.append(
            "缺少 Python 包 'playwright'（MiniMax 飞书 ATS 采集依赖）\n"
            "  安装命令：pip install playwright && python3 -m playwright install chromium\n"
            "  影响：MiniMax 将被跳过，其余公司不受影响"
        )

    if errors:
        print("=" * 60)
        print("❌ 依赖检查失败，以下必要依赖缺失：")
        for i, msg in enumerate(errors, 1):
            print(f"\n  [{i}] {msg}")
        print("\n请安装以上依赖后重新运行。")
        print("=" * 60)
        sys.exit(1)

    if warnings:
        print("=" * 60)
        print("⚠️  依赖警告（不影响主流程，但部分公司将跳过）：")
        for msg in warnings:
            print(f"\n  - {msg}")
        print("=" * 60)

_check_dependencies()

import requests  # noqa: E402（依赖自检后再导入）

# ─────────────────────────────────────────
# 配置
# ─────────────────────────────────────────
_proxy_url = os.environ.get("HTTP_PROXY", os.environ.get("HTTPS_PROXY", ""))
PROXY = {"http": _proxy_url, "https": _proxy_url} if _proxy_url else {}
NO_PROXY = {}  # 字节/腾讯不能走代理（代理返回 405）
L1_KEYWORDS = ["Agent", "智能体"]  # mokahr 大小写不敏感，无需重复"agent"

# 阿里系专用关键词：仅传给 collect_alibaba / collect_aliyun
# 通义/Qwen/千问 是阿里品牌词，不应出现在其他公司搜索中
ALI_EXTRA_KEYWORDS = ["通义", "Qwen", "千问", "ATH", "百炼", "悟空", "大模型", "LLM"]
MAX_RETRIES = 3
RETRY_DELAY = 2
REQUEST_TIMEOUT = 20

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE_DIR = os.path.dirname(SCRIPT_DIR)
SNAPSHOTS_DIR = os.path.join(WORKSPACE_DIR, "snapshots")

CST = timezone(timedelta(hours=8))

# ─────────────────────────────────────────
# 城市名清洗（采集层，写入快照前清洗）
# ─────────────────────────────────────────
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
    loc = loc.strip()
    # 如果含有 JD 特征词，先尝试提取城市再放弃
    _jd_markers = ["【", "岗位", "职责", "负责", "要求", "任职", "全职", "兼职", "实习"]
    has_jd = any(m in loc for m in _jd_markers)
    # 如果 location 很长（>25字符）或含 JD 特征词，说明是 JD 全文污染
    if len(loc) > 25 or has_jd:
        for city in sorted(CITY_NAMES, key=len, reverse=True):
            if city in loc:
                return _CITY_NORMALIZE.get(city, city)
        return ""  # 无法提取有效城市
    # 去掉重复城市名（如 "北京市 北京市 xxx"），仅当首词是已知城市时
    parts = loc.split()
    if len(parts) >= 2 and parts[0] == parts[1] and parts[0] in CITY_NAMES:
        loc = parts[0]
    # 如果 location 后面跟了 JD 内容，只取第一部分
    for city in CITY_NAMES:
        if loc.startswith(city) and len(loc) > len(city) + 5:
            loc = city
            break
    loc = loc.strip()
    return _CITY_NORMALIZE.get(loc, loc)


# ─────────────────────────────────────────
# 标准化 job dict 字段（确保所有 job 有一致的字段集）
# ─────────────────────────────────────────
_STANDARD_JOB_FIELDS = {"id", "company", "title", "department", "location", "url",
                         "date", "match_tier", "match_reason"}


def normalize_job(job: dict) -> dict:
    """确保 job dict 有所有标准字段，清洗 location"""
    for field in _STANDARD_JOB_FIELDS:
        if field not in job:
            job[field] = ""
    job["location"] = clean_location(job.get("location", ""))
    return job


# agent-browser 浏览器操作超时（ms）
AB_WAIT_MS = 4000
AB_LOAD_TIMEOUT = 20  # sec

# ─────────────────────────────────────────
# 工具函数
# ─────────────────────────────────────────
def make_job_id(company: str, title: str, location: str) -> str:
    raw = f"{company}:{title}:{location}"
    h = hashlib.md5(raw.encode()).hexdigest()[:8]
    return f"{company}:{title}:{h}"


def safe_request(method: str, url: str, retries: int = MAX_RETRIES, **kwargs) -> dict | None:
    kwargs.setdefault("proxies", PROXY)
    kwargs.setdefault("timeout", REQUEST_TIMEOUT)
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, **kwargs) if method.upper() == "GET" else requests.post(url, **kwargs)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            print(f"  [WARN] {method} {url} 第{attempt}次失败: {e}")
            if attempt < retries:
                time.sleep(RETRY_DELAY)
    print(f"  [ERROR] {url} 请求失败 {retries} 次，跳过")
    return None


def dedup_jobs(jobs: list) -> list:
    seen = set()
    result = []
    for j in jobs:
        # 兼容无 id 字段的岗位（如飞书 ATS 采集的 MiniMax 岗位）
        job_id = j.get("id") or j.get("url") or f"{j.get('title','')}_{j.get('company','')}"
        if job_id not in seen:
            seen.add(job_id)
            result.append(j)
    return result


def ab_run(*args, timeout=30) -> str:
    """执行 agent-browser 命令，返回 stdout"""
    try:
        r = subprocess.run(["agent-browser"] + list(args), capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except subprocess.TimeoutExpired:
        print(f"  [WARN] agent-browser {args[0]} 超时 {timeout}s")
        return ""
    except Exception as e:
        print(f"  [WARN] agent-browser {args[0]} 错误: {e}")
        return ""


def ab_navigate(url: str) -> bool:
    """导航到 URL，等待 networkidle"""
    ab_run("navigate", url, timeout=AB_LOAD_TIMEOUT + 5)
    ab_run("wait", "--load", "networkidle", timeout=AB_LOAD_TIMEOUT)
    ab_run("wait", str(AB_WAIT_MS), timeout=10)
    return True


def ab_eval(js: str, timeout: int = 30, retries: int = 2) -> str:
    """执行 JS，返回结果字符串。失败自动重试（含增量延迟）。"""
    for attempt in range(1, retries + 1):
        result = ab_run("eval", js, timeout=timeout)
        if result.strip():
            return result
        if attempt < retries:
            wait = 3 * attempt
            print(f"  [RETRY] eval 返回空，{wait}s 后重试 ({attempt}/{retries})")
            time.sleep(wait)
    return ""


# ─────────────────────────────────────────
# 通用：解析阿里系招聘页 innerText
# ─────────────────────────────────────────
def parse_ali_page_text(text: str, company: str) -> tuple[int, list]:
    """从阿里系招聘页 innerText 解析岗位列表和总数。

    两种格式：
    格式A（含类别行，阿里控股）：
      标题\n更新于 DATE\n技术类-算法\n城市
    格式B（无类别行，阿里云）：
      标题\n更新于 DATE\n城市
    """
    lines = [l.strip() for l in text.replace("\\n", "\n").split("\n") if l.strip()]
    jobs = []
    total = 0
    for line in lines:
        m = re.search(r"在招职位共(\d+)个岗位", line)
        if m:
            total = int(m.group(1))

    SKIP_TITLES = {"©", "招聘官网", "关注我们", "立即登录", "版权所有", "增值电信"}

    i = 0
    while i < len(lines):
        # 职位格式：当前行为标题，下一行为"更新于 YYYY-MM-DD"
        if i + 1 < len(lines) and lines[i + 1].startswith("更新于"):
            title = lines[i]
            date = lines[i + 1].replace("更新于 ", "").strip()

            # 跳过噪音标题
            if len(title) < 3 or any(s in title for s in SKIP_TITLES):
                i += 2
                continue

            # 判断 i+2 是类别行还是城市行
            # 类别行特征：含"-"且包含"类"字，如"技术类-算法"
            # 城市行特征：城市名
            cat, loc = "", ""
            if i + 2 < len(lines):
                next_line = lines[i + 2]
                if re.match(r"^[\u4e00-\u9fa5]+类[-—]", next_line) or ("类" in next_line and "-" in next_line and len(next_line) < 20):
                    # 格式A：有类别行
                    cat = next_line
                    loc = lines[i + 3] if i + 3 < len(lines) else ""
                    i += 4
                else:
                    # 格式B：无类别行，i+2 直接是城市
                    loc = next_line
                    i += 3
            else:
                i += 2

            jobs.append({
                "id": make_job_id(company, title, loc),
                "company": company,
                "title": title,
                "department": cat,
                "location": loc,
                "date": date,
                "match_tier": "L1",
                "match_reason": "keyword:Agent",
            })
        else:
            i += 1
    return total, jobs


def collect_ali_browser(base_page_url: str, company: str, keywords: list, max_pages: int = 20) -> dict:
    """
    通用阿里系招聘页采集（agent-browser DOM）
    base_page_url: 职位列表页 URL（不含 keyword 参数），如
      https://careers.aliyun.com/off-campus/position-list?lang=zh
    策略：导航到职位列表页 → 填搜索框 → Enter → 翻页提取
    注：URL keyword 参数对 SPA 无效，必须通过填写搜索框触发过滤
    """
    print(f"[{company}] 开始采集（agent-browser）...")
    all_jobs = []
    errors = []

    # 找搜索框 selector（两个站点一致）
    SEARCH_SELECTORS = [
        'input[placeholder="输入关键词搜索职位"]',
        'input[placeholder="搜索职位关键词"]',
        'input[placeholder="请输入关键词"]',
        'input[type="text"]',
    ]

    for kw in keywords:
        print(f"  [{company}] 关键词={kw}")

        # 导航到列表页
        ab_navigate(base_page_url)

        # 找并填搜索框
        filled = False
        for sel in SEARCH_SELECTORS:
            check = ab_eval(f'document.querySelector({json.dumps(sel)}) ? "found" : "not"')
            if "found" in check:
                ab_run("fill", sel, kw, timeout=10)
                ab_run("press", sel, "Enter", timeout=10)
                ab_run("wait", "4000", timeout=8)
                filled = True
                break

        if not filled:
            print(f"    [WARN] 找不到搜索框，跳过")
            errors.append(f"keyword={kw} 搜索框未找到")
            continue

        # 第一页
        text = ab_eval("document.body.innerText")
        if not text:
            errors.append(f"keyword={kw} 页面加载失败")
            continue

        total, page_jobs = parse_ali_page_text(text, company)
        print(f"    搜索后共 {total} 岗位，第1页 {len(page_jobs)} 条")
        all_jobs.extend(page_jobs)

        if total == 0 or len(page_jobs) == 0:
            continue

        per_page = len(page_jobs) if len(page_jobs) > 0 else 10
        total_pages = min(max_pages, (total + per_page - 1) // per_page)

        # 翻页
        for page in range(2, total_pages + 1):
            next_js = """
(function() {
  const btns = Array.from(document.querySelectorAll('button, a, li'));
  const nextBtn = btns.find(el => {
    const t = (el.innerText || '').trim();
    const cls = (el.className || '').toString();
    return t === '下一页' || t === '>' ||
      (cls.includes('next') && !cls.includes('no-next') && !cls.includes('prev') && !cls.includes('prefix'));
  });
  if (nextBtn && !nextBtn.disabled && !nextBtn.classList?.contains('disabled')) {
    nextBtn.click(); return 'clicked';
  }
  return 'not_found';
})()
"""
            result = ab_eval(next_js)
            if "not_found" in result:
                print(f"    找不到下一页，停止于第{page-1}页")
                break

            ab_run("wait", "3000", timeout=8)
            text = ab_eval("document.body.innerText")
            _, page_jobs = parse_ali_page_text(text, company)
            print(f"    第{page}页 {len(page_jobs)} 条")
            if not page_jobs:
                break
            all_jobs.extend(page_jobs)
            time.sleep(0.5)

    all_jobs = dedup_jobs(all_jobs)
    print(f"[{company}] 采集完成，共 {len(all_jobs)} 条")
    return {"total": len(all_jobs), "jobs": all_jobs, "errors": errors}


# ─────────────────────────────────────────
# 通用：mokahr DOM 采集（智谱/Kimi）
# ─────────────────────────────────────────
MOKAHR_JOB_JS = """
(function() {
  const CITY_NAMES = ['北京','上海','杭州','深圳','广州','成都','武汉','南京','西安','厦门','重庆','天津','苏州','合肥','长沙','郑州','珠海','中国香港','全国'];
  function cleanLoc(raw) {
    if (!raw || raw.length <= 30) return raw || '';
    // 长文本污染：尝试提取第一个中文城市名
    for (const city of CITY_NAMES) {
      if (raw.includes(city)) return city;
    }
    // 提取不到则截断
    return raw.slice(0, 30);
  }
  const items = Array.from(document.querySelectorAll('a[href*="#/job/"]'));
  return JSON.stringify(items.map(a => {
    const text = (a.innerText || '').trim().replace(/\\s+/g, ' ');
    const titleMatch = text.match(/^(.+?)(?:\\s+发布于|\\s+\\d{4}-)/);
    const title = titleMatch ? titleMatch[1].trim() : text.slice(0, 80);
    const parts = text.split(' | ');
    // 找 location（通常最后一个 | 前后包含城市）
    let loc = '', dept = '';
    for (const part of parts) {
      const p = part.trim();
      if (p.includes('市') || p.includes('北京') || p.includes('上海') || p.includes('杭州') || p.includes('深圳') || p.includes('全国')) {
        loc = cleanLoc(p);
      }
    }
    if (parts.length >= 2) dept = parts[parts.length - 2]?.trim()?.slice(0, 30) || '';
    // 日期
    const dateMatch = text.match(/发布于\\s*(\\d{4}-\\d{2}-\\d{2})/);
    const date = dateMatch ? dateMatch[1] : '';
    return {title, dept, loc, date};
  }));
})()
"""

def collect_mokahr_browser(base_url: str, company: str, keywords: list) -> dict:
    """
    mokahr DOM 采集
    base_url: 如 https://app.mokahr.com/social-recruitment/zphz/148983?locale=zh-CN
    """
    print(f"[{company}] 开始采集（mokahr DOM）...")
    all_jobs = []
    errors = []

    for kw in keywords:
        url = f"{base_url}#/jobs?keyword={kw}"
        print(f"  [{company}] 关键词={kw}")
        ab_navigate(url)

        raw = ab_eval(MOKAHR_JOB_JS)
        try:
            # raw 可能带引号
            raw_clean = raw.strip()
            if raw_clean.startswith('"') and raw_clean.endswith('"'):
                raw_clean = raw_clean[1:-1].replace('\\"', '"').replace('\\\\', '\\')
            items = json.loads(raw_clean)
        except Exception as e:
            print(f"  [WARN] 解析失败: {e} raw={raw[:100]}")
            errors.append(f"keyword={kw} 解析失败")
            continue

        print(f"    找到 {len(items)} 条")
        for item in items:
            title = item.get("title", "")
            if not title or len(title) < 2:
                continue
            # 关键词过滤：确保标题或岗位确实相关（mokahr 搜索可能返回噪音）
            kw_match = any(k.lower() in title.lower() for k in L1_KEYWORDS)
            if not kw_match and kw.lower() not in [k.lower() for k in L1_KEYWORDS]:
                continue
            all_jobs.append({
                "id": make_job_id(company, title, item.get("loc", "")),
                "company": company,
                "title": title,
                "department": item.get("dept", ""),
                "location": item.get("loc", ""),
                "date": item.get("date", ""),
                "match_tier": "L1",
                "match_reason": f"keyword:{kw}",
            })
        time.sleep(0.5)

    all_jobs = dedup_jobs(all_jobs)
    # 二次过滤：确保至少有一个搜索关键词在标题中（用传入的 keywords 而非硬编码）
    filtered = [j for j in all_jobs if any(k.lower() in j["title"].lower() for k in L1_KEYWORDS)]
    print(f"[{company}] 采集完成，共 {len(filtered)} 条（原始{len(all_jobs)}条，过滤噪音后）")
    return {"total": len(filtered), "jobs": filtered, "errors": errors}


# ─────────────────────────────────────────
# 腾讯采集（直连 API）
# ─────────────────────────────────────────
def collect_tencent(keywords: list) -> dict:
    print("[腾讯] 开始采集...")
    company_jobs = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json",
    }
    for kw in keywords:
        page = 1
        while True:
            url = "https://careers.tencent.com/tencentcareer/api/post/Query"
            params = {
                "timestamp": int(time.time() * 1000),
                "keyword": kw,
                "pageIndex": page,
                "pageSize": 60,
                "language": "zh-cn",
                "area": "cn",
            }
            data = safe_request("GET", url, headers=headers, params=params, proxies=NO_PROXY)
            if not data:
                break
            posts = data.get("Data", {}).get("Posts", []) or []
            if not posts:
                break
            for p in posts:
                title = p.get("RecruitPostName", "") or p.get("title", "")
                location = p.get("LocationName", "") or p.get("CountryName", "")
                dept = p.get("CategoryName", "") or p.get("BGName", "")
                post_id = str(p.get("PostId", "") or p.get("postId", ""))
                job_url = f"https://careers.tencent.com/jobdesc.html?postId={post_id}" if post_id else ""
                company_jobs.append({
                    "id": make_job_id("腾讯", title, location),
                    "company": "腾讯",
                    "title": title,
                    "department": dept,
                    "location": location,
                    "url": job_url,
                    "match_tier": "L1",
                    "match_reason": f"title:{kw}",
                })
            total = data.get("Data", {}).get("Count", 0) or 0
            if page * 60 >= total:
                break
            page += 1
            time.sleep(0.3)
    company_jobs = dedup_jobs(company_jobs)
    print(f"[腾讯] 采集完成，共 {len(company_jobs)} 条")
    return {"total": len(company_jobs), "jobs": company_jobs}


# ─────────────────────────────────────────
# 字节跳动采集（直连 API）
# ─────────────────────────────────────────
def collect_bytedance(keywords: list) -> dict:
    print("[字节跳动] 开始采集...")
    company_jobs = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    for kw in keywords:
        page = 1
        while True:
            body = {
                "keyword": kw,
                "limit": 50,
                "offset": (page - 1) * 50,
                "job_category_id_list": [],
                "location_code_list": [],
                "subject_id_list": [],
                "portal_type": 2,
                "city_code": "",
            }
            data = safe_request(
                "POST",
                "https://jobs.bytedance.com/api/v1/search/job/posts",
                headers=headers,
                json=body,
                proxies=NO_PROXY,
            )
            if not data:
                break
            job_list = data.get("data", {}).get("job_post_list", []) or []
            if not job_list:
                break
            for p in job_list:
                title = p.get("title", "") or p.get("name", "")
                city_list = p.get("city_list", []) or p.get("location", []) or []
                location = ", ".join(c.get("cn_name", "") for c in city_list if isinstance(c, dict)) if city_list else ""
                dept = p.get("job_category", {}).get("cn_name", "") if isinstance(p.get("job_category"), dict) else ""
                post_id = str(p.get("id", ""))
                job_url = f"https://jobs.bytedance.com/position/{post_id}/detail" if post_id else ""
                company_jobs.append({
                    "id": make_job_id("字节跳动", title, location),
                    "company": "字节跳动",
                    "title": title,
                    "department": dept,
                    "location": location,
                    "url": job_url,
                    "match_tier": "L1",
                    "match_reason": f"title:{kw}",
                })
            total = data.get("data", {}).get("total", 0) or 0
            if page * 50 >= total:
                break
            page += 1
            time.sleep(0.3)
    company_jobs = dedup_jobs(company_jobs)
    print(f"[字节跳动] 采集完成，共 {len(company_jobs)} 条")
    return {"total": len(company_jobs), "jobs": company_jobs}


# ─────────────────────────────────────────
# 阿里巴巴控股集团（agent-browser DOM）
# 含达摩院、通义实验室等 AI 研究机构
# ─────────────────────────────────────────
def collect_alibaba(keywords: list) -> dict:
    # 合并 L2 阿里专用关键词（去重）
    merged = list(dict.fromkeys(keywords + ALI_EXTRA_KEYWORDS))
    return collect_ali_browser(
        base_page_url="https://talent-holding.alibaba.com/off-campus/position-list?lang=zh",
        company="阿里巴巴",
        keywords=merged,
        max_pages=15,
    )


# ─────────────────────────────────────────
# 阿里云（agent-browser DOM）
# ─────────────────────────────────────────
def collect_aliyun(keywords: list) -> dict:
    # 合并 L2 阿里专用关键词（去重）
    merged = list(dict.fromkeys(keywords + ALI_EXTRA_KEYWORDS))
    return collect_ali_browser(
        base_page_url="https://careers.aliyun.com/off-campus/position-list?lang=zh",
        company="阿里云",
        keywords=merged,
        max_pages=10,
    )


# ─────────────────────────────────────────
# 智谱AI（agent-browser mokahr DOM）
# ─────────────────────────────────────────
def collect_zhipu(keywords: list) -> dict:
    return collect_mokahr_browser(
        base_url="https://app.mokahr.com/social-recruitment/zphz/148983?locale=zh-CN",
        company="智谱AI",
        keywords=keywords,
    )


# ─────────────────────────────────────────
# Kimi（月之暗面）（agent-browser mokahr DOM）
# ─────────────────────────────────────────
def collect_kimi(keywords: list) -> dict:
    return collect_mokahr_browser(
        base_url="https://app.mokahr.com/apply/moonshot/148506?sourceToken=1da825ef642385a5951ca5a63f6151c9",
        company="Kimi",
        keywords=keywords,
    )


# ─────────────────────────────────────────
# 通用：飞书 ATS SaaS 候选人门户（V4.3 新增）
# 适用于所有托管在 *.jobs.feishu.cn 的企业招聘页
# ─────────────────────────────────────────
def collect_feishu_ats(
    tenant_id: str,
    website_path: str,
    company: str,
    keywords: list,
    extra_keywords: list = None,
    proxy: str = None,
) -> dict:
    """
    通用飞书 ATS 候选人门户采集器（V4.3）。

    飞书 ATS SaaS 是纯 CSR 架构，所有 API 请求（/api/v1/search/job/posts）
    均由浏览器 JS 动态发起（含 _signature 签名，不可伪造）。
    某些网络环境出口 IP 被飞书 TCP 层封锁，需通过代理访问。

    方案：Playwright Chromium + HTTP proxy（通过 HTTP_PROXY 环境变量或参数传入）
    1. 通过代理加载招聘主页（初始化 session/cookie）
    2. 拦截 /api/v1/search/job/posts 响应，获取结构化 JSON
    3. 通过点击分页器（li.atsx-pagination-item-{n} a）自动翻页
    4. 多关键词搜索，去重合并

    Args:
        tenant_id: 飞书 ATS 租户子域名前缀，如 "vrfi1sk8a0"
        website_path: 招聘站点路径，如 "379481"
        company: 公司名称（用于日志）
        keywords: L1 关键词列表
        extra_keywords: 额外补充关键词（飞书需要关键词匹配，默认 Agent/大模型/智能体）
        proxy: 上游代理地址

    Returns:
        {"total": N, "jobs": [...]} 或 {"total": 0, "jobs": [], "warning": True, "reason": "..."}
    """
    try:
        from playwright.sync_api import sync_playwright
        import urllib.parse as _urlparse
        import json as _json
    except ImportError:
        print(f"[{company}] playwright 未安装，跳过")
        return {"total": 0, "jobs": [], "blocked": True, "reason": "playwright未安装"}

    BASE_URL = f"https://{tenant_id}.jobs.feishu.cn/{website_path}/"
    JOB_URL_PREFIX = f"https://{tenant_id}.jobs.feishu.cn/{website_path}/position/"

    # 合并关键词
    _extra = extra_keywords or ["Agent", "大模型", "智能体"]
    search_terms = list(dict.fromkeys(_extra + [k for k in keywords if k not in _extra]))

    all_jobs: dict = {}
    _captures: list = []

    def _parse_post(post: dict, kw: str) -> dict:
        rt = post.get("recruit_type") or {}
        rt_parent = rt.get("parent") or {}
        city_info = post.get("city_info") or {}
        return {
            "title": post.get("title", ""),
            "company": company,  # 修复：飞书 ATS 解析时必须带 company 字段
            "city": city_info.get("name", ""),
            "department": (post.get("job_category") or {}).get("name", ""),
            "recruit_type": rt_parent.get("name") or rt.get("name", ""),
            "source_keyword": kw,
            "url": f"{JOB_URL_PREFIX}{post.get('id', '')}",
        }

    def _collect_keyword(page, kw: str):
        _captures.clear()
        page.goto(
            BASE_URL + f"?keywords={_urlparse.quote(kw)}",
            timeout=35000,
            wait_until="networkidle",
        )
        new_count = 0

        def _drain():
            nonlocal new_count
            for cap in list(_captures):
                for post in cap.get("data", {}).get("job_post_list", []):
                    job_id = post.get("id", "")
                    if job_id and job_id not in all_jobs:
                        all_jobs[job_id] = _parse_post(post, kw)
                        new_count += 1
            _captures.clear()

        _drain()

        # 自动翻页
        for pg_num in range(2, 30):
            btn = page.query_selector(
                f"li.atsx-pagination-item-{pg_num}:not(.atsx-pagination-disabled) a"
            )
            if not btn:
                break
            btn.click()
            page.wait_for_timeout(1800)
            _drain()

        print(f"  [{company}][{kw}] 新增 {new_count} 条，累计 {len(all_jobs)} 条")

    # 自动检测已安装的 Chromium（兼容版本不匹配）
    def _find_chromium_executable() -> str | None:
        import glob as _glob
        candidates = sorted(
            _glob.glob("/opt/playwright/chromium-*/chrome-linux64/chrome"),
            reverse=True,
        )
        return candidates[0] if candidates else None

    if not proxy:
        proxy = os.environ.get("HTTP_PROXY", os.environ.get("HTTPS_PROXY", ""))

    try:
        with sync_playwright() as pw:
            launch_opts: dict = {"headless": True}
            if proxy:
                launch_opts["proxy"] = {"server": proxy}
            # 如果 playwright 默认路径不存在，用已安装的 chromium
            _exec = _find_chromium_executable()
            if _exec:
                launch_opts["executable_path"] = _exec
            browser = pw.chromium.launch(**launch_opts)
            ctx = browser.new_context(ignore_https_errors=True)
            page = ctx.new_page()

            def _on_response(response):
                if "search/job/posts" in response.url and response.status == 200:
                    try:
                        data = _json.loads(response.body())
                        if data.get("code") == 0:
                            _captures.append(data)
                    except Exception:
                        pass

            page.on("response", _on_response)

            for kw in search_terms:
                _collect_keyword(page, kw)

            browser.close()

        jobs_list = list(all_jobs.values())
        print(f"[{company}] 飞书 ATS 采集完成，共 {len(jobs_list)} 条 L1 岗位")
        return {"total": len(jobs_list), "jobs": jobs_list}

    except Exception as e:
        print(f"[{company}] 飞书 ATS 采集失败: {e}")
        return {"total": 0, "jobs": [], "warning": True, "reason": f"playwright error: {e}"}


# ─────────────────────────────────────────
# MiniMax（稀宇科技）—— 飞书 ATS 主路径 + catclaw-search 降级
# ─────────────────────────────────────────
def _collect_minimax_search_fallback(keywords: list) -> dict:
    """
    MiniMax 搜索降级采集器（方案 A）。
    当飞书 ATS 不通时，通过 catclaw-search 搜索 BOSS 直聘索引数据。
    限制：搜索引擎索引有限，无法覆盖全量，但可覆盖大部分 Agent/AI 岗位。
    """
    print("[MiniMax] 飞书 ATS 不通，启用 catclaw-search 搜索降级...")

    CATCLAW_SCRIPT = "/app/skills/catclaw-search/scripts/catclaw_search.py"
    if not os.path.exists(CATCLAW_SCRIPT):
        return {"total": 0, "jobs": [], "warning": True,
                "reason": "catclaw-search 脚本不存在，搜索降级失败"}

    search_queries = [
        "site:zhipin.com MiniMax Agent",
        "site:zhipin.com MiniMax 大模型",
        "site:zhipin.com MiniMax AI Infra",
        "site:zhipin.com MiniMax 算法",
        "site:zhipin.com MiniMax 产品经理 AI",
        "site:zhipin.com MiniMax 工程师 智能",
        "site:zhipin.com MiniMax 研发 AI",
        "site:zhipin.com MiniMax 测试 Agent",
        "site:zhipin.com MiniMax 推理 训练",
        "site:zhipin.com MiniMax 前端 后端 Agent",
    ]

    # L1 关键词（小写匹配）
    l1_kw = [k.lower() for k in keywords] + [
        "agent", "智能体", "大模型", "llm", "ai ", "gpt", "rlhf",
        "推理", "训练", "nlp", "自然语言", "多模态", "agi", "aigc",
        "infra", "算法", "native",
    ]

    all_jobs = {}  # url -> job dict
    for query in search_queries:
        try:
            r = subprocess.run(
                ["python3", CATCLAW_SCRIPT, "search", query, "-s", "bing", "-n", "10"],
                capture_output=True, text=True, timeout=30,
            )
            if r.returncode != 0:
                continue
            data = json.loads(r.stdout)
            for item in data.get("results", []):
                url = item.get("url", "")
                title = item.get("title", "")
                snippet = item.get("snippet", "")

                # 只保留 BOSS 直聘岗位详情页
                if "zhipin.com/job_detail/" not in url:
                    continue
                if "MiniMax" not in (title + snippet) and "minimax" not in (title + snippet).lower():
                    continue
                if url in all_jobs:
                    continue

                # 从标题提取岗位名
                m = re.search(r'[「](.+?)招聘[」]', title)
                if m:
                    job_title = m.group(1).strip()
                else:
                    # 备用：去掉 BOSS直聘/MiniMax 后缀
                    job_title = re.sub(r'\s*[-–—]\s*(BOSS直聘|MiniMax).*$', '', title).strip("「」 ")
                # 清洗 BOSS 直聘页面标题中的噪音后缀
                job_title = re.sub(r'(是做什么的|任职要求|招聘工资)[_]?.*$', '', job_title)
                job_title = re.sub(r'\s*[-–—]\s*BOSS直聘.*$', '', job_title)
                job_title = re.sub(r'_MiniMax.*$', '', job_title)
                job_title = job_title.rstrip('. ').strip()

                # 从 snippet 提取城市
                city_m = re.search(r'地点：(\S+?)(?=[，,\s])', snippet)
                city = city_m.group(1) if city_m else ""
                # 清理城市（去掉后缀的逗号等）
                city = re.sub(r'[，,。].*$', '', city)

                # L1 关键词过滤
                title_lower = job_title.lower()
                if not any(kw in title_lower for kw in l1_kw):
                    continue

                all_jobs[url] = {
                    "title": job_title,
                    "company": "MiniMax",
                    "location": city,
                    "department": "",
                    "recruit_type": "",
                    "source_keyword": "boss_search",
                    "url": url,
                }
        except Exception as e:
            print(f"[MiniMax] 搜索查询失败 '{query}': {e}")
            continue

    jobs_list = list(all_jobs.values())
    print(f"[MiniMax] 搜索降级完成，共 {len(jobs_list)} 条 L1 岗位（去重后）")

    if len(jobs_list) == 0:
        return {"total": 0, "jobs": [], "warning": True,
                "reason": "搜索降级未找到任何岗位"}

    return {
        "total": len(jobs_list),
        "jobs": jobs_list,
        "source": "catclaw-search-fallback",
        "note": "飞书ATS不通，通过BOSS直聘搜索引擎索引降级采集，覆盖率约60-80%",
    }


def collect_minimax(keywords: list) -> dict:
    """MiniMax 招聘：飞书 ATS 主路径 → catclaw-search 搜索降级。"""
    # 主路径：飞书 ATS
    result = collect_feishu_ats(
        tenant_id="vrfi1sk8a0",
        website_path="379481",
        company="MiniMax",
        keywords=keywords,
    )
    # 主路径成功（有数据），直接返回
    if result.get("total", 0) > 0:
        return result

    # 主路径失败，启用搜索降级
    print(f"[MiniMax] 飞书 ATS 返回 0 条（原因: {result.get('reason', '未知')}），尝试搜索降级...")
    fallback = _collect_minimax_search_fallback(keywords)
    if fallback.get("total", 0) > 0:
        return fallback

    # 两条路径都失败
    return {
        "total": 0,
        "jobs": [],
        "warning": True,
        "reason": f"飞书ATS: {result.get('reason', '失败')}; 搜索降级: {fallback.get('reason', '失败')}",
    }


# ─────────────────────────────────────────
# 主函数
# ─────────────────────────────────────────
COLLECTORS = {
    "腾讯": collect_tencent,
    "字节跳动": collect_bytedance,
    "阿里巴巴": collect_alibaba,
    "阿里云": collect_aliyun,
    "智谱AI": collect_zhipu,
    "Kimi": collect_kimi,
    "MiniMax": collect_minimax,
}


def main():
    parser = argparse.ArgumentParser(description="Agent 岗位每日采集脚本 v2.0")
    parser.add_argument("--date", default=None, help="采集日期 YYYY-MM-DD，默认今天")
    parser.add_argument("--company", default=None,
                        help="只采集指定公司（调试用），如 --company 腾讯")
    args = parser.parse_args()

    today = datetime.now(CST).strftime("%Y-%m-%d") if args.date is None else args.date
    collected_at = datetime.now(CST).isoformat()

    os.makedirs(SNAPSHOTS_DIR, exist_ok=True)
    output_path = os.path.join(SNAPSHOTS_DIR, f"{today}.json")

    print(f"\n{'='*50}")
    print(f"Agent 岗位采集 v2.0  {today}")
    print(f"{'='*50}")

    companies_result = {}
    all_jobs = []
    errors = []

    target_companies = [args.company] if args.company else list(COLLECTORS.keys())

    for company in target_companies:
        if company not in COLLECTORS:
            print(f"[ERROR] 未知公司: {company}")
            continue
        try:
            result = COLLECTORS[company](L1_KEYWORDS)
            companies_result[company] = result
            all_jobs.extend(result["jobs"])
        except Exception as e:
            print(f"[ERROR] {company} 采集异常: {e}")
            errors.append({"company": company, "error": str(e)})
            companies_result[company] = {"total": 0, "jobs": [], "error": str(e)}

    all_jobs = dedup_jobs(all_jobs)

    # 标准化所有 job 字段 + 清洗 location
    all_jobs = [normalize_job(j) for j in all_jobs]

    snapshot = {
        "date": today,
        "collected_at": collected_at,
        "companies": companies_result,
        "total": len(all_jobs),
        "jobs": all_jobs,
        "errors": errors,
    }

    # ─────────────────────────────────────────
    # 方案 C：写前校验 + 快照备份
    # ─────────────────────────────────────────
    # 1. 写前校验：非单公司模式下，检查采集完整性
    if not args.company:
        successful_companies = [c for c, r in companies_result.items() if r.get("total", 0) > 0]
        min_companies = 5  # 至少 5/7 家公司成功
        if len(successful_companies) < min_companies:
            print(f"\n⚠️  [SANITY CHECK 失败] 仅 {len(successful_companies)}/7 家采集成功"
                  f"（{', '.join(successful_companies)}），低于阈值 {min_companies}。")
            # 检查是否有旧快照
            if os.path.exists(output_path):
                old_snap = json.load(open(output_path))
                old_total = old_snap.get("total", 0)
                print(f"   旧快照有 {old_total} 条。本次 {len(all_jobs)} 条。")
                if len(all_jobs) < old_total * 0.5:
                    print(f"   ❌ 新快照不足旧快照 50%（{len(all_jobs)} < {old_total * 0.5:.0f}），"
                          f"拒绝覆盖！旧快照保留。")
                    print(f"   本次采集结果保存到：{output_path}.incomplete")
                    with open(output_path + ".incomplete", "w", encoding="utf-8") as f:
                        json.dump(snapshot, f, ensure_ascii=False, indent=2)
                    return 2  # 非 0 退出码表示数据不完整

    # 2. 旧快照备份（覆盖前 rename）
    if os.path.exists(output_path):
        import glob
        existing_backups = glob.glob(output_path + ".v*")
        next_version = len(existing_backups) + 1
        backup_path = f"{output_path}.v{next_version}"
        os.rename(output_path, backup_path)
        print(f"[BACKUP] 旧快照已备份：{backup_path}")

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*50}")
    print(f"采集完成！总计 {len(all_jobs)} 条 L1 岗位")
    print(f"快照已写入：{output_path}")
    if errors:
        print(f"⚠️  {len(errors)} 家公司采集出错：{[e['company'] for e in errors]}")
    print(f"{'='*50}\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
