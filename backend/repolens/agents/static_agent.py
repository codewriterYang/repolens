"""StaticAgent — StaticAnalyzer 的 Agent 包装层。

保持原有分析逻辑不变，仅增加统一的 BaseAgent 接口。
"""

from __future__ import annotations

from typing import Any

from .base import BaseAgent
from ..analyzers.static_analyzer import StaticAnalyzer
from ..schemas import StaticResult


class StaticAgent(BaseAgent):
    """代码质量分析 Agent，封装 StaticAnalyzer。"""

    name = "static"

    def __init__(self) -> None:
        self._analyzer = StaticAnalyzer()

    async def run(self, repo_path: str, **kwargs: Any) -> StaticResult:
        """执行静态代码分析。

        参数:
            repo_path: 克隆仓库的绝对路径。

        返回:
            StaticResult 包含 pylint 评分、圈复杂度热点、
            文件风险摘要等。
        """
        return await self._analyzer.run(repo_path)
