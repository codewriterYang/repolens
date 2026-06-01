"""DynamicPlanner — 动态策略编排器。

组合 RepositoryProfiler + PlanningRules，
根据仓库特征生成分析计划。

不引入 LLM 调用，纯规则引擎驱动。
"""

from __future__ import annotations

import logging

from .repository_profiler import RepositoryProfiler
from .planning_rules import PlanningRules
from ..schemas import AnalysisPlan

logger = logging.getLogger(__name__)


class DynamicPlanner:
    """动态分析策略编排器。

    用法::

        planner = DynamicPlanner()
        plan = planner.plan(repo_path)
        # plan.tasks → 根据仓库特征动态决定的执行列表
    """

    def __init__(self) -> None:
        self._profiler = RepositoryProfiler()
        self._rules = PlanningRules()

    def plan(self, repo_path: str) -> AnalysisPlan:
        """分析仓库并生成动态分析计划。

        参数:
            repo_path: 克隆仓库的绝对路径。

        返回:
            AnalysisPlan 包含动态决定的 tasks / skipped_tasks / reasons。
        """
        profile = self._profiler.analyze(repo_path)
        plan = self._rules.evaluate(profile)

        logger.info(
            "DynamicPlanner: %d tasks, %d skipped — %s",
            len(plan.tasks), len(plan.skipped_tasks),
            plan.reasons,
        )
        return plan
