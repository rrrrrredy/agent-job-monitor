#!/usr/bin/env python3
"""
Agent Job Daily Collection Script v2.1
Supported: Tencent, ByteDance (direct API)
          Alibaba, Aliyun (Playwright DOM)
          Zhipu AI, Kimi (mokahr Playwright DOM)
          MiniMax (Feishu ATS + Playwright + HTTP proxy)
Usage: python3 daily_collect.py [--date YYYY-MM-DD] [--company Tencent]
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

    # 2. playwright（阿里/智谱/Kimi/MiniMax 采集依赖）
    try:
        import playwright  # noqa: F401
    except ImportError:
        errors.append(
            "缺少 Python 包 'playwright'（浏览器采集依赖）\n"
            "  安装命令：pip install playwright && python3 -m playwright install chromium"
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
PROXY = {"http": os.environ.get("HTTP_PROXY", ""), "https": os.environ.get("HTTPS_PROXY", "")}
# If your IP is blocked by Feishu ATS, set HTTP_PROXY/HTTPS_PROXY environment variables
# Example: export HTTP_PROXY=http://your-proxy:3128
# If not blocked (curl -I https://vrfi1sk8a0.jobs.feishu.cn/379481/ returns 200), use empty dict:
# PROXY = {}
NO_PROXY = {}  # 字节/腾讯不能走代理（代理返回 405）
L1_KEYWORDS = ["Agent", "智能体"]  # mokahr 大小写不敏感，无需重复"agent"
MAX_RETRIES = 3
RETRY_DELAY = 2
REQUEST_TIMEOUT = 20

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE_DIR = os.path.dirname(SCRIPT_DIR)
SNAPSHOTS_DIR = os.path.join(WORKSPACE_DIR, "snapshots")

CST = timezone(timedelta(hours=8))

# Playwright browser operation timeout (ms)
PW_WAIT_MS = 4000
PW_LOAD_TIMEOUT = 20000  # ms

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
        # Handle jobs without id field (e.g. Feishu ATS collected MiniMax jobs)
        job_id = j.get("id") or j.get("url") or f"{j.get('title','')}_{j.get('company','')}"
        if job_id not in seen:
            seen.add(job_id)
            result.append(j)
    return result


# ─────────────────────────────────────────
# Playwright browser singleton (lazy init)
# ─────────────────────────────────────────
_pw_instance = None
_pw_browser = None
_pw_page = None


def _find_chromium_executable() -> str | None:
    """Auto-detect installed Chromium binary (handles version mismatch)."""
    import glob as _glob
    candidates = sorted(
        _glob.glob("/opt/playwright/chromium-*/chrome-linux64/chrome"),
        reverse=True,
    )
    if not candidates:
        # Also check common locations
        for path in ["/usr/bin/chromium", "/usr/bin/chromium-browser", "/usr/bin/google-chrome"]:
            if os.path.exists(path):
                return path
    return candidates[0] if candidates else None


def _get_browser_page():
    """Get or create a Playwright browser page (singleton)."""
    global _pw_instance, _pw_browser, _pw_page
    if _pw_page is not None:
        return _pw_page

    from playwright.sync_api import sync_playwright
    _pw_instance = sync_playwright().start()

    launch_opts = {"headless": True}
    proxy_url = os.environ.get("HTTP_PROXY") or os.environ.get("HTTPS_PROXY")
    if proxy_url:
        launch_opts["proxy"] = {"server": proxy_url}

    _exec = _find_chromium_executable()
    if _exec:
        launch_opts["executable_path"] = _exec

    _pw_browser = _pw_instance.chromium.launch(**launch_opts)
    _pw_page = _pw_browser.new_page()
    return _pw_page


def _close_browser():
    """Clean up Playwright browser."""
    global _pw_instance, _pw_browser, _pw_page
    if _pw_browser:
        try:
            _pw_browser.close()
        except Exception:
            pass
    if _pw_instance:
        try:
            _pw_instance.stop()
        except Exception:
            pass
    _pw_instance = _pw_browser = _pw_page = None


def pw_navigate(url: str) -> bool:
    """Navigate to URL and wait for load."""
    page = _get_browser_page()
    try:
        page.goto(url, timeout=PW_LOAD_TIMEOUT, wait_until="networkidle")
        page.wait_for_timeout(PW_WAIT_MS)
        return True
    except Exception as e:
        print(f"  [WARN] Navigation to {url} failed: {e}")
        return False


def pw_eval(js: str) -> str:
    """Execute JavaScript and return result as string."""
    page = _get_browser_page()
    try:
        result = page.evaluate(js)
        return str(result) if result is not None else ""
    except Exception as e:
        print(f"  [WARN] JS eval failed: {e}")
        return ""


def pw_fill(selector: str, text: str):
    """Fill a form field."""
    page = _get_browser_page()
    try:
        page.fill(selector, text, timeout=10000)
    except Exception as e:
        print(f"  [WARN] Fill {selector} failed: {e}")


def pw_press(selector: str, key: str):
    """Press a key on an element."""
    page = _get_browser_page()
    try:
        page.press(selector, key, timeout=10000)
    except Exception as e:
        print(f"  [WARN] Press {key} on {selector} failed: {e}")


def pw_wait(ms: int):
    """Wait for specified milliseconds."""
    page = _get_browser_page()
    page.wait_for_timeout(ms)


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
    Generic Alibaba-family job page collection (Playwright DOM)
    base_page_url: 职位列表页 URL（不含 keyword 参数），如
      https://careers.aliyun.com/off-campus/position-list?lang=zh
    Strategy: navigate to job list page → fill search box → Enter → paginate
    Note: URL keyword params don't work for SPA, must use search box to trigger filter
    """
    print(f"[{company}] Starting collection (Playwright)...")
    all_jobs = []
    errors = []

    # Search box selector (consistent across both sites)
    SEARCH_SELECTORS = [
        'input[placeholder="输入关键词搜索职位"]',
        'input[placeholder="搜索职位关键词"]',
        'input[placeholder="请输入关键词"]',
        'input[type="text"]',
    ]

    for kw in keywords:
        print(f"  [{company}] 关键词={kw}")

        # 导航到列表页
        pw_navigate(base_page_url)

        # Find and fill search box
        filled = False
        for sel in SEARCH_SELECTORS:
            check = pw_eval(f'document.querySelector({json.dumps(sel)}) ? "found" : "not"')
            if "found" in check:
                pw_fill(sel, kw)
                pw_press(sel, "Enter")
                pw_wait(4000)
                filled = True
                break

        if not filled:
            print(f"    [WARN] 找不到搜索框，跳过")
            errors.append(f"keyword={kw} 搜索框未找到")
            continue

        # First page
        text = pw_eval("document.body.innerText")
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

        # Pagination
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
            result = pw_eval(next_js)
            if "not_found" in result:
                print(f"    找不到下一页，停止于第{page-1}页")
                break

            pw_wait(3000)
            text = pw_eval("document.body.innerText")
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
        loc = p.slice(0, 30);
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
    print(f"[{company}] Starting collection (mokahr Playwright)...")
    all_jobs = []
    errors = []

    for kw in keywords:
        url = f"{base_url}#/jobs?keyword={kw}"
        print(f"  [{company}] 关键词={kw}")
        pw_navigate(url)

        raw = pw_eval(MOKAHR_JOB_JS)
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
            # Keyword filter: ensure title is relevant (mokahr search may return noise)
            kw_match = any(k.lower() in title.lower() for k in L1_KEYWORDS)
            if not kw_match and kw not in ["Agent", "agent", "智能体"]:
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
    # Second filter: ensure at least one L1 keyword in title
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
                company_jobs.append({
                    "id": make_job_id("腾讯", title, location),
                    "company": "腾讯",
                    "title": title,
                    "department": dept,
                    "location": location,
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
                company_jobs.append({
                    "id": make_job_id("字节跳动", title, location),
                    "company": "字节跳动",
                    "title": title,
                    "department": dept,
                    "location": location,
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
# Alibaba Group (Playwright DOM)
# Including DAMO Academy, Tongyi Labs, etc.
# ─────────────────────────────────────────
def collect_alibaba(keywords: list) -> dict:
    return collect_ali_browser(
        base_page_url="https://talent-holding.alibaba.com/off-campus/position-list?lang=zh",
        company="阿里巴巴",
        keywords=keywords,
        max_pages=15,
    )


# ─────────────────────────────────────────
# Aliyun (Playwright DOM)
# ─────────────────────────────────────────
def collect_aliyun(keywords: list) -> dict:
    return collect_ali_browser(
        base_page_url="https://careers.aliyun.com/off-campus/position-list?lang=zh",
        company="阿里云",
        keywords=keywords,
        max_pages=10,
    )


# ─────────────────────────────────────────
# Zhipu AI (mokahr Playwright DOM)
# ─────────────────────────────────────────
def collect_zhipu(keywords: list) -> dict:
    return collect_mokahr_browser(
        base_url="https://app.mokahr.com/social-recruitment/zphz/148983?locale=zh-CN",
        company="智谱AI",
        keywords=keywords,
    )


# ─────────────────────────────────────────
# Kimi (Moonshot) (mokahr Playwright DOM)
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
    proxy: str = "",
) -> dict:
    """
    Generic Feishu ATS candidate portal collector (V2.0).

    Feishu ATS SaaS is pure CSR architecture — all API requests (/api/v1/search/job/posts)
    are dynamically initiated by browser JS (with _signature signing, not forgeable).
    Some exit IPs are blocked by Feishu at the TCP layer, requiring an HTTP proxy.

    Approach: Playwright Chromium + HTTP proxy (if needed)
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
# MiniMax（稀宇科技）—— 使用通用飞书 ATS 采集器
# ─────────────────────────────────────────
def collect_minimax(keywords: list) -> dict:
    """MiniMax 招聘：vrfi1sk8a0.jobs.feishu.cn，通过 collect_feishu_ats() 采集。"""
    return collect_feishu_ats(
        tenant_id="vrfi1sk8a0",
        website_path="379481",
        company="MiniMax",
        keywords=keywords,
    )


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

    snapshot = {
        "date": today,
        "collected_at": collected_at,
        "companies": companies_result,
        "total": len(all_jobs),
        "jobs": all_jobs,
        "errors": errors,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*50}")
    print(f"采集完成！总计 {len(all_jobs)} 条 L1 岗位")
    print(f"快照已写入：{output_path}")
    if errors:
        print(f"⚠️  {len(errors)} 家公司采集出错：{[e['company'] for e in errors]}")
    print(f"{'='*50}\n")

    # Cleanup browser
    _close_browser()

    return 0


if __name__ == "__main__":
    sys.exit(main())
