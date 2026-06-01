"""PlannerAgent — 分析计划编排 Agent。

Phase 7: 升级为动态策略引擎。
不再返回固定 tasks，而是根据仓库特征动态决定执行哪些分析任务。

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
    """分析计划编排 Agent（动态策略版）。

    在流水线中第一个运行，根据仓库特征制定动态分析计划：
    - 文件 > 1000 → 跳过 static_analysis
    - README 不存在 → 跳过 repo_analysis
    - 其余情况默认全部执行

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
            AnalysisPlan 包含动态决定的 tasks / skipped_tasks / reasons。
        """
        # Phase 7: 不再返回固定 tasks，改为根据仓库特征动态决定
        plan = self._dynamic_planner.plan(context.repo_path)

        # 将计划写入 SharedMemory
        if self._memory is not None:
            self._memory.set("analysis_plan", plan)
            logger.info(
                "PlannerAgent: 动态计划 — tasks=%s skipped=%s reason=%s",
                plan.tasks, plan.skipped_tasks, plan.reasons,
            )
        else:
            logger.warning("PlannerAgent: SharedMemory 未注入，计划未持久化")

        return plan
