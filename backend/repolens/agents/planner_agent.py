"""PlannerAgent — 分析计划编排 Agent。

Phase 5: 第一个真正参与 Agent 协作的 Agent。

职责：
- 根据 RepositoryContext 制定分析计划 (AnalysisPlan)
- 将分析计划写入 SharedMemory (key: "analysis_plan")
- 后续 Agent 读取此计划以了解应执行的分析任务

这是 RepoLens 第一条真实 Agent 协作链路：
PlannerAgent → SharedMemory → StaticAgent/RepoAgent/GitAgent
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from .base import BaseAgent
from ..schemas import AnalysisPlan

if TYPE_CHECKING:
    from ..context import RepositoryContext

logger = logging.getLogger(__name__)


class PlannerAgent(BaseAgent):
    """分析计划编排 Agent。

    在流水线中第一个运行，根据仓库上下文制定分析计划，
    将计划写入 SharedMemory 供后续 Agent 读取。

    当前 MVP 阶段始终返回默认计划（三个分析器全部启用），
    后续可扩展为根据仓库特征动态决定分析策略。
    """

    name = "planner"

    async def run(self, context: RepositoryContext, **kwargs: Any) -> AnalysisPlan:
        """制定分析计划并写入 SharedMemory。

        参数:
            context: 不可变分析上下文。

        返回:
            AnalysisPlan 对象。
        """
        plan = AnalysisPlan(
            tasks=["static_analysis", "repo_analysis", "git_analysis"],
            priority="normal",
        )

        # 将计划写入 SharedMemory，供其他 Agent 读取
        if self._memory is not None:
            self._memory.set("analysis_plan", plan)
            logger.info(
                "PlannerAgent: 分析计划已写入 SharedMemory — %s",
                plan.model_dump(),
            )
        else:
            logger.warning("PlannerAgent: SharedMemory 未注入，计划未持久化")

        return plan
