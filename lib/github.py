"""GitHub Trending 采集与「星数增量」计算。

数据来源为 GitHub Trending 页面（daily / weekly / monthly），该页面直接给出
对应区间的真实新增星数。由于 GitHub 官方没有「最近三日」档位，这里额外维护
一份本地星数快照；运行满 3 天后，「三日榜」会自动切换为
`今日星数 − 3 日前星数` 的真实增量，冷启动阶段则回退到页面自带数据。

每个榜输出 12 个仓库。
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

from . import http

log = logging.getLogger("ai-intel.github")

TRENDING_URL = "https://github.com/trending?since={since}"
PER_PAGE_N = 12

# GitHub Trending 的档位名 → (页面参数, 页面增量文案关键词, 中文标签)
PERIODS: dict[str, dict] = {
    "daily": {"since": "daily", "match": "today", "label": "今日新增", "days": 1},
    "three_day": {"since": "weekly", "match": "this week", "label": "近三日新增", "days": 3},
    "weekly": {"since": "weekly", "match": "this week", "label": "近一周新增", "days": 7},
    "monthly": {"since": "monthly", "match": "this month", "label": "近一月新增", "days": 30},
}

_ARTICLE_RE = re.compile(r'<article class="Box-row">(.*?)</article>', re.S)
_REPO_RE = re.compile(r'<h2[^>]*>\s*<a[^>]*?href="/([^"]+?)"', re.S)
_DESC_RE = re.compile(r'<p class="col-9[^"]*"[^>]*>(.*?)</p>', re.S)
_LANG_RE = re.compile(r'<span itemprop="programmingLanguage">(.*?)</span>', re.S)
_STARS_RE = re.compile(r'href="/[^"]+/stargazers"[^>]*>(.*?)</a>', re.S)
_FORKS_RE = re.compile(r'href="/[^"]+/forks"[^>]*>(.*?)</a>', re.S)
_PERIOD_RE = re.compile(r"([\d,]+)\s+stars\s+(today|this week|this month)", re.S)
_BUILDERS_RE = re.compile(r'data-hovercard-type="user"[^>]*href="/([^"]+)"', re.S)
_TAG_RE = re.compile(r"<[^>]+>")


def _to_int(raw: str | None) -> int:
    """把 `1,075` 形式的字符串转成整数。"""
    if not raw:
        return 0
    digits = re.sub(r"[^\d]", "", raw)
    return int(digits) if digits else 0


def _clean(raw: str | None) -> str:
    """去标签并压缩空白。"""
    if not raw:
        return ""
    import html as _html

    text = _TAG_RE.sub(" ", raw)
    return " ".join(_html.unescape(text).split())


def parse_trending(html_text: str, period_key: str) -> list[dict]:
    """解析 GitHub Trending 页面。

    Args:
        html_text: 页面 HTML。
        period_key: PERIODS 的键，用于匹配对应区间的增量文案。

    Returns:
        仓库字典列表，含 full_name / description / language / stars / forks / period_stars。
    """
    cfg = PERIODS[period_key]
    out: list[dict] = []
    for block in _ARTICLE_RE.findall(html_text or ""):
        repo_match = _REPO_RE.search(block)
        if not repo_match:
            continue
        full_name = repo_match.group(1).strip().strip("/")
        if full_name.count("/") != 1:
            continue

        # 页面自带的区间增量（形如 `1,075 stars today`）
        page_delta = 0
        for value, label in _PERIOD_RE.findall(block):
            if label == cfg["match"]:
                page_delta = _to_int(value)
                break

        desc_match = _DESC_RE.search(block)
        lang_match = _LANG_RE.search(block)
        stars_match = _STARS_RE.search(block)
        forks_match = _FORKS_RE.search(block)

        out.append(
            {
                "full_name": full_name,
                "owner": full_name.split("/")[0],
                "name": full_name.split("/")[1],
                "url": f"https://github.com/{full_name}",
                "description": _clean(desc_match.group(1)) if desc_match else "",
                "language": _clean(lang_match.group(1)) if lang_match else "",
                "stars": _to_int(_clean(stars_match.group(1))) if stars_match else 0,
                "forks": _to_int(_clean(forks_match.group(1))) if forks_match else 0,
                "page_delta": page_delta,
                "builders": list(dict.fromkeys(_BUILDERS_RE.findall(block)))[:3],
            }
        )
    return out


# --------------------------------------------------------------- 快照 -----
def snapshot_path(data_dir: Path, day: datetime) -> Path:
    """返回某天星数快照的文件路径。"""
    return data_dir / "snapshots" / f"stars-{day.date().isoformat()}.json"


def load_snapshot(path: Path) -> dict[str, int]:
    """读取某天的星数快照；不存在或损坏时返回空字典。"""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return {k: int(v) for k, v in payload.get("stars", {}).items()}
    except (OSError, ValueError, TypeError):
        return {}


def save_snapshot(path: Path, stars: dict[str, int], day: datetime) -> None:
    """写入当天星数快照。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"date": day.date().isoformat(), "stars": stars}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _find_past_snapshot(data_dir: Path, today: datetime, days: int) -> dict[str, int] | None:
    """向前回溯查找 N 天前的快照，容忍 1 天误差（补跑/漏跑场景）。"""
    for offset in (days, days - 1, days + 1, days - 2, days + 2):
        if offset <= 0:
            continue
        path = snapshot_path(data_dir, today - timedelta(days=offset))
        snap = load_snapshot(path)
        if snap:
            return snap
    return None


