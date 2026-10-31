"""RSS 2.0 / Atom 通用解析器（标准库实现，无第三方依赖）。

输出统一的条目结构：
    {
        "title": str,
        "link": str,
        "summary": str,     # 去标签后的纯文本
        "published": datetime | None,   # 已统一为 UTC 时间
        "author": str,
    }
"""

from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

# RSS 2.0 / Atom 命名空间
NS = {
    "content": "http://purl.org/rss/1.0/modules/content/",
    "dc": "http://purl.org/dc/elements/1.1/",
    "atom": "http://www.w3.org/2005/Atom",
}

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def strip_html(raw: str | None, limit: int = 400) -> str:
    """去掉 HTML 标签、反转义实体，并按长度截断。"""
    if not raw:
        return ""
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw)
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    text = _WS_RE.sub(" ", text).strip()
    if len(text) > limit:
        text = text[:limit].rstrip() + "…"
    return text


def _localname(tag: str) -> str:
    """去掉 XML 命名空间前缀。"""
    return tag.split("}", 1)[-1].lower() if "}" in tag else tag.lower()


def parse_datetime(raw: str | None) -> datetime | None:
    """解析 RSS 的 RFC822 日期或 Atom 的 ISO8601 日期，统一返回 UTC。

    Args:
        raw: 原始日期字符串。

    Returns:
        UTC datetime；解析失败或无输入时返回 None。
    """
    if not raw:
        return None
    raw = raw.strip()
    try:
        dt = parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (TypeError, ValueError, IndexError):
        pass

    iso = raw.replace("Z", "+00:00")
    iso = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", iso)
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        try:
            dt = datetime.strptime(raw[:19], "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _first_text(node: ET.Element, *names: str) -> str:
    """按候选标签名取第一个非空文本。"""
    want = {n.lower() for n in names}
    for child in node:
        if _localname(child.tag) in want:
            text = "".join(child.itertext()).strip()
            if text:
                return text
    return ""


def _find_link(node: ET.Element) -> str:
    """提取条目链接：优先 <link> 文本，其次 <link href>，最后 guid。"""
    for child in node:
        if _localname(child.tag) != "link":
            continue
        href = (child.get("href") or "").strip()
        text = "".join(child.itertext()).strip()
        if text:
            return text
        if href:
            return href
    return ""


def parse_feed(xml_text: str) -> list[dict]:
    """解析 RSS 2.0 或 Atom 源文本。

    Args:
        xml_text: 源 XML 文本。

    Returns:
        条目字典列表；XML 损坏时返回空列表。
    """
    if not xml_text or not xml_text.strip():
        return []
    try:
        root = ET.fromstring(xml_text.strip())
    except ET.ParseError:
        # 部分源带 BOM 或前导空白，尝试容错解析
        try:
            root = ET.fromstring(xml_text.strip().lstrip("﻿").encode("utf-8", "ignore"))
        except ET.ParseError:
            return []

    items: list[dict] = []
    if _localname(root.tag) == "feed":  # Atom
        for entry in root:
            if _localname(entry.tag) != "entry":
                continue
            items.append(
                {
                    "title": strip_html(_first_text(entry, "title"), 200),
                    "link": _find_link(entry),
                    "summary": strip_html(
                        _first_text(entry, "summary", "content", "description"), 400
                    ),
                    "published": parse_datetime(_first_text(entry, "published", "updated")),
                    "author": strip_html(_first_text(entry, "name", "author"), 60),
                }
            )
        return items

    # RSS 2.0 / RDF
    for item in root.iter():
        if _localname(item.tag) not in {"item", "entry"}:
            continue
        summary = _first_text(
            item, "description", "{http://purl.org/rss/1.0/modules/content/}encoded", "summary"
        )
        items.append(
            {
                "title": strip_html(_first_text(item, "title"), 200),
                "link": _find_link(item) or strip_html(_first_text(item, "guid"), 300),
                "summary": strip_html(summary, 400),
                "published": parse_datetime(
                    _first_text(
                        item, "pubDate", "{http://purl.org/dc/elements/1.1/}date", "published"
                    )
                ),
                "author": strip_html(_first_text(item, "author", "creator", "name"), 60),
            }
        )
    return items


def utcnow() -> datetime:
    """当前 UTC 时间（便于测试与统一时区口径）。"""
    return datetime.now(timezone.utc)


def age_hours(published: datetime | None, now: datetime | None = None) -> float:
    """条目距今小时数；无发布时间时返回一个较大的保守值。"""
    now = now or utcnow()
    if not published:
        return 999.0
    delta: timedelta = now - published
    return max(delta.total_seconds() / 3600.0, 0.0)
