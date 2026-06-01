"""流水线编排器 — 调度和协调分析工作流。

设计：
- 接收 job_id 和 repo_url，异步执行完整流水线。
- 三个 Agent 通过 AgentRegistry 并行调度，各自有独立超时。
- Reporter 在 Agent 完成后串行运行。
- 状态更新写入数据库供前端轮询。
- 优雅降级：单个 Agent 失败不会导致整体崩溃。
- 流水线级超时防止失控任务。
- 结构化日志追踪执行过程。

v2.0: Agent 架构 — 分析器通过 BaseAgent 接口统一包装，
由 AgentRegistry 注册和调度，Orchestrator 不再直接持有分析器实例。
"""

from __future__ import annotations

import asyncio
import logging
import time
import traceback
from typing import Optional

import aiosqlite

from .agents import AgentRegistry, GitAgent, PlannerAgent, RepoAgent, StaticAgent
from .cloner import CloneError, RepoCloner
from .config import config
from .context import ContextManager
from .db import save_partial_results, save_report, update_job_status
from .llm_service import LLMService
from .memory import MemoryManager
from .reporter import Reporter
from .schemas import AnalysisPlan, AnalysisStrategy, GitResult, JobStatus, RepoResult, StaticResult

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
        self._reporter = Reporter()
        self._cloner = RepoCloner()

        # --- v2.0: Agent 架构 ---
        # Agent 通过 Registry 注册，Orchestrator 不再直接持有分析器实例。
        self._registry = AgentRegistry()

        # --- v2.3: PlannerAgent（Phase 5，第一个协作 Agent）---
        self._planner = PlannerAgent()
        self._registry.register(self._planner)

        self._registry.register(StaticAgent())
        self._registry.register(RepoAgent(llm))
        self._registry.register(GitAgent())

        # --- v2.1: Context 层 ---
        # ContextManager 负责创建和校验分析上下文，
        # Agent 通过 RepositoryContext 获取所需信息。
        self._ctx_manager = ContextManager()

        # --- v2.2: Memory 层 ---
        # MemoryManager 负责每个流水线的 SharedMemory 生命周期，
        # Agent 通过 SharedMemory 共享中间分析结果。
        self._mem_manager = MemoryManager()

        logger.debug(
            "Orchestrator 已注册 %d 个 Agent: %s",
            len(self._registry), self._registry.list(),
        )

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

        # --- 阶段二：Agent 协作（v2.3: Planner → Memory → Analyzers） --
        await self._set_status(job_id, JobStatus.ANALYZING, 20, "正在分析代码...")
        # 创建分析上下文和共享记忆
        context = self._ctx_manager.create(repo_url, repo_path, job_id)
        memory = self._mem_manager.create()
        self._registry.inject_memory(memory)

        # Phase 7: PlannerAgent 动态制定分析计划
        plan = await self._run_planner(job_id, context)

        # 根据 Plan 动态执行分析 Agent
        static_result, repo_result, git_result, analyzer_durations = (
            await self._run_analyzers(job_id, context, plan)
        )

        logger.debug(
            "流水线 [%s] Memory 使用: %d 条记录",
            job_id, len(memory),
        )
        self._mem_manager.clear()
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
    # Planner 执行（Phase 5）
    # ------------------------------------------------------------------

    async def _run_planner(
        self, job_id: str, context,
    ) -> AnalysisPlan:
        """运行 PlannerAgent，返回动态分析计划。

        Phase 7: Planner 失败时返回默认计划（全部执行）。
        """
        try:
            plan = await asyncio.wait_for(
                self._planner.run(context),
                timeout=30,
            )
            logger.info(
                "流水线 [%s] Planner 完成: tasks=%s strategy=%s",
                job_id, plan.tasks, plan.strategy.model_dump(),
            )
            return plan
        except asyncio.TimeoutError:
            logger.warning("流水线 [%s] Planner 超时，使用默认计划", job_id)
        except Exception as exc:
            logger.warning("流水线 [%s] Planner 失败: %s", job_id, exc)
        # 降级：默认 full 策略全部执行
        return AnalysisPlan(
            tasks=["static_analysis", "repo_analysis", "git_analysis"],
            strategy=AnalysisStrategy(static="full", repo="full", git="full"),
            priority="normal",
        )

    # ------------------------------------------------------------------
    # 分析器执行
    # ------------------------------------------------------------------

    async def _run_analyzers(
        self, job_id: str, context, plan: AnalysisPlan,
    ) -> tuple[
        Optional[StaticResult],
        Optional[RepoResult],
        Optional[GitResult],
        dict[str, float],
    ]:
        """执行所有分析 Agent，各自有独立超时。

        Phase 8: 所有 Agent 始终执行，不再 skip。
        StaticAgent 从 AnalysisPlan.strategy.static 选择分析深度。

        参数:
            job_id: 分析任务 ID。
            context: RepositoryContext，通过 AgentRegistry 传递给各 Agent。
            plan: AnalysisPlan，含 strategy 字段决定各 Agent 执行模式。

        返回:
            (static_result, repo_result, git_result, durations_dict) 元组。
            durations_dict 映射 Agent 名称 → 耗时（秒）。
        """
        durations: dict[str, float] = {}

        async def run_static() -> Optional[StaticResult]:
            t0 = time.monotonic()
            agent = self._registry.get("static")
            try:
                result = await asyncio.wait_for(
                    agent.run(context), timeout=_TIMEOUT_STATIC,
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
            agent = self._registry.get("repo")
            try:
                result = await asyncio.wait_for(
                    agent.run(context), timeout=_TIMEOUT_REPO,
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
            # git_analysis 始终执行（规则引擎不会跳过）
            t0 = time.monotonic()
            agent = self._registry.get("git")
            try:
                result = await asyncio.wait_for(
                    agent.run(context), timeout=_TIMEOUT_GIT,
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
