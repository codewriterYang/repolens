"""流水线编排器 — 调度和协调分析工作流。

设计：
- 接收 job_id 和 repo_url，异步执行完整流水线。
- 三个分析器并行运行（asyncio.gather），各自有独立超时。
- Reporter 在分析器完成后串行运行。
- 状态更新写入数据库供前端轮询。
- 优雅降级：单个分析器失败不会导致整体崩溃。
- 流水线级超时防止失控任务。
- 结构化日志追踪执行过程。
"""

from __future__ import annotations

import asyncio
import logging
import time
import traceback
from typing import Optional

import aiosqlite

from .analyzers.git_analyzer import GitAnalyzer
from .analyzers.repo_analyzer import RepoAnalyzer
from .analyzers.static_analyzer import StaticAnalyzer
from .cloner import CloneError, RepoCloner
from .config import config
from .db import save_partial_results, save_report, update_job_status
from .llm_service import LLMService
from .reporter import Reporter
from .schemas import GitResult, JobStatus, RepoResult, StaticResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 各分析器超时配置（秒）
# 这些是在分析器自身上限之上的额外保护。
# ---------------------------------------------------------------------------

_TIMEOUT_STATIC = 420   # pylint + radon 在大型仓库上可能较慢
_TIMEOUT_REPO = 150     # LLM 调用 + 文件 I/O
_TIMEOUT_GIT = 120      # git 子进程


class PipelineError(Exception):
    """致命流水线错误（例如克隆失败）。"""


