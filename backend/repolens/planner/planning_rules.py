"""PlanningRules — 分析策略规则引擎。

Phase 8: 从 skip-task 升级为 strategy 模式。
基于仓库特征选择各 Agent 的执行策略（full/sampled/fast），
所有 Agent 始终执行，不再跳过。

规则（按优先级）：
1. file_count > 1000 → static = "fast"（仅 radon cc）
2. file_count 501-1000 → static = "sampled"（核心文件 pylint + 全量 radon）
3. file_count ≤ 500 → static = "full"（完整 pylint + radon）
4. repo / git → 始终 "full"
"""

from __future__ import annotations

import logging

from ..schemas import AnalysisPlan, AnalysisStrategy

logger = logging.getLogger(__name__)

# 默认任务列表（始终全量执行）
_ALL_TASKS = ["static_analysis", "repo_analysis", "git_analysis"]

# 策略阈值
_SAMPLED_THRESHOLD = 500
_FAST_THRESHOLD = 1000


class PlanningRules:
    """基于规则的动态分析策略引擎。

    用法::

        rules = PlanningRules()
        plan = rules.evaluate(profile)
        # plan.strategy.static == "fast"  (而非 skip)
        # plan.tasks == ["static_analysis", "repo_analysis", "git_analysis"]  (始终全量)
    """

    def evaluate(self, profile: dict) -> AnalysisPlan:
        """根据仓库特征选择分析策略。

        参数:
            profile: RepositoryProfiler.analyze() 输出。

        返回:
            AnalysisPlan 包含 strategy（含各 Agent 执行模式）。
        """
        file_count = profile.get("file_count", 0)
        reasons: dict[str, str] = {}
        static_strategy = "full"
        priority = "normal"

        if file_count > _FAST_THRESHOLD:
            static_strategy = "fast"
            reasons["static"] = (
                f"超大仓库 ({file_count} files > {_FAST_THRESHOLD})，"
                f"fast 模式：仅 radon cc 扫描"
            )
            priority = "high"
        elif file_count > _SAMPLED_THRESHOLD:
            static_strategy = "sampled"
            reasons["static"] = (
                f"大仓库 ({file_count} files, {_SAMPLED_THRESHOLD}-{_FAST_THRESHOLD})，"
                f"sampled 模式：核心文件 pylint + 全量 radon"
            )
        else:
            reasons["static"] = (
                f"小仓库 ({file_count} files ≤ {_SAMPLED_THRESHOLD})，"
                f"full 模式：完整 pylint + radon"
            )

        strategy = AnalysisStrategy(
            static=static_strategy,
            repo="full",
            git="full",
        )

        plan = AnalysisPlan(
            tasks=list(_ALL_TASKS),
            strategy=strategy,
            reasons=reasons,
            priority=priority,
        )

        logger.info(
            "PlanningRules: strategy=%s priority=%s",
            strategy.model_dump(), priority,
        )
        return plan
