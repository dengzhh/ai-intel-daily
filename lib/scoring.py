"""新闻价值打分与跨源去重。

打分模型（各分量归一化到 0~1 后加权求和）：

    score = 0.28 * 新鲜度
          + 0.17 * 来源权重
          + 0.27 * AI 相关度
          + 0.28 * 热度
          -        噪声惩罚

其中「热度」由标题热度词、跨源转载次数、社区互动量（Hacker News）合成。
"""

from __future__ import annotations

import math
import re
from datetime import datetime
from typing import Iterable

from .sources import AI_STRONG_KEYWORDS, AI_WEAK_KEYWORDS, HYPE_KEYWORDS, NOISE_KEYWORDS

W_FRESHNESS = 0.28
W_SOURCE = 0.17
W_RELEVANCE = 0.27
W_HEAT = 0.28

MAX_AGE_HOURS = 24.0

_TOKEN_RE = re.compile(r"[a-z0-9\u4e00-\u9fff]+")
_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "is", "are",
    "its", "it", "this", "that", "as", "at", "by", "from", "has", "have", "will", "can",
    "的", "了", "是", "在", "和", "与", "对", "为", "将", "把", "被", "中", "上", "如何",
}


def tokenize(text: str) -> set[str]:
    """将文本切分为去停用词的词元集合，用于相似度比较。"""
    if not text:
        return set()
    tokens = _TOKEN_RE.findall(text.lower())
    return {t for t in tokens if t not in _STOPWORDS and len(t) > 1}


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def freshness_score(age_hours: float | None) -> float:
    """新鲜度：24 小时内从 1.0 线性衰减到 0；超过 24 小时为 0。

    Args:
        age_hours: 条目距今小时数。

    Returns:
        0~1 的新鲜度分值。
    """
    if age_hours is None:
        return 0.15  # 无发布时间，给保守低分
    if age_hours < 0:
        age_hours = 0.0
    return _clamp(1.0 - (age_hours / MAX_AGE_HOURS) ** 0.85)


def relevance_score(title: str, summary: str) -> tuple[float, list[str]]:
    """AI 相关度：标题权重高于摘要，强信号权重高于弱信号。

    Args:
        title: 标题。
        summary: 摘要。

    Returns:
        `(分值, 命中的强信号词列表)`。
    """
    title_l = (title or "").lower()
    summary_l = (summary or "").lower()

    strong_hits: list[str] = []
    strong_raw = 0.0
    for kw in AI_STRONG_KEYWORDS:
        kw_l = kw.lower()
        hit_t = kw_l in title_l
        hit_s = kw_l in summary_l
        if hit_t:
            strong_raw += 1.0
            strong_hits.append(kw)
        elif hit_s:
            strong_raw += 0.45

    weak_raw = 0.0
    for kw in AI_WEAK_KEYWORDS:
        kw_l = kw.lower()
        if kw_l in title_l:
            weak_raw += 0.5
        elif kw_l in summary_l:
            weak_raw += 0.2

    # 强信号主导，弱信号只作为补充，避免泛词刷分
    raw = strong_raw + min(weak_raw, 2.0) * 0.4
    # 用饱和函数压缩，2 个强信号即接近满分
    score = 1.0 - math.exp(-raw / 1.6)
    return _clamp(score), strong_hits[:6]


def heat_score(
    title: str,
    *,
    dup_count: int = 1,
    points: int = 0,
    comments: int = 0,
) -> float:
    """热度：标题热度词 + 跨源转载 + 社区互动。

    Args:
        title: 标题。
        dup_count: 同一事件被多少个源报道（1 表示仅一个源）。
        points: Hacker News 点赞数（无则 0）。
        comments: Hacker News 评论数（无则 0）。

    Returns:
        0~1 的热度分值。
    """
    title_l = (title or "").lower()
    hype_hits = sum(1 for kw in HYPE_KEYWORDS if kw.lower() in title_l)
    hype_score = _clamp(hype_hits / 3.0)

    # 跨源转载：第 2 个源即显著加分，之后边际递减
    dup_score = 0.0 if dup_count <= 1 else _clamp(0.45 + 0.2 * math.log(dup_count - 1, 2))

    # 社区互动：点赞 200 / 评论 100 视为饱和
    community = _clamp(points / 200.0) * 0.6 + _clamp(comments / 100.0) * 0.4

    score = 0.40 * hype_score + 0.30 * dup_score + 0.30 * community
    return _clamp(score)


def noise_penalty(title: str, summary: str) -> float:
    """噪声惩罚：命中营销/水文关键词时扣分。"""
    text = f"{title or ''} {summary or ''}".lower()
    hits = sum(1 for kw in NOISE_KEYWORDS if kw.lower() in text)
    return min(hits, 3) * 0.12


def total_score(item: dict) -> float:
    """按权重合成总分。"""
    return max(
        0.0,
        W_FRESHNESS * item.get("freshness", 0.0)
        + W_SOURCE * item.get("source_weight", 0.0)
        + W_RELEVANCE * item.get("relevance", 0.0)
        + W_HEAT * item.get("heat", 0.0)
        - item.get("noise", 0.0),
    )