class Orchestrator:
    """协调完整分析流水线：克隆 → 分析 → 报告。

    每个应用生命周期实例化一次。每次 run_pipeline 调用
    产生一个独立的异步后台任务。
    """

    def __init__(self, db: aiosqlite.Connection, llm: LLMService):
        self._db = db
        self._llm = llm
        self._static = StaticAnalyzer()
        self._repo = RepoAnalyzer(llm)
        self._git = GitAnalyzer()
        self._reporter = Reporter()
        self._cloner = RepoCloner()

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    async def run_pipeline(self, job_id: str, repo_url: str) -> None:
        """执行完整分析流水线。

        该方法以异步任务（asyncio.create_task）方式被调用。
        所有错误均被捕获并记录到数据库中。

        参数：
            job_id: 唯一任务标识（UUID hex）。
            repo_url: GitHub URL 或本地文件系统路径。
        """
        pipeline_start = time.monotonic()
        logger.info("流水线 [%s] 开始, repo=%s", job_id, repo_url)

        try:
            # 将整个流水线包装在总超时中
            await asyncio.wait_for(
                self._execute(job_id, repo_url, pipeline_start),
                timeout=config.pipeline_timeout_seconds,
            )

        except asyncio.TimeoutError:
            logger.error("流水线 [%s] 超时 (%ds)", job_id, config.pipeline_timeout_seconds)
            await self._handle_fatal(
                job_id, JobStatus.TIMEOUT,
                f"流水线执行超时 ({config.pipeline_timeout_seconds}s)",
            )

        except CloneError as exc:
            logger.error("流水线 [%s] 克隆失败: %s", job_id, exc)
            await self._handle_fatal(job_id, JobStatus.FAILED, str(exc))

        except Exception as exc:
            tb = traceback.format_exc()
            logger.exception("流水线 [%s] 未处理异常", job_id)
            await self._handle_fatal(job_id, JobStatus.FAILED, f"{exc}\n{tb}")

        finally:
            await self._cloner.cleanup()
            elapsed = time.monotonic() - pipeline_start
            logger.info("流水线 [%s] 完成，耗时 %.1fs", job_id, elapsed)

    # ------------------------------------------------------------------
    # 内部：执行阶段
    # ------------------------------------------------------------------

    async def _execute(
        self, job_id: str, repo_url: str, pipeline_start: float,
    ) -> None:
        """核心流水线逻辑（在总超时内运行）。"""

        # --- 阶段一：克隆 -------------------------------------------------
        await self._set_status(job_id, JobStatus.CLONING, 5, "正在克隆仓库...")
        t0 = time.monotonic()
        repo_path = await asyncio.wait_for(
            self._cloner.clone(repo_url, job_id),
            timeout=config.clone_timeout_seconds,
        )
        logger.info(
            "流水线 [%s] 克隆完成 (%.1fs): %s",
            job_id, time.monotonic() - t0, repo_path,
        )

        # --- 阶段二：并行分析 --------------------------------------------
        await self._set_status(job_id, JobStatus.ANALYZING, 20, "正在分析代码...")
        static_result, repo_result, git_result, analyzer_durations = (
            await self._run_analyzers(job_id, repo_path, repo_url)
        )
        logger.info(
            "流水线 [%s] 分析器完成: static=%s repo=%s git=%s 耗时=%s",
            job_id,
            "OK" if static_result and not static_result.error else "FAIL",
            "OK" if repo_result and not repo_result.error else "FAIL",
            "OK" if git_result and not git_result.error else "FAIL",
            analyzer_durations,
        )

        # 保存部分结果，供前端展示中间数据
        await self._save_partials(
            job_id, static_result, repo_result, git_result,
        )

        # --- 阶段三：报告生成 --------------------------------------------
        await self._set_status(job_id, JobStatus.REPORTING, 75, "正在生成报告...")
        t0 = time.monotonic()
        report = self._reporter.render(
            job_id=job_id,
            repo_url=repo_url,
            static_result=static_result,
            repo_result=repo_result,
            git_result=git_result,
            pipeline_start=pipeline_start,
        )
        logger.info(
            "流水线 [%s] 报告生成 (%.1fs) score=%d 建议=%d",
            job_id, time.monotonic() - t0,
            report.health_score, len(report.recommendations),
        )

        # --- 阶段四：持久化 -----------------------------------------------
        await save_report(self._db, job_id, report)
        logger.info("流水线 [%s] 报告已持久化", job_id)

    # ------------------------------------------------------------------
    # 分析器执行
    # ------------------------------------------------------------------

    async def _run_analyzers(
        self, job_id: str, repo_path: str, repo_url: str,
    ) -> tuple[
        Optional[StaticResult],
        Optional[RepoResult],
        Optional[GitResult],
        dict[str, float],
    ]:
        """并行运行全部三个分析器，各自有独立超时。

        每个分析器的失败独立 — 一个失败不会阻碍其他分析器。
        Reporter 优雅处理缺失的结果。

        返回：
            (static_result, repo_result, git_result, durations_dict) 元组。
            durations_dict 映射分析器名称 → 耗时（秒）。
        """
        durations: dict[str, float] = {}

        async def run_static() -> Optional[StaticResult]:
            t0 = time.monotonic()
            try:
                result = await asyncio.wait_for(
                    self._static.run(repo_path), timeout=_TIMEOUT_STATIC,
                )
                durations["static"] = time.monotonic() - t0
                if result.error:
                    logger.warning(
                        "流水线 [%s] 静态分析降级: %s", job_id, result.error,
                    )
                else:
                    logger.info(
                        "流水线 [%s] 静态分析 OK: %d 个文件, %d 个高复杂度函数",
                        job_id, result.total_files_scanned,
                        len(result.high_complexity_functions),
                    )
                return result
            except asyncio.TimeoutError:
                durations["static"] = time.monotonic() - t0
                logger.error(
                    "流水线 [%s] 静态分析超时 (%ds)", job_id, _TIMEOUT_STATIC,
                )
                return StaticResult(error=f"静态分析超时 ({_TIMEOUT_STATIC}s)")
            except Exception as exc:
                durations["static"] = time.monotonic() - t0
                logger.exception("流水线 [%s] 静态分析失败", job_id)
                return StaticResult(error=f"静态分析失败: {exc}")

        async def run_repo() -> Optional[RepoResult]:
            t0 = time.monotonic()
            try:
                result = await asyncio.wait_for(
                    self._repo.run(repo_path, repo_url), timeout=_TIMEOUT_REPO,
                )
                durations["repo"] = time.monotonic() - t0
                if result.error:
                    logger.warning(
                        "流水线 [%s] 仓库分析降级: %s", job_id, result.error,
                    )
                else:
                    logger.info(
                        "流水线 [%s] 仓库分析 OK: %d 个模式, %d 个模块",
                        job_id, len(result.usage_patterns),
                        len(result.core_modules),
                    )
                return result
            except asyncio.TimeoutError:
                durations["repo"] = time.monotonic() - t0
                logger.error(
                    "流水线 [%s] 仓库分析超时 (%ds)", job_id, _TIMEOUT_REPO,
                )
                return RepoResult(error=f"仓库分析超时 ({_TIMEOUT_REPO}s)")
            except Exception as exc:
                durations["repo"] = time.monotonic() - t0
                logger.exception("流水线 [%s] 仓库分析失败", job_id)
                return RepoResult(error=f"仓库分析失败: {exc}")

        async def run_git() -> Optional[GitResult]:
            t0 = time.monotonic()
            try:
                result = await asyncio.wait_for(
                    self._git.run(repo_path), timeout=_TIMEOUT_GIT,
                )
                durations["git"] = time.monotonic() - t0
                if result.error:
                    logger.warning(
                        "流水线 [%s] Git 分析降级: %s", job_id, result.error,
                    )
                else:
                    logger.info(
                        "流水线 [%s] Git 分析 OK: %d 次提交, %d 位贡献者",
                        job_id, result.total_commits,
                        result.unique_contributors,
                    )
                return result
            except asyncio.TimeoutError:
                durations["git"] = time.monotonic() - t0
                logger.error(
                    "流水线 [%s] Git 分析超时 (%ds)", job_id, _TIMEOUT_GIT,
                )
                return GitResult(error=f"Git 分析超时 ({_TIMEOUT_GIT}s)")
            except Exception as exc:
                durations["git"] = time.monotonic() - t0
                logger.exception("流水线 [%s] Git 分析失败", job_id)
                return GitResult(error=f"Git 分析失败: {exc}")

        results = await asyncio.gather(
            run_static(), run_repo(), run_git(),
            return_exceptions=True,
        )

        # 解包 — 每个结果要么是带类型的结果，要么是异常
        def unwrap(idx: int) -> Optional[object]:
            val = results[idx]
            if isinstance(val, BaseException):
                logger.error(
                    "流水线 [%s] 分析器[%d] 返回未处理异常: %s",
                    job_id, idx, val,
                )
                return None
            return val

        return (
            unwrap(0),  # type: ignore[return-value]
            unwrap(1),  # type: ignore[return-value]
            unwrap(2),  # type: ignore[return-value]
            durations,
        )

    # ------------------------------------------------------------------
    # 数据库辅助方法
    # ------------------------------------------------------------------

    async def _set_status(
        self,
        job_id: str,
        status: JobStatus,
        progress_pct: int,
        stage_label: str,
    ) -> None:
        """更新数据库中的任务状态。"""
        try:
            await update_job_status(
                self._db, job_id, status,
                progress_pct=progress_pct,
                stage_label=stage_label,
            )
        except Exception:
            logger.exception(
                "流水线 [%s] 更新状态到 %s 失败", job_id, status.value,
            )

    async def _save_partials(
        self,
        job_id: str,
        static_result: Optional[StaticResult],
        repo_result: Optional[RepoResult],
        git_result: Optional[GitResult],
    ) -> None:
        """持久化分析器中间输出供前端轮询。"""
        try:
            await save_partial_results(
                self._db,
                job_id,
                static_result=static_result.model_dump() if static_result else None,
                repo_result=repo_result.model_dump() if repo_result else None,
                git_result=git_result.model_dump() if git_result else None,
            )
        except Exception:
            logger.exception(
                "流水线 [%s] 保存部分结果失败", job_id,
            )

    async def _handle_fatal(
        self, job_id: str, status: JobStatus, error_msg: str
    ) -> None:
        """记录致命流水线错误。"""
        try:
            await update_job_status(
                self._db, job_id, status,
                error_msg=error_msg[:2000],
            )
        except Exception:
            logger.exception(
                "流水线 [%s] 记录致命错误失败", job_id,
            )
