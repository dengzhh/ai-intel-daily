#!/usr/bin/env python3
"""AI 情报站 · 生成发布副本并推送到 GitHub Pages。

流程：
  1. 调 publish_build.py 重新生成 ./ai-intel-public/
  2. 把产物同步到一个独立的 git worktree（分支 gh-pages）
  3. 有差异才 commit + push，没差异直接跳过（幂等，可反复执行）

为什么用 gh-pages 分支而不是 main 分支的 /docs：
  仓库 main 里是采集源码，Pages 只需要静态产物；分开发布分支后
  main 保持干净，也不会把每日 JSON 混进源码历史。

前置条件：
  - 已配置 git 用户（user.name / user.email）
  - remote origin 指向 GitHub 仓库，且当前分支能 push
  - GitHub 仓库 Settings → Pages → Source 选 "Deploy from a branch" → gh-pages / (root)

用法:
    python deploy_pages.py                  # 构建并推送
    python deploy_pages.py --dry-run        # 只构建，不 commit/push
    python deploy_pages.py --keep-days 365  # 指定归档天数
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PUBLIC_DIR = ROOT / "ai-intel-public"
WORKTREE = ROOT / ".deploy-worktree"
BRANCH = "gh-pages"

# 不参与同步的残留文件（工具生成物、系统垃圾）
SKIP_NAMES = {".git", ".DS_Store", "Thumbs.db", "__pycache__"}


def run(cmd: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    """执行命令并回显。check=False 时允许非零退出。"""
    proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and proc.returncode != 0:
        sys.stderr.write(f"[失败] {' '.join(cmd)}\n{proc.stdout}\n{proc.stderr}\n")
        raise SystemExit(proc.returncode)
    return proc


def build(keep_days: int) -> None:
    """第 1 步：生成静态发布副本。"""
    print("[1/3] 生成发布副本 ...")
    run([sys.executable, str(ROOT / "publish_build.py"), "--keep-days", str(keep_days)], cwd=ROOT)
    if not (PUBLIC_DIR / "index.html").exists():
        raise SystemExit(f"[失败] 发布副本缺失：{PUBLIC_DIR / 'index.html'}")


def ensure_worktree() -> Path:
    """第 2 步：准备 gh-pages 分支的独立工作树。"""
    if WORKTREE.exists() and (WORKTREE / ".git").exists():
        run(["git", "fetch", "origin", BRANCH], cwd=WORKTREE, check=False)
        run(["git", "reset", "--hard", f"origin/{BRANCH}"], cwd=WORKTREE, check=False)
        return WORKTREE

    if WORKTREE.exists():
        shutil.rmtree(WORKTREE)

    # 首次：远端可能还没有 gh-pages，先拉一次
    run(["git", "fetch", "origin", BRANCH], cwd=ROOT, check=False)
    probe = run(["git", "rev-parse", "--verify", f"origin/{BRANCH}"], cwd=ROOT, check=False)
    if probe.returncode == 0:
        run(["git", "worktree", "add", str(WORKTREE), BRANCH], cwd=ROOT)
        run(["git", "reset", "--hard", f"origin/{BRANCH}"], cwd=WORKTREE)
    else:
        # 远端无此分支：建一个孤儿分支
        print(f"  远端还没有 {BRANCH}，创建孤立分支 ...")
        run(["git", "worktree", "add", "--detach", str(WORKTREE)], cwd=ROOT)
        run(["git", "checkout", "--orphan", BRANCH], cwd=WORKTREE)
        run(["git", "rm", "-rf", "--cached", "."], cwd=WORKTREE, check=False)
    return WORKTREE


def sync_public(dest: Path) -> None:
    """把发布副本内容同步到工作树（先清干净，避免删除的文件残留）。"""
    for child in dest.iterdir():
        if child.name in SKIP_NAMES:
            continue
        shutil.rmtree(child) if child.is_dir() else child.unlink()

    for child in PUBLIC_DIR.iterdir():
        if child.name in SKIP_NAMES:
            continue
        target = dest / child.name
        if child.is_dir():
            shutil.copytree(child, target)
        else:
            shutil.copy2(child, target)


def commit_and_push(dest: Path, dry_run: bool) -> bool:
    """第 3 步：有差异才提交并推送，返回是否真的推送了。"""
    run(["git", "add", "-A"], cwd=dest)
    status = run(["git", "status", "--porcelain"], cwd=dest).stdout.strip()
    if not status:
        print("[3/3] 无变更，跳过提交")
        return False

    changed = len([line for line in status.splitlines() if line.strip()])
    print(f"[3/3] 检测到 {changed} 处变更")

    if dry_run:
        print("  --dry-run：不提交不推送")
        return False

    stamp = run(["git", "log", "-1", "--format=%cd", "--date=format:%Y-%m-%d %H:%M"], cwd=ROOT, check=False)
    latest = PUBLIC_DIR / "data" / "latest.json"
    tag = ""
    if latest.exists():
        import json

        try:
            tag = json.loads(latest.read_text(encoding="utf-8")).get("date", "")
        except Exception:
            tag = ""
    msg = f"发布 {tag}".strip() if tag else "发布更新"
    run(["git", "commit", "-m", msg], cwd=dest)
    push = run(["git", "push", "origin", BRANCH], cwd=dest, check=False)
    if push.returncode != 0:
        sys.stderr.write(f"[失败] push 失败\n{push.stdout}\n{push.stderr}\n")
        raise SystemExit(push.returncode)
    print(f"  已推送：{msg}（{stamp.stdout.strip()}）")
    return True


def main() -> int:
    """命令行入口。"""
    parser = argparse.ArgumentParser(description="生成发布副本并推送到 GitHub Pages")
    parser.add_argument("--keep-days", type=int, default=365, help="历史归档保留天数，默认 365")
    parser.add_argument("--dry-run", action="store_true", help="只构建，不提交不推送")
    args = parser.parse_args()

    build(args.keep_days)
    dest = ensure_worktree()
    sync_public(dest)
    pushed = commit_and_push(dest, args.dry_run)
    print("完成" if pushed else "完成（无改动）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
