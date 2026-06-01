"""PlanningRules — 分析策略规则引擎。

基于 RepositoryProfiler 输出的仓库特征，
决定应执行和应跳过的分析任务。

规则（按优先级）：
1. file_count > 1000 → 跳过 static_analysis（仓库过大）
2. !has_readme → 跳过 repo_analysis（README 缺失）
3. 默认：全部执行
"""

from __future__ import annotations

import logging

from ..schemas import AnalysisPlan

logger = logging.getLogger(__name__)

# 默认任务列表
_ALL_TASKS = ["static_analysis", "repo_analysis", "git_analysis"]

# 跳过阈值
_FILE_COUNT_SKIP_THRESHOLD = 1000


class PlanningRules:
    """基于规则的动态分析策略引擎。

    用法::

        rules = PlanningRules()
        plan = rules.evaluate(profile)
        # plan.tasks = ["repo_analysis", "git_analysis"]
        # plan.skipped_tasks = ["static_analysis"]
        # plan.reasons = {"static_analysis": "repository too large"}
    """

    def evaluate(self, profile: dict) -> AnalysisPlan:
        """根据仓库特征决定分析策略。

        参数:
            profile: RepositoryProfiler.analyze() 输出。

        返回:
            AnalysisPlan 包含 tasks / skipped_tasks / reasons。
        """
        tasks = list(_ALL_TASKS)
        skipped: list[str] = []
        reasons: dict[str, str] = {}
        priority = "normal"

        # 规则 1: 文件过多 → 跳过静态分析
        file_count = profile.get("file_count", 0)
        if file_count > _FILE_COUNT_SKIP_THRESHOLD:
            if "static_analysis" in tasks:
                tasks.remove("static_analysis")
                skipped.append("static_analysis")
                reasons["static_analysis"] = (
                    f"repository too large ({file_count} files > {_FILE_COUNT_SKIP_THRESHOLD})"
                )

        # 规则 2: README 不存在 → 跳过仓库分析
        has_readme = profile.get("has_readme", False)
        if not has_readme:
            if "repo_analysis" in tasks:
                tasks.remove("repo_analysis")
                skipped.append("repo_analysis")
                reasons["repo_analysis"] = "README missing"

        # 如果跳过了关键任务，提高优先级标识
        if skipped:
            priority = "high"

        plan = AnalysisPlan(
            tasks=tasks,
            skipped_tasks=skipped,
            reasons=reasons,
            priority=priority,
        )

        logger.info(
            "PlanningRules: tasks=%s skipped=%s reason=%s",
            tasks, skipped, reasons,
        )
        return plan
