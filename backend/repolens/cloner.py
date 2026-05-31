"""仓库克隆器 — 克隆 GitHub 仓库或验证本地路径。

设计：同步 git 操作放到线程中执行（使用 subprocess.run + asyncio.to_thread）。
不依赖 GitPython — 直接使用 subprocess 实现。
Windows 兼容：避免依赖 asyncio 子进程支持，可在 ProactorEventLoop 下正常运行。
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
from pathlib import Path

from .config import config


class CloneError(Exception):
    """克隆或路径校验失败时抛出。"""


class RepoCloner:
    """克隆 GitHub 仓库或验证本地目录路径。"""

    def __init__(self) -> None:
        self._cloned_path: str | None = None

    async def clone(self, repo_url: str, job_id: str) -> str:
        """克隆仓库，返回本地文件系统路径。

        对于 GitHub URL，执行完整克隆到临时目录。
        对于本地路径，验证目录存在并可读。
        """
        if repo_url.startswith(("http://", "https://")):
            return await self._clone_github(repo_url, job_id)
        return await self._validate_local(repo_url)

    async def cleanup(self) -> None:
        """清理：移除克隆目录（仅远程克隆时生效）。"""
        if self._cloned_path and os.path.isdir(self._cloned_path):
            await asyncio.to_thread(
                shutil.rmtree, self._cloned_path, ignore_errors=True
            )
            self._cloned_path = None

    # ------------------------------------------------------------------
    # 内部实现
    # ------------------------------------------------------------------

    async def _clone_github(self, url: str, job_id: str) -> str:
        """克隆 GitHub 仓库到临时目录。

        使用 subprocess.run 在线程中同步执行，避免依赖
        asyncio 的子进程支持（Windows ProactorEventLoop 不兼容）。

        不使用 --depth 浅克隆，保证 GitAnalyzer 可读取完整提交历史。
        --single-branch 减少克隆体积，只取默认分支。
        """
        target = os.path.join(config.tmp_dir, f"repo_{job_id[:12]}")
        os.makedirs(os.path.dirname(target), exist_ok=True)

        def _run() -> None:
            result = subprocess.run(
                ["git", "clone", "--single-branch", url, target],
                capture_output=True,
                timeout=config.clone_timeout_seconds,
            )
            if result.returncode != 0:
                err = result.stderr.decode("utf-8", errors="replace").strip()
                raise CloneError(f"git clone 失败: {err}")

        try:
            await asyncio.to_thread(_run)
        except subprocess.TimeoutExpired:
            raise CloneError(f"克隆超时 ({config.clone_timeout_seconds}s)")
        except CloneError:
            raise

        self._cloned_path = target
        return target

    async def _validate_local(self, path: str) -> str:
        """验证本地目录存在且可读。"""
        resolved = str(Path(path).resolve())
        if not os.path.isdir(resolved):
            raise CloneError(f"本地路径不存在或不是目录: {resolved}")
        # 防止路径遍历：拒绝访问系统关键目录
        dangerous = {"/etc", "/sys", "/proc", "/dev", "C:\\Windows", "C:\\Windows\\System32"}
        resolved_lower = resolved.lower()
        for d in dangerous:
            if resolved_lower.startswith(d.lower()):
                raise CloneError(f"拒绝分析系统目录: {resolved}")
        # 本地路径不执行清理 — 它们属于用户。
        return resolved
