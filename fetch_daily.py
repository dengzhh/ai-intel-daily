#!/usr/bin/env python3
"""AI 情报站 · 每日数据采集入口。

抓取 24 小时内各大科技媒体的 AI 消息（选出最有价值的 12 条），
以及 GitHub Trending 三日 / 一周 / 一月星数增长最快的各 12 个开源项目，
结果写入 `data/latest.json` 与 `data/daily/<日期>.json`。

用法:
    python fetch_daily.py                 # 采集当天数据
    python fetch_daily.py --date 2026-10-28
    python fetch_daily.py --no-github     # 只采新闻
    python fetch_daily.py --dry-run       # 只打印统计，不写文件
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from lib import feeds, github, news  # noqa: E402

DATA_DIR = ROOT / "data"
DAILY_DIR = DATA_DIR / "daily"
LATEST_FILE = DATA_DIR / "latest.json"
KEEP_DAYS = 365

CST = timezone(timedelta(hours=8))


def setup_logging(verbose: bool = False) -> None:
    """配置日志格式与级别。"""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(name)-16s | %(message)s",
        datefmt="%H:%M:%S",
    )
    # 屏蔽 urllib3 之外的噪声
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def prune_history(keep_days: int = KEEP_DAYS) -> int:
    """删除超过保留天数的历史日报文件。

    Args:
        keep_days: 保留最近多少天。

    Returns:
        被删除的文件数。
    """
    if not DAILY_DIR.exists():
        return 0
    files = sorted(DAILY_DIR.glob("daily-*.json"))
    removed = 0
    for path in files[: max(len(files) - keep_days, 0)]:
        path.unlink(missing_ok=True)
        removed += 1
    if removed:
        logging.getLogger("ai-intel").info("清理历史日报 %d 份（保留最近 %d 天）", removed, keep_days)
    return removed


def build_payload(collect_github: bool = True, now: datetime | None = None) -> dict:
    """执行一次完整采集，返回待序列化的数据字典。

    Args:
        collect_github: 是否采集 GitHub 榜单。
        now: 基准时间（默认当前 UTC）。

    Returns:
        含 `news`、`github`、`meta` 的数据字典。
    """
    log = logging.getLogger("ai-intel")
    now = now or feeds.utcnow()

    log.info("=" * 64)
    log.info("开始采集 · 北京时间 %s", now.astimezone(CST).strftime("%Y-%m-%d %H:%M:%S"))

    news_data = news.build_news(now=now, top_n=12)
    github_data = github.build_github(DATA_DIR, now=now) if collect_github else {}

    payload = {
        "generated_at": now.isoformat(),
        "generated_at_cst": now.astimezone(CST).strftime("%Y-%m-%d %H:%M:%S"),
        "date": now.astimezone(CST).date().isoformat(),
        "news": news_data.get("items", []),
        "news_stats": news_data.get("stats", {}),
        "news_sources": news_data.get("sources", []),
        "github": {k: v for k, v in github_data.items() if not k.startswith("_")},
        "github_meta": github_data.get("_meta", {}),
        "meta": {
            "version": "1.0",
            "news_window_hours": 24,
            "news_top_n": 12,
            "github_top_n": 12,
            "scoring": {
                "freshness": 0.28,
                "source": 0.17,
                "relevance": 0.27,
                "heat": 0.28,
            },
        },
    }
    log.info("=" * 64)
    log.info(
        "采集完成：新闻 %d 条，GitHub 三档各 %s 个",
        len(payload["news"]),
        [len(v) for k, v in payload["github"].items()],
    )
    return payload


def main() -> int:
    """命令行入口。"""
    parser = argparse.ArgumentParser(description="AI 情报站每日数据采集")
    parser.add_argument("--date", help="指定采集日期（YYYY-MM-DD），默认今天")
    parser.add_argument("--no-github", action="store_true", help="跳过 GitHub 榜单采集")
    parser.add_argument("--dry-run", action="store_true", help="只打印结果，不写文件")
    parser.add_argument("-v", "--verbose", action="store_true", help="输出调试日志")
    args = parser.parse_args()

    setup_logging(args.verbose)

    if args.date:
        try:
            target = datetime.strptime(args.date, "%Y-%m-%d").replace(
                hour=1, minute=30, tzinfo=CST
            )
        except ValueError:
            print(f"日期格式错误：{args.date}，应为 YYYY-MM-DD", file=sys.stderr)
            return 2
        now = target.astimezone(timezone.utc)
    else:
        now = None

    payload = build_payload(collect_github=not args.no_github, now=now)

    if args.dry_run:
        print(json.dumps(payload, ensure_ascii=False, indent=2)[:4000])
        return 0

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DAILY_DIR.mkdir(parents=True, exist_ok=True)

    day = payload["date"]
    daily_file = DAILY_DIR / f"daily-{day}.json"
    for path in (LATEST_FILE, daily_file):
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # 额外输出一份 JS 版本：以 file:// 直接打开 HTML 时 fetch 会被 CORS 拦截，
    # 此时前端会回退到用 <script> 加载这份数据。
    js_file = DATA_DIR / "latest.js"
    js_file.write_text(
        "window.__AI_INTEL_DATA__ = " + json.dumps(payload, ensure_ascii=False) + ";\n",
        encoding="utf-8",
    )

    print(f"\n已写入：{LATEST_FILE}")
    print(f"已写入：{daily_file}")
    print(f"已写入：{js_file}")
    print(
        f"新闻 {len(payload['news'])} 条 | "
        f"GitHub 三日 {len(payload['github'].get('three_day', []))} / "
        f"一周 {len(payload['github'].get('weekly', []))} / "
        f"一月 {len(payload['github'].get('monthly', []))}"
    )

    prune_history()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
