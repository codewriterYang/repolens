"""StaticAgent — StaticAnalyzer 的 Agent 包装层。

保持原有分析逻辑不变，仅增加统一的 BaseAgent 接口。
v2.1: run() 入参升级为 RepositoryContext。
v2.2: 接入 SharedMemory。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from .base import BaseAgent
from ..analyzers.static_analyzer import StaticAnalyzer
from ..schemas import StaticResult

if TYPE_CHECKING:
    from ..context import RepositoryContext
    from ..memory import SharedMemory


class StaticAgent(BaseAgent):
    """代码质量分析 Agent，封装 StaticAnalyzer。"""

    name = "static"

    def __init__(self, memory: Optional[SharedMemory] = None) -> None:
        super().__init__(memory=memory)
        self._analyzer = StaticAnalyzer()

    async def run(self, context: RepositoryContext, **kwargs: Any) -> StaticResult:
        """执行静态代码分析。

        参数:
            context: 不可变分析上下文，从中提取 repo_path。

        返回:
            StaticResult 包含 pylint 评分、圈复杂度热点、
            文件风险摘要等。
        """
        strategy_mode = self._read_analysis_strategy()
        result = await self._analyzer.run(context.repo_path, strategy_mode)

        # Phase 6: 将结果写入 SharedMemory 供 ReportAgent 读取
        if self._memory is not None:
            self._memory.set("static_result", result)

        return result

    def _read_analysis_strategy(self) -> str:
        """从 SharedMemory 读取 PlannerAgent 的 static 策略模式。"""
        import logging
        logger = logging.getLogger(__name__)
        if self._memory and self._memory.has("analysis_plan"):
            plan = self._memory.get("analysis_plan")
            strategy = getattr(plan, "strategy", None)
            if strategy:
                mode = strategy.static
                logger.info(
                    "StaticAgent: 读取策略 — static=%s (confidence=%d%%)",
                    mode, strategy.static_confidence,
                )
                return mode
        logger.info("StaticAgent: 未找到分析策略，默认 full 模式")
        return "full"