# --------------------------------------------------------------- 编排 -----
def _build_candidate(repo: dict) -> dict:
    """把 trending 解析结果扩展为统一的候选对象。"""
    return {
        **repo,
        "page_deltas": {repo.get("_since", ""): repo.get("page_delta", 0)},
        "created_deltas": {},
        "appears_in": [],
        "age_days": None,
    }


# ------------------------------------------------- GitHub Search API 补充 -----
SEARCH_API = "https://api.github.com/search/repositories"


def fetch_new_repos(now: datetime, days: int, min_stars: int = 50, per_page: int = 100) -> list[dict]:
    """检索「窗口期内新建」的仓库。

    对于创建时间距今不足 `days` 天的仓库，它在窗口期开始时星数为 0，
    因此 `窗口增量 = 当前星数`，这是一个无需快照即可得出的**真实**增量。

    Args:
        now: 基准时间。
        days: 回溯天数。
        min_stars: 星数下限，过滤噪声仓库。
        per_page: 单页条数（上限 100）。

    Returns:
        仓库信息字典列表；接口不可用或触发限流时返回空列表。
    """
    since = (now - timedelta(days=days)).date().isoformat()
    params = urlencode(
        {
            "q": f"created:>{since} stars:>={min_stars}",
            "sort": "stars",
            "order": "desc",
            "per_page": per_page,
        }
    )
    try:
        payload = http.fetch_json(f"{SEARCH_API}?{params}", timeout=25, retries=1)
    except Exception as exc:  # noqa: BLE001
        log.warning("GitHub Search API 不可用（窗口 %d 天）: %s", days, exc)
        return []

    out: list[dict] = []
    for item in payload.get("items", []) if isinstance(payload, dict) else []:
        created = item.get("created_at") or ""
        try:
            created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
        except ValueError:
            created_dt = now
        out.append(
            {
                "full_name": item.get("full_name", ""),
                "owner": (item.get("owner") or {}).get("login", ""),
                "name": item.get("name", ""),
                "url": item.get("html_url", ""),
                "description": (item.get("description") or "").strip(),
                "language": item.get("language") or "",
                "stars": int(item.get("stargazers_count") or 0),
                "forks": int(item.get("forks_count") or 0),
                "builders": [],
                "page_delta": 0,
                "created_at": created,
                "age_days": (now - created_dt).days,
                "topics": (item.get("topics") or [])[:5],
                "from_search": True,
            }
        )
    return out


