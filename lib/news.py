"""新闻采集编排：RSS / Hacker News / arXiv 三路汇总后统一打分选题。"""

from __future__ import annotations

import json
import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

from . import feeds, http, scoring, sources

log = logging.getLogger("ai-intel.news")

TOP_N = 12
WINDOW_HOURS = 24
MAX_PER_FEED = 60  # 单个源最多处理的条目数（按发布时间取最新）
MAX_PER_SOURCE_IN_TOP = 3  # 精选结果中单一来源最多占 3 席，避免版面被一家刷屏

_ARXIV_NS = {"atom": "http://www.w3.org/2005/Atom"}


def _mk_item(
    *,
    title: str,
    url: str,
    summary: str,
    published: datetime | None,
    source: str,
    lang: str,
    weight: float,
    points: int = 0,
    comments: int = 0,
    extra: dict | None = None,
) -> dict | None:
    """构造统一条目结构并计算除热度外的各项分值。"""
    title = (title or "").strip()
    url = (url or "").strip()
    if not title or not url or not url.startswith("http"):
        return None

    age = feeds.age_hours(published)
    if age > WINDOW_HOURS + 1:  # 留 1 小时容错，覆盖源端时间偏差
        return None

    relevance, keywords = scoring.relevance_score(title, summary)
    item = {
        "title": title,
        "url": url,
        "summary": (summary or "").strip(),
        "source": source,
        "lang": lang,
        "published": published,
        "published_iso": published.isoformat() if published else None,
        "age_hours": round(age, 2),
        "source_weight": round(weight, 3),
        "freshness": round(scoring.freshness_score(age), 4),
        "relevance": round(relevance, 4),
        "keywords": keywords,
        "noise": round(scoring.noise_penalty(title, summary), 4),
        "points": points,
        "comments": comments,
        "dup_count": 1,
        "related": [],
    }
    if extra:
        item.update(extra)
    return item


# ------------------------------------------------------------------ RSS -----
def collect_rss(now: datetime) -> dict:
    """并发抓取所有 RSS 源，产出原始条目列表与可用源清单。

    Returns:
        `{"items": [...], "ok_sources": [...]}`。
    """
    tasks = [(s["url"], feeds.parse_feed) for s in sources.RSS_SOURCES]
    parsed = http.fetch_many(tasks, label="rss", workers=len(tasks))

    # 部分官方博客的 RSS 是全量历史（如 OpenAI 有上千条），
    # 先按发布时间倒序再截断，避免无谓地处理早已过期的条目。
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)

    items: list[dict] = []
    ok_sources: list[str] = []
    for src, entries in zip(sources.RSS_SOURCES, parsed):
        if not entries:
            log.info("源无数据：%s", src["name"])
            continue
        ok_sources.append(src["name"])
        entries = sorted(
            entries, key=lambda e: e.get("published") or epoch, reverse=True
        )[:MAX_PER_FEED]
        for entry in entries:
            item = _mk_item(
                title=entry.get("title", ""),
                url=entry.get("link", ""),
                summary=entry.get("summary", ""),
                published=entry.get("published"),
                source=src["name"],
                lang=src["lang"],
                weight=src["weight"],
            )
            if item:
                items.append(item)
    log.info("RSS 可用源 %d/%d，原始条目 %d 条", len(ok_sources), len(sources.RSS_SOURCES), len(items))
    return {"items": items, "ok_sources": ok_sources}


# --------------------------------------------------------- Hacker News -----
def collect_hn(now: datetime) -> list[dict]:
    """抓取 Hacker News 近期高票 AI 相关故事。"""
    since_ts = int((now - timedelta(hours=WINDOW_HOURS)).timestamp())
    tasks = [
        (sources.build_hn_url(q, since_ts, sources.HN_MIN_POINTS), json.loads)
        for q in sources.HN_QUERIES
    ]

    seen: set[str] = set()
    items: list[dict] = []
    for payload in http.fetch_many(tasks, label="hn", workers=4):
        if not isinstance(payload, dict):
            continue
        for hit in payload.get("hits", []):
            title = (hit.get("title") or "").strip()
            url = hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}"
            if not title or url in seen:
                continue
            seen.add(url)
            published = feeds.parse_datetime(hit.get("created_at"))
            item = _mk_item(
                title=title,
                url=url,
                summary=f"Hacker News 讨论：{title}",
                published=published,
                source="Hacker News",
                lang="en",
                weight=0.88,
                points=hit.get("points") or 0,
                comments=hit.get("num_comments") or 0,
            )
            if item:
                items.append(item)
    log.info("Hacker News 条目 %d 条", len(items))
    return items


