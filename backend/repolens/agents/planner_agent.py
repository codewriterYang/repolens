"""PlannerAgent — 分析计划编排 Agent。

Phase 8: 从 skip-task 升级为 strategy 模式。
基于仓库特征选择各 Agent 的执行策略（full/focused/fast），
所有 Agent 始终执行，不再跳过。

协作链路：
RepositoryProfiler → PlanningRules → AnalysisPlan → SharedMemory
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from .base import BaseAgent
from ..planner import DynamicPlanner
from ..schemas import AnalysisPlan

if TYPE_CHECKING:
    from ..context import RepositoryContext

logger = logging.getLogger(__name__)


class PlannerAgent(BaseAgent):
    """分析计划编排 Agent（策略模式版）。

    在流水线中第一个运行，根据仓库 .py 文件数制定动态策略：
    - ≤ 500 → static = "full"（完整 pylint + radon）
    - 501–1000 → static = "focused"（排除测试文件的 pylint + radon）
    - > 1000 → static = "fast"（跳过 pylint，仅 radon）

    所有 Agent 始终执行，策略仅影响分析深度。
    计划通过 SharedMemory 传递给后续 Agent 和 Orchestrator。
    """

    name = "planner"

    def __init__(self, memory=None):
        super().__init__(memory=memory)
        self._dynamic_planner = DynamicPlanner()

    async def run(self, context: RepositoryContext, **kwargs: Any) -> AnalysisPlan:
        """制定动态分析计划并写入 SharedMemory。

        参数:
            context: 不可变分析上下文。

        返回:
            AnalysisPlan 包含动态决定的 strategy / tasks / reasons。
        """
        # Phase 8: 根据仓库特征动态选择执行策略（full/focused/fast）
        plan = self._dynamic_planner.plan(context.repo_path)

        # 将计划写入 SharedMemory
        if self._memory is not None:
            self._memory.set("analysis_plan", plan)
            logger.info(
                "PlannerAgent: 动态计划 — strategy=%s tasks=%s",
                plan.strategy.model_dump(), plan.tasks,
            )
        else:
            logger.warning("PlannerAgent: SharedMemory 未注入，计划未持久化")

        return plan
