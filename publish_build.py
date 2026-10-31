#!/usr/bin/env python3
"""AI 情报站 · 生成线上发布副本。

把采集结果整理成纯静态站点，输出到 `../ai-intel-public/`。
该目录只含渲染所需的 html/css/js 与数据，不含 Python 采集代码，
用于发布到 WorkBuddy 在线站点。

之所以独立成一个目录而不是直接发布项目根：
宿主机安全策略会拦截「把含源码的本地目录整体上传」的动作，
而纯静态产物目录可以正常发布。

历史归档策略：
  为了让「日历查看历史」能翻到更早的日期，每日结果会被追加进
  `data/history/<YYYY-MM>.json`（按月一个文件，整体重新生成）。
  前端点开某个月时只请求那一个文件，避免一次性下载全部历史。

用法:
    python publish_build.py
    python publish_build.py --keep-days 365
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PUBLIC_DIR = ROOT.parent / "ai-intel-public"

STATIC_FILES = ("index.html", "styles.css", "app.js")

# 只保留前端渲染真正需要的字段，避免把评分内部字段一并公开
KEEP_TOP_LEVEL = ("date", "generated_at_cst", "news", "news_stats", "news_sources", "github", "github_meta")

# 历史归档里每条新闻只留展示所需字段（体积约为完整版的 1/4）
NEWS_KEEP = (
    "title", "url", "summary", "source", "lang", "published_iso",
    "keywords", "points", "comments", "dup_count", "score", "rank", "display_time",
)

# 历史归档里每个仓库只留展示所需字段
REPO_KEEP = (
    "full_name", "url", "description", "language", "stars", "forks",
    "delta", "delta_label", "delta_days", "delta_source", "is_new",
)

PERIODS = ("daily", "three_day", "weekly", "monthly")

# 需要加内容指纹的静态资源：站点未返回 Cache-Control/ETag，
# 浏览器只能用启发式缓存，改了 CSS 用户端仍是旧版（历史视图切「开源项目」曾因此显示旧布局）
VERSIONED_ASSETS = ("styles.css", "app.js")


def stamp_asset_versions() -> None:
    """给发布副本 index.html 里的 css/js 引用追加内容哈希。

    每次内容变动都会产生新 URL，浏览器不可能命中旧缓存；
    文件未变时哈希不变，缓存仍然有效。
    """
    import hashlib
    import re

    html_path = PUBLIC_DIR / "index.html"
    html = html_path.read_text(encoding="utf-8")
    changed = []

    for name in VERSIONED_ASSETS:
        asset = PUBLIC_DIR / name
        if not asset.exists():
            continue
        digest = hashlib.md5(asset.read_bytes()).hexdigest()[:8]
        # 先去掉已有指纹再重写，保证重复执行结果一致（幂等）
        pattern = re.compile(r'(?P<pre>["\'])' + re.escape(name) + r'(?:\?v=[0-9a-f]+)?(?P<post>["\'])')
        new_html, n = pattern.subn(lambda m: f"{m.group('pre')}{name}?v={digest}{m.group('post')}", html)
        if n:
            html = new_html
            changed.append(f"{name}?v={digest}")

    if changed:
        html_path.write_text(html, encoding="utf-8")
        print(f"  资源指纹：{', '.join(changed)}")


def slim_payload(data: dict, date: str) -> dict:
    """把一份完整日报裁剪成历史归档所需的最小结构。

    Args:
        data: 原始日报数据（与 latest.json 同构）。
        date: 该日报对应的日期（YYYY-MM-DD）。

    Returns:
        含 `date` / `generated_at_cst` / `news` / `github` 等字段的精简字典。
    """
    github = {
        key: [{k: r[k] for k in REPO_KEEP if k in r} for r in data.get("github", {}).get(key, [])]
        for key in PERIODS
    }
    return {
        "date": date,
        "generated_at_cst": data.get("generated_at_cst", ""),
        "news": [{k: it[k] for k in NEWS_KEEP if k in it} for it in data.get("news", [])],
        "news_stats": data.get("news_stats", {}),
        "news_sources": data.get("news_sources", []),
        "github": github,
        "github_meta": data.get("github_meta", {}),
    }


def load_history(keep_days: int) -> dict[str, dict]:
    """读取 `data/daily/` 下的全部日报，按日期索引。

    Args:
        keep_days: 只保留最近多少天的日报。

    Returns:
        `{日期: 精简后的日报}`，按日期升序。
    """
    daily_dir = ROOT / "data" / "daily"
    if not daily_dir.exists():
        return {}

    entries: dict[str, dict] = {}
    for path in sorted(daily_dir.glob("daily-*.json")):
        date = path.stem.replace("daily-", "", 1)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"跳过损坏的日报 {path.name}：{exc}", file=sys.stderr)
            continue
        entries[date] = slim_payload(raw, date)

    ordered = sorted(entries.items())[-keep_days:] if keep_days > 0 else sorted(entries.items())
    return dict(ordered)


def build_history(entries: dict[str, dict]) -> int:
    """按月分片写出历史归档与日历索引。

    Args:
        entries: `{日期: 精简日报}`。

    Returns:
        写出的月份文件数。
    """
    out_dir = PUBLIC_DIR / "data" / "history"
    out_dir.mkdir(parents=True, exist_ok=True)

    # 清掉旧分片，避免删掉日报后归档里还留着幽灵日期
    for stale in out_dir.glob("*.json"):
        stale.unlink(missing_ok=True)

    by_month: dict[str, dict[str, dict]] = defaultdict(dict)
    for date, payload in entries.items():
        by_month[date[:7]][date] = payload

    index_days = []
    for month in sorted(by_month):
        days = by_month[month]
        (out_dir / f"{month}.json").write_text(
            json.dumps(days, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        for date, payload in days.items():
            index_days.append({
                "date": date,
                "news": len(payload.get("news", [])),
                "repos": len(payload.get("github", {}).get("three_day", [])),
            })

    manifest = {
        "days": index_days,
        "months": sorted(by_month),
        "count": len(index_days),
    }
    (out_dir / "index.json").write_text(
        json.dumps(manifest, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    # file:// 兜底：同 latest.js 的思路
    (out_dir / "index.js").write_text(
        "window.__AI_INTEL_HISTORY__ = " + json.dumps(manifest, ensure_ascii=False) + ";\n",
        encoding="utf-8",
    )
    return len(by_month)


def build(keep_days: int = 365) -> int:
    """生成发布副本并打印摘要。

    Args:
        keep_days: 历史归档保留天数。

    Returns:
        进程退出码（0 成功，1 数据缺失）。
    """
    latest = ROOT / "data" / "latest.json"
    if not latest.exists():
        print(f"找不到采集结果：{latest}", file=sys.stderr)
        print("请先运行 python fetch_daily.py", file=sys.stderr)
        return 1

    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    for name in STATIC_FILES:
        (PUBLIC_DIR / name).write_bytes((ROOT / name).read_bytes())
    stamp_asset_versions()

    data = json.loads(latest.read_text(encoding="utf-8"))
    payload = {k: data[k] for k in KEEP_TOP_LEVEL if k in data}
    payload["github"] = {
        k: v for k, v in payload.get("github", {}).items() if not k.startswith("_")
    }

    out_dir = PUBLIC_DIR / "data"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "latest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    # file:// 直接打开时 fetch 受 CORS 限制，用这份 JS 兜底
    (out_dir / "latest.js").write_text(
        "window.__AI_INTEL_DATA__ = "
        + json.dumps(payload, ensure_ascii=False)
        + ";\n",
        encoding="utf-8",
    )

    entries = load_history(keep_days)
    # 当天一定在归档里，即使 data/daily 下还没有文件
    entries.setdefault(payload.get("date", ""), slim_payload(payload, payload.get("date", "")))
    months = build_history({d: p for d, p in entries.items() if d})

    news = payload.get("news", [])
    stats = payload.get("news_stats", {})
    print(f"发布副本已生成：{PUBLIC_DIR}")
    print(f"  新闻 {len(news)} 条 | 覆盖源 {stats.get('source_total', '—')} 个")
    for key in ("three_day", "weekly", "monthly"):
        print(f"  {key}: {len(payload.get('github', {}).get(key, []))} 个")
    print(f"  数据时间：{payload.get('generated_at_cst', '—')}")
    print(f"  历史归档：{len(entries)} 天 / {months} 个月")
    return 0


def main() -> int:
    """命令行入口。"""
    parser = argparse.ArgumentParser(description="生成 AI 情报站发布副本")
    parser.add_argument("--keep-days", type=int, default=365, help="历史归档保留天数，默认 365")
    args = parser.parse_args()
    return build(args.keep_days)


if __name__ == "__main__":
    raise SystemExit(main())
