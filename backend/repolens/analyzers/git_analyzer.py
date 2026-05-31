"""Git 活动分析器 — 通过子进程进行全面的 Git 历史分析。

产出 GitResult，包含：
- 总提交次数 (git rev-list --count)
- 按提交数排序的主要贡献者 (git shortlog)
- 频繁修改的文件 (git log --name-only --format=)
- 每周活动时间线（从 git log 解析）
- CI/CD 配置检测 (.github/workflows)

设计：
- 4 个独立的 git 子进程通过 asyncio.gather 并发运行。
  子进程使用 subprocess.run 在线程中执行，兼容 Windows ProactorEventLoop。
- 各自有独立的超时；单个失败不会导致整体崩溃。
- 输出完全确定性 — 无 LLM 调用。
- 对浅克隆仓库友好处理（rev-list 计数受克隆深度限制）。
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import subprocess
import time
from collections import Counter
from datetime import datetime
from typing import Any, Optional

from ..schemas import ActiveFile, Contributor, GitResult, WeeklyActivity

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

_GIT_TIMEOUT = 60       # 每个 git 子进程的超时（秒）
_LOOKBACK_DAYS = 90     # activity_over_time 回溯窗口
_MAX_ACTIVE_FILES = 50  # 最频繁变更文件数


# ---------------------------------------------------------------------------
# 分析器
# ---------------------------------------------------------------------------


class GitAnalyzer:
    """分析 Git 提交历史：活动、贡献者和 CI 配置。

    所有 git 命令通过 subprocess.run 在线程中运行，兼容 Windows 和所有 asyncio 事件循环。
    结果从解析的子进程输出在内存中组装。
    """

    def __init__(self) -> None:
        self._timeout = _GIT_TIMEOUT
        self._lookback = _LOOKBACK_DAYS

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    async def run(self, repo_path: str) -> GitResult:
        """对仓库执行完整的 Git 分析。

        参数:
            repo_path: 克隆仓库的绝对路径。

        返回:
            包含所有字段的 GitResult。
            失败时返回带有 error 字段的结果。
        """
        start = time.monotonic()

        try:
            # 快速检查：这是 Git 仓库吗？
            if not os.path.isdir(os.path.join(repo_path, ".git")):
                return GitResult(
                    duration_ms=int((time.monotonic() - start) * 1000),
                    error=f"不是 Git 仓库（{repo_path}/.git 不存在）",
                )

            # 检查是否是浅克隆（--depth 1 创建的），如果是则尝试 deepen
            shallow = await self._check_shallow(repo_path)
            if shallow:
                logger.info(
                    "检测到浅克隆仓库，尝试 deepen: %s", repo_path,
                )
                unshallow_ok = await self._unshallow(repo_path)
                if not unshallow_ok:
                    logger.warning(
                        "仓库 deepen 失败，部分 Git 指标可能不准确: %s", repo_path,
                    )

            # 阶段 1：并行启动所有子进程
            results = await asyncio.gather(
                self._run_rev_count(repo_path),          # 总提交数
                self._run_shortlog(repo_path),            # 贡献者
                self._run_log_timeline(repo_path),        # 提交日期 + 哈希
                self._run_file_freq(repo_path),           # 频繁变更文件
                self._check_ci(repo_path),                # CI/CD 检测
                return_exceptions=True,
            )

            total_commits, contributors, log_raw, file_freq, ci_cd = results

            # 从 gather 结果中过滤异常
            if isinstance(log_raw, BaseException):
                log_raw = None
            if isinstance(file_freq, BaseException):
                file_freq = []
            if isinstance(contributors, BaseException):
                contributors = []
            if isinstance(total_commits, BaseException):
                total_commits = None
            if isinstance(ci_cd, BaseException):
                ci_cd = False

            # 阶段 2：从日志输出解析时间线
            tl: Any = self._parse_timeline(log_raw)

            # 阶段 3：组装结果
            return GitResult(
                total_commits=self._safe_int(total_commits),
                commits_per_week=float(tl["commits_per_week"]),
                unique_contributors=(
                    len(contributors) if isinstance(contributors, list) else 0
                ),
                active_days=int(tl["active_days"]),
                top_contributors=(  # type: ignore[arg-type]
                    contributors if isinstance(contributors, list) else []
                )[:10],
                active_files=(  # type: ignore[arg-type]
                    file_freq if isinstance(file_freq, list) else []
                )[:_MAX_ACTIVE_FILES],
                activity_over_time=tl["activity_over_time"],  # type: ignore[arg-type]
                ci_cd_config=self._safe_bool(ci_cd),
                duration_ms=int((time.monotonic() - start) * 1000),
            )

        except Exception as exc:
            logger.exception("GitAnalyzer.run 失败")
            return GitResult(
                duration_ms=int((time.monotonic() - start) * 1000),
                error=f"Git 分析失败: {exc}",
            )

    # ------------------------------------------------------------------
    # 子进程运行器（使用 subprocess.run 在线程中执行，各自处理错误）
    # ------------------------------------------------------------------

    async def _run_rev_count(self, repo_path: str) -> Optional[int]:
        """获取非合并提交总数：git rev-list --count HEAD。"""
        try:
            def _run() -> int:
                result = subprocess.run(
                    ["git", "-C", repo_path, "rev-list", "--count", "--no-merges", "HEAD"],
                    capture_output=True, timeout=self._timeout,
                )
                if result.returncode != 0:
                    raise subprocess.CalledProcessError(
                        result.returncode,
                        result.args,
                        output=result.stdout,
                        stderr=result.stderr,
                    )
                text = result.stdout.decode("utf-8", errors="replace").strip()
                return int(text) if text else 0

            return await asyncio.to_thread(_run)
        except subprocess.TimeoutExpired:
            logger.warning("git rev-list 超时 (%ds)", self._timeout)
            return None
        except subprocess.CalledProcessError as exc:
            stderr_text = exc.stderr.decode(errors="replace") if exc.stderr else ""
            logger.warning("git rev-list 失败 (rc=%d): %s", exc.returncode, stderr_text.strip())
            return None
        except (ValueError, FileNotFoundError) as exc:
            logger.warning("git rev-list 错误: %s", exc)
            return None

    async def _run_shortlog(self, repo_path: str) -> list[Contributor]:
        """获取按提交数排序的贡献者：git shortlog -sne HEAD。"""
        try:
            def _run() -> str:
                result = subprocess.run(
                    ["git", "-C", repo_path, "shortlog", "-sne", "HEAD"],
                    capture_output=True, timeout=self._timeout,
                )
                if result.returncode != 0:
                    stderr_text = result.stderr.decode(errors="replace").strip()
                    raise subprocess.CalledProcessError(
                        result.returncode, result.args,
                        output=result.stdout, stderr=result.stderr,
                    )
                return result.stdout.decode("utf-8", errors="replace")

            raw = await asyncio.to_thread(_run)
            return self._parse_shortlog(raw)
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            logger.warning("git shortlog 错误: %s", exc)
            return []
        except subprocess.CalledProcessError as exc:
            stderr_text = exc.stderr.decode(errors="replace") if exc.stderr else ""
            logger.warning("git shortlog 失败 (rc=%d): %s", exc.returncode, stderr_text.strip())
            return []

    async def _run_log_timeline(self, repo_path: str) -> Optional[str]:
        """获取完整提交时间线：git log 含哈希、邮箱、日期。

        格式：<hash>|<email>|<ISO date>
        """
        try:
            def _run() -> str:
                result = subprocess.run(
                    ["git", "-C", repo_path, "log",
                     "--format=%H|%ae|%ci", "--no-merges"],
                    capture_output=True, timeout=self._timeout,
                )
                if result.returncode != 0:
                    stderr_text = result.stderr.decode(errors="replace").strip()
                    raise subprocess.CalledProcessError(
                        result.returncode, result.args,
                        output=result.stdout, stderr=result.stderr,
                    )
                return result.stdout.decode("utf-8", errors="replace")

            return await asyncio.to_thread(_run)
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            logger.warning("git log 时间线 错误: %s", exc)
            return None
        except subprocess.CalledProcessError as exc:
            stderr_text = exc.stderr.decode(errors="replace") if exc.stderr else ""
            logger.warning("git log (时间线) 失败 (rc=%d): %s", exc.returncode, stderr_text.strip())
            return None

    async def _run_file_freq(self, repo_path: str) -> list[ActiveFile]:
        """获取频繁变更文件：git log --name-only --format=。"""
        try:
            def _run() -> str:
                result = subprocess.run(
                    ["git", "-C", repo_path, "log",
                     "--name-only", "--format=", "--no-merges", "--no-renames"],
                    capture_output=True, timeout=self._timeout,
                )
                if result.returncode != 0:
                    stderr_text = result.stderr.decode(errors="replace").strip()
                    raise subprocess.CalledProcessError(
                        result.returncode, result.args,
                        output=result.stdout, stderr=result.stderr,
                    )
                return result.stdout.decode("utf-8", errors="replace")

            raw = await asyncio.to_thread(_run)
            return self._parse_file_freq(raw)
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            logger.warning("git file freq 错误: %s", exc)
            return []
        except subprocess.CalledProcessError as exc:
            stderr_text = exc.stderr.decode(errors="replace") if exc.stderr else ""
            logger.warning("git log (文件) 失败 (rc=%d): %s", exc.returncode, stderr_text.strip())
            return []

    async def _check_ci(self, repo_path: str) -> bool:
        """检查 CI/CD 配置文件。"""
        try:
            workflows_dir = os.path.join(repo_path, ".github", "workflows")
            if os.path.isdir(workflows_dir):
                for fname in os.listdir(workflows_dir):
                    if fname.endswith((".yml", ".yaml")):
                        return True
            return False
        except OSError:
            return False

    # ------------------------------------------------------------------
    # 解析辅助方法
    # ------------------------------------------------------------------

    def _parse_timeline(  # type: ignore[no-untyped-def]
        self, raw: Optional[str]
    ):
        """将 git log 输出解析为时间线指标。

        返回包含 commits_per_week、active_days、activity_over_time 的字典。
        """
        default = {
            "commits_per_week": 0.0,
            "active_days": 0,
            "activity_over_time": [],
        }

        if not raw:
            return default

        commit_dates: list[datetime] = []
        weekly_counter: Counter[str] = Counter()

        for line in raw.strip().split("\n"):
            if not line:
                continue
            parts = line.split("|", 2)
            if len(parts) < 3:
                continue
            date_str = parts[2].strip()[:25]  # "2024-01-15 10:30:00 +0000"
            try:
                dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S %z")
            except ValueError:
                continue
            commit_dates.append(dt)
            iso = dt.isocalendar()
            weekly_counter[f"{iso[0]}-W{iso[1]:02d}"] += 1

        if not commit_dates:
            return default

        oldest = min(commit_dates)
        newest = max(commit_dates)
        span_days = max(1, (newest - oldest).days)
        weeks = max(1, span_days / 7)
        commits_per_week = round(len(commit_dates) / weeks, 1)

        active_days = len({d.date() for d in commit_dates})

        activity_over_time = sorted(
            [
                WeeklyActivity(week=wk, commits=ct)
                for wk, ct in weekly_counter.items()
            ],
            key=lambda a: a.week,
        )

        return {
            "commits_per_week": commits_per_week,
            "active_days": active_days,
            "activity_over_time": activity_over_time,
        }

    @staticmethod
    def _parse_shortlog(raw: str) -> list[Contributor]:
        """将 'git shortlog -sne' 输出解析为 Contributor 列表。

        示例行："    42  Alice <alice@example.com>"
        """
        contributors: list[Contributor] = []
        pattern = re.compile(r"^\s*(\d+)\s+(.+?)\s*<([^>]+)>\s*$")
        for line in raw.strip().split("\n"):
            m = pattern.match(line.strip())
            if m:
                contributors.append(Contributor(
                    commits=int(m.group(1)),
                    name=m.group(2).strip(),
                    email=m.group(3).strip(),
                ))
        return contributors

    @staticmethod
    def _parse_file_freq(raw: str) -> list[ActiveFile]:
        """将 'git log --name-only --format=' 输出解析为 ActiveFile 列表。

        每行是一个文件路径；空行分隔不同的提交。
        我们统计出现次数，按频率降序返回顶部文件。
        """
        counter: Counter[str] = Counter()
        for line in raw.strip().split("\n"):
            path = line.strip()
            if path:
                counter[path] += 1
        return [
            ActiveFile(path=path, changes=count)
            for path, count in counter.most_common(_MAX_ACTIVE_FILES)
        ]

    # ------------------------------------------------------------------
    # 安全解包辅助方法 — 处理 asyncio.gather 返回的异常
    # ------------------------------------------------------------------

    @staticmethod
    def _safe_int(val: object) -> int:
        if isinstance(val, int):
            return val
        if isinstance(val, (str, float)):
            try:
                return int(val)
            except (ValueError, TypeError):
                pass
        return 0

    @staticmethod
    def _safe_bool(val: object) -> bool:
        if isinstance(val, bool):
            return val
        return False

    # ------------------------------------------------------------------
    # 浅克隆检测与 deepening
    # ------------------------------------------------------------------

    async def _check_shallow(self, repo_path: str) -> bool:
        """检测仓库是否是浅克隆。"""
        try:
            def _run() -> str:
                result = subprocess.run(
                    ["git", "-C", repo_path, "rev-parse", "--is-shallow-repository"],
                    capture_output=True, timeout=15,
                )
                return result.stdout.decode("utf-8", errors="replace").strip()

            raw = await asyncio.to_thread(_run)
            return raw.lower() == "true"
        except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
            return False

    async def _unshallow(self, repo_path: str) -> bool:
        """尝试将浅克隆仓库 deepen 为完整历史。"""
        try:
            def _run() -> bool:
                result = subprocess.run(
                    ["git", "-C", repo_path, "fetch", "--unshallow"],
                    capture_output=True, timeout=120,
                )
                return result.returncode == 0

            return await asyncio.to_thread(_run)
        except (FileNotFoundError, subprocess.TimeoutExpired, Exception) as exc:
            logger.warning("git fetch --unshallow 失败: %s", exc)
            return False
