"""HTTP 抓取层。

仅使用标准库：自带 gzip / deflate 解压、浏览器 UA、超时、指数退避重试、
以及基于线程池的并发抓取。抓取失败只记录日志，不中断整个流程。
"""

from __future__ import annotations

import gzip
import io
import json
import logging
import random
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Iterable, Sequence

log = logging.getLogger("ai-intel.http")

DEFAULT_TIMEOUT = 25
DEFAULT_RETRIES = 2
DEFAULT_WORKERS = 8

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE


class FetchError(RuntimeError):
    """抓取失败。"""


def _decompress(body: bytes, encoding: str | None) -> bytes:
    """按 Content-Encoding 解压响应体。"""
    enc = (encoding or "").lower()
    try:
        if "gzip" in enc:
            return gzip.decompress(body)
        if "deflate" in enc:
            try:
                return zlib.decompress(body)
            except zlib.error:
                return zlib.decompress(body, -zlib.MAX_WBITS)
        if "br" in enc:
            # brotli 非标准库，服务端通常还接受 gzip，故不请求 br
            raise FetchError("brotli 响应无法解码")
    except FetchError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise FetchError(f"解压失败: {exc}") from exc
    return body


def fetch(
    url: str,
    *,
    timeout: int = DEFAULT_TIMEOUT,
    retries: int = DEFAULT_RETRIES,
    headers: dict[str, str] | None = None,
    accept: str = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
) -> str:
    """GET 一个 URL 并返回解码后的文本。

    Args:
        url: 目标地址。
        timeout: 单次请求超时秒数。
        retries: 额外重试次数（指数退避）。
        headers: 追加的请求头。
        accept: Accept 请求头内容。

    Returns:
        响应正文文本。

    Raises:
        FetchError: 重试耗尽后仍失败。
    """
    req_headers = {
        "User-Agent": UA,
        "Accept": accept,
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "close",
    }
    if headers:
        req_headers.update(headers)

    last_err: Exception | None = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=req_headers, method="GET")
            with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as resp:
                raw = resp.read()
                text = _decompress(raw, resp.headers.get("Content-Encoding")).decode(
                    "utf-8", errors="replace"
                )
            return text
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            if attempt < retries:
                delay = 1.5 * (2**attempt) + random.uniform(0, 0.6)
                log.debug("重试 %s (%s): %s", url, attempt + 1, exc)
                time.sleep(delay)
    raise FetchError(f"{url} 抓取失败: {last_err}")


def fetch_json(url: str, **kwargs) -> dict | list:
    """GET 一个 URL 并按 JSON 解析。"""
    headers = dict(kwargs.pop("headers", {}) or {})
    headers.setdefault("Accept", "application/json")
    text = fetch(url, headers=headers, accept="application/json", **kwargs)
    return json.loads(text)


def fetch_many(
    tasks: Sequence[tuple[str, Callable[[str], object]]],
    *,
    workers: int = DEFAULT_WORKERS,
    timeout: int = DEFAULT_TIMEOUT,
    retries: int = DEFAULT_RETRIES,
    label: str = "fetch",
) -> list[object]:
    """并发抓取并解析多个 URL，返回结果顺序与 tasks 严格一致。

    Args:
        tasks: `(url, 解析函数)` 序列，解析函数接收文本返回任意对象。
        workers: 并发线程数。
        timeout: 单次请求超时秒数。
        retries: 额外重试次数。
        label: 日志前缀。

    Returns:
        与 tasks 等长的结果列表：成功项为解析结果，失败项为 None。
        保序是关键——调用方依赖索引把结果与源配置对应起来。
    """
    if not tasks:
        return []

    results: list[object] = [None] * len(tasks)
    with ThreadPoolExecutor(max_workers=min(workers, len(tasks))) as pool:
        futures = {
            pool.submit(fetch, url, timeout=timeout, retries=retries): (idx, url, parser)
            for idx, (url, parser) in enumerate(tasks)
        }
        for fut in as_completed(futures):
            idx, url, parser = futures[fut]
            try:
                results[idx] = parser(fut.result())
            except FetchError as exc:
                log.warning("[%s] 跳过不可达源 %s: %s", label, url, exc)
            except Exception as exc:  # noqa: BLE001
                log.warning("[%s] 解析失败 %s: %s", label, url, exc)
    return results


def safe_fetch(url: str, **kwargs) -> str | None:
    """抓取失败时返回 None 而非抛异常。"""
    try:
        return fetch(url, **kwargs)
    except FetchError as exc:
        log.warning("抓取失败: %s", exc)
        return None


def iter_chunks(items: Iterable, size: int):
    """将可迭代对象切成指定大小的批次。"""
    chunk: list = []
    for item in items:
        chunk.append(item)
        if len(chunk) >= size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


def quote_path(path: str) -> str:
    """对 URL 路径段做百分号编码（保留 /）。"""
    return urllib.parse.quote(path, safe="/")