# ---------------------------------------------------------------- arXiv -----
def collect_arxiv(now: datetime) -> list[dict]:
    """抓取 arXiv 最新 AI 相关论文（作为深度技术补充，权重较低）。"""
    url = sources.build_arxiv_url(sources.ARXIV_CATEGORIES, sources.ARXIV_MAX_RESULTS)
    text = http.safe_fetch(url)
    if not text:
        log.info("arXiv 不可达，跳过")
        return []
    try:
        root = ET.fromstring(text.strip())
    except ET.ParseError:
        log.info("arXiv 返回非预期 XML，跳过")
        return []

    items: list[dict] = []
    for entry in root.findall("atom:entry", _ARXIV_NS):
        title = " ".join((entry.findtext("atom:title", "", _ARXIV_NS) or "").split())
        link = ""
        for ln in entry.findall("atom:link", _ARXIV_NS):
            if ln.get("rel") == "alternate":
                link = ln.get("href") or ""
        summary = " ".join((entry.findtext("atom:summary", "", _ARXIV_NS) or "").split())
        published = feeds.parse_datetime(entry.findtext("atom:published", "", _ARXIV_NS))
        if not title or not link:
            continue
        item = _mk_item(
            title=f"[论文] {title}",
            url=link,
            summary=feeds.strip_html(summary, 300),
            published=published,
            source="arXiv",
            lang="en",
            weight=0.62,
            extra={"is_paper": True},
        )
        if item:
            items.append(item)
    log.info("arXiv 论文 %d 条", len(items))
    return items


# ---------------------------------------------------------------- 汇总 -----
def build_news(now: datetime | None = None, top_n: int = TOP_N) -> dict:
    """采集全部来源 → 去重 → 打分 → 取前 N 条。

    Args:
        now: 基准时间（默认当前 UTC）。
        top_n: 需要挑选的条数。

    Returns:
        含 `items`（精选条目）与 `stats`（采集统计）的字典。
    """
    now = now or feeds.utcnow()

    raw: list[dict] = []
    rss = collect_rss(now)
    raw += rss["items"]
    hn = collect_hn(now)
    raw += hn
    papers = collect_arxiv(now)
    raw += papers

    # 实际采集到数据的源清单（含非 RSS 的两路），用于页面顶部展示覆盖广度
    source_names = list(rss["ok_sources"])
    if hn:
        source_names.append("Hacker News")
    if papers:
        source_names.append("arXiv")

    # 先按标题去重，再按跨源转载次数计算热度
    clustered = scoring.deduplicate(raw)
    for item in clustered:
        item["heat"] = round(
            scoring.heat_score(
                item.get("title", ""),
                dup_count=item.get("dup_count", 1),
                points=item.get("points", 0),
                comments=item.get("comments", 0),
            ),
            4,
        )

    selected = scoring.rank(clustered, top_n=top_n, max_per_source=MAX_PER_SOURCE_IN_TOP)

    # 序列化：datetime 不可直接进 JSON，先算好相对时间再移除该字段
    for item in selected:
        item.pop("_tokens", None)
        item["display_time"] = scoring.relative_time(item.get("published"), now)
        item.pop("published", None)
        for rel in item.get("related", []):
            rel.pop("_tokens", None)

    stats = {
        "raw_count": len(raw),
        "after_dedup": len(clustered),
        "selected": len(selected),
        "window_hours": WINDOW_HOURS,
        "source_total": len(source_names),
    }
    log.info(
        "选题完成：原始 %d → 去重 %d → 精选 %d（覆盖 %d 个源）",
        len(raw), len(clustered), len(selected), len(source_names),
    )
    return {"items": selected, "stats": stats, "sources": source_names}