def build_github(data_dir: Path, now: datetime | None = None) -> dict:
    """抓取 Trending 三档榜 + 窗口期新仓库，算出各档星数增量。

    候选池由三部分构成：
      1. GitHub Trending 页面（daily / weekly / monthly），带页面真实增量；
      2. 各窗口期内新建的仓库（增量直接等于当前星数，真实值）；
      3. 本地历史快照（运行满 N 天后，可对老项目算出真实差值）。

    增量取值优先级：快照差分 > 新建窗口推算 > 页面增量（必要时按比例外推）。

    Args:
        data_dir: 数据根目录（快照存放于其 snapshots 子目录）。
        now: 基准时间（默认当前 UTC）。

    Returns:
        形如 `{"daily": [...], "three_day": [...], "weekly": [...], "monthly": [...]}`
        的字典，每档 12 条。
    """
    now = now or datetime.now(timezone.utc)

    # 1) 抓取 Trending 三个页面
    page_html: dict[str, str] = {}
    for since in ("daily", "weekly", "monthly"):
        text = http.safe_fetch(TRENDING_URL.format(since=since))
        if text:
            page_html[since] = text
        else:
            log.warning("GitHub Trending 页面抓取失败: %s", since)

    # 2) 解析页面，建立候选池
    candidates: dict[str, dict] = {}
    for period_key, cfg in PERIODS.items():
        html_text = page_html.get(cfg["since"])
        if not html_text:
            continue
        for repo in parse_trending(html_text, period_key):
            name = repo["full_name"]
            cur = candidates.get(name)
            if cur is None:
                cur = _build_candidate({**repo, "_since": cfg["since"]})
                candidates[name] = cur
            else:
                cur["page_deltas"][cfg["since"]] = max(
                    cur["page_deltas"].get(cfg["since"], 0), repo.get("page_delta", 0)
                )
                cur["stars"] = max(cur["stars"], repo.get("stars", 0))
                cur["forks"] = max(cur["forks"], repo.get("forks", 0))
                if not cur.get("description") and repo.get("description"):
                    cur["description"] = repo["description"]
            if period_key not in cur["appears_in"]:
                cur["appears_in"].append(period_key)

    # 3) 用 Search API 补充「窗口期内新建」的仓库
    for days in (3, 7, 30):
        for repo in fetch_new_repos(now, days):
            name = repo["full_name"]
            if not name:
                continue
            cur = candidates.get(name)
            if cur is None:
                cur = _build_candidate(repo)
                cur["age_days"] = repo.get("age_days")
                cur["topics"] = repo.get("topics", [])
                candidates[name] = cur
            else:
                cur["age_days"] = repo.get("age_days", cur.get("age_days"))
                cur["created_at"] = repo.get("created_at", cur.get("created_at"))
                cur["topics"] = repo.get("topics", cur.get("topics", []))
                cur["stars"] = max(cur["stars"], repo.get("stars", 0))

    log.info("GitHub 候选仓库 %d 个", len(candidates))

    # 4) 保存今日快照，供后续日期对老项目做真实差分
    save_snapshot(
        snapshot_path(data_dir, now),
        {name: repo["stars"] for name, repo in candidates.items()},
        now,
    )

    # 5) 逐档计算增量并排序
    result: dict[str, list[dict]] = {}
    for period_key, cfg in PERIODS.items():
        days = cfg["days"]
        past = _find_past_snapshot(data_dir, now, days) if days > 1 else None

        for repo in candidates.values():
            page_delta = repo.get("page_deltas", {}).get(cfg["since"], 0)
            age = repo.get("age_days")

            if past is not None and repo["full_name"] in past:
                delta = repo["stars"] - int(past[repo["full_name"]])
                source = "snapshot"
            elif age is not None and age <= days and repo["stars"] > 0:
                # 窗口期内新建：窗口开始时星数为 0，当前星数即真实增量
                delta = repo["stars"]
                source = "new_repo"
            elif page_delta and period_key == "three_day":
                # 三日档无官方数据，按周增量日均外推，并明确标注为估算
                delta = int(round(page_delta * 3 / 7))
                source = "estimate"
            elif page_delta:
                delta = page_delta
                source = "page"
            else:
                delta = 0
                source = "none"

            repo.setdefault("deltas", {})[period_key] = max(delta, 0)
            repo.setdefault("delta_sources", {})[period_key] = source

        ranked = sorted(
            candidates.values(),
            key=lambda r: (r["deltas"][period_key], r["stars"]),
            reverse=True,
        )
        result[period_key] = [_present(r, period_key, days) for r in ranked[:PER_PAGE_N]]

    result["_meta"] = {
        "snapshot_date": now.date().isoformat(),
        "candidate_count": len(candidates),
        "sources_used": sorted(
            {r.get("delta_source") for lst in result.values() for r in lst if lst}
        ),
    }
    return result


def _present(repo: dict, period_key: str, days: int) -> dict:
    """把内部候选对象转成前端展示所需的结构。"""
    delta = repo.get("deltas", {}).get(period_key, 0)
    source = repo.get("delta_sources", {}).get(period_key, "page")
    stars = repo.get("stars", 0)
    return {
        "full_name": repo["full_name"],
        "owner": repo["owner"],
        "name": repo["name"],
        "url": repo["url"],
        "description": repo.get("description", ""),
        "language": repo.get("language", ""),
        "stars": stars,
        "forks": repo.get("forks", 0),
        "delta": delta,
        "delta_label": PERIODS[period_key]["label"],
        "delta_days": days,
        "delta_source": source,
        "builders": repo.get("builders", []),
        "topics": repo.get("topics", [])[:5],
        "age_days": repo.get("age_days"),
        "is_new": bool(
            repo.get("age_days") is not None and repo.get("age_days") <= days
        ),
        "daily_rate": round(delta / days, 1) if days else delta,
    }