def jaccard(a: set[str], b: set[str]) -> float:
    """两个词元集合的 Jaccard 相似度。"""
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def containment(a: set[str], b: set[str]) -> float:
    """较小集合被较大集合覆盖的比例（对长度差异大的标题更稳健）。"""
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def same_event(
    a: set[str],
    b: set[str],
    threshold: float = 0.62,
    coverage: float = 0.5,
) -> bool:
    """判断两组标题词元是否描述同一事件。

    仅用 Jaccard 会漏判「同一事件、不同措辞」的情况：媒体在标题里
    增删修饰语（launches / announces / significant leap）会让 Jaccard
    掉到 0.3 左右，即便两者共享全部专有名词。因此复合判定：
    Jaccard 达标，或「较小集合覆盖率达标且共有词不少于 3 个」。

    覆盖率阈值低于 Jaccard 阈值是刻意的：实测同事件标题覆盖率多在
    0.5~0.65，不同事件普遍低于 0.2，两者区间可分；而要求共有词
    ≥3 个可避免「同公司、同泛词」的假合并。

    Args:
        a: 标题 A 的词元集合。
        b: 标题 B 的词元集合。
        threshold: Jaccard 判定阈值。
        coverage: 覆盖率判定阈值。

    Returns:
        是否视为同一事件。
    """
    if jaccard(a, b) >= threshold:
        return True
    return len(a & b) >= 3 and containment(a, b) >= coverage


def deduplicate(items: list[dict], threshold: float = 0.62) -> list[dict]:
    """跨源去重并统计转载次数。

    标题词元 Jaccard 相似度超过阈值的条目被视为同一事件，
    保留分数最高者作为代表，其余作为 `related` 附在其上，
    并把 `dup_count` 记为报道该事件的源数量。

    Args:
        items: 已打分的条目列表。
        threshold: 判定为同一事件的相似度阈值。

    Returns:
        去重后的条目列表（按当前顺序）。
    """
    clusters: list[dict] = []
    for item in items:
        toks = item.get("_tokens") or tokenize(item.get("title", ""))
        matched = None
        for cluster in clusters:
            if same_event(toks, cluster["_tokens"], threshold):
                matched = cluster
                break
        if matched is None:
            item["_tokens"] = toks
            item.setdefault("related", [])
            item.setdefault("dup_count", 1)
            clusters.append(item)
            continue
        matched.setdefault("related", []).append(
            {
                "source": item.get("source"),
                "title": item.get("title"),
                "url": item.get("url"),
            }
        )
        seen_sources = {r.get("source") for r in matched.get("related", [])}
        seen_sources.add(matched.get("source"))
        seen_sources.add(item.get("source"))
        matched["dup_count"] = len(seen_sources)
    return clusters


def rank(
    items: Iterable[dict],
    top_n: int = 12,
    *,
    max_per_source: int = 3,
) -> list[dict]:
    """计算总分、按分值降序排序并截取前 N 条，同时对单一来源设置名额上限。

    纯全局排序下，新鲜度和权重双高的源（如更新频繁的 InfoQ 中国）
    可能独占半数名额，使版面失去来源多样性。因此先按分数排序，
    再以「每源最多 max_per_source 条」做一轮筛选；若因此凑不满 N 条，
    把被挤下的高分条目按分数顺序回填，确保结果始终是 N 条。

    Args:
        items: 去重后的条目列表（需含各打分分量）。
        top_n: 需要返回的条数。
        max_per_source: 单一来源最多占用的名额。

    Returns:
        排好序的条目列表，每条附带 `score` 与 `rank`。
    """
    ranked = sorted(items, key=total_score, reverse=True)
    for item in ranked:
        item["score"] = round(total_score(item), 4)

    picked: list[dict] = []
    deferred: list[dict] = []
    quota: dict[str, int] = {}
    for item in ranked:
        if len(picked) >= top_n:
            break
        src = item.get("source", "")
        if quota.get(src, 0) < max_per_source:
            picked.append(item)
            quota[src] = quota.get(src, 0) + 1
        else:
            deferred.append(item)

    # 名额回填：来源不足时用被挤下的高分条目补齐，保证足量
    if len(picked) < top_n:
        picked.extend(deferred[: top_n - len(picked)])
        picked.sort(key=lambda i: i["score"], reverse=True)

    for idx, item in enumerate(picked, start=1):
        item["rank"] = idx
    return picked


def summarize_scores(item: dict) -> str:
    """生成供调试/展示用的评分明细字符串。"""
    return (
        f"fresh={item.get('freshness', 0):.2f} "
        f"src={item.get('source_weight', 0):.2f} "
        f"rel={item.get('relevance', 0):.2f} "
        f"heat={item.get('heat', 0):.2f} "
        f"noise=-{item.get('noise', 0):.2f}"
    )


def relative_time(published: datetime | None, now: datetime | None = None) -> str:
    """把发布时间转成「x 小时前」形式的中文相对时间。"""
    if not published:
        return "时间未知"
    now = now or datetime.now(published.tzinfo)
    hours = (now - published).total_seconds() / 3600.0
    if hours < 1:
        return f"{max(int(hours * 60), 1)} 分钟前"
    if hours < 24:
        return f"{int(hours)} 小时前"
    return f"{int(hours // 24)} 天前"
