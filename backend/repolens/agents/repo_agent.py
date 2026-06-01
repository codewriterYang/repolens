"""RepoAgent — RepoAnalyzer 的 Agent 包装层。

保持原有分析逻辑不变，仅增加统一的 BaseAgent 接口。
v2.1: run() 入参升级为 RepositoryContext。
v2.2: 接入 SharedMemory。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from .base import BaseAgent
from ..analyzers.repo_analyzer import RepoAnalyzer
from ..llm_service import LLMService
from ..schemas import RepoResult

if TYPE_CHECKING:
    from ..context import RepositoryContext
    from ..memory import SharedMemory


class RepoAgent(BaseAgent):
    """仓库意图分析 Agent，封装 RepoAnalyzer。"""

    name = "repo"

    def __init__(self, llm: LLMService, memory: Optional[SharedMemory] = None) -> None:
        super().__init__(memory=memory)
        self._analyzer = RepoAnalyzer(llm)

    async def run(self, context: RepositoryContext, **kwargs: Any) -> RepoResult:
        """通过 README + 目录树 + LLM 理解项目意图。

        参数:
            context: 不可变分析上下文，从中提取 repo_path 和 repo_url。

        返回:
            RepoResult 包含使用模式、核心模块、推断风险等。
        """
        self._read_analysis_plan()
        result = await self._analyzer.run(context.repo_path, context.repo_url)

        # Phase 6: 将结果写入 SharedMemory 供 ReportAgent 读取
        if self._memory is not None:
            self._memory.set("repo_result", result)

        return result

    def _read_analysis_plan(self) -> None:
        """从 SharedMemory 读取 PlannerAgent 产出的分析计划。"""
        import logging
        logger = logging.getLogger(__name__)
        if self._memory and self._memory.has("analysis_plan"):
            plan = self._memory.get("analysis_plan")
            logger.info(
                "RepoAgent: 读取分析计划 — tasks=%s priority=%s",
                plan.tasks, plan.priority,
            )
        else:
            logger.info("RepoAgent: 未找到分析计划，使用默认分析策略")
