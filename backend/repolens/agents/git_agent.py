"""GitAgent — GitAnalyzer 的 Agent 包装层。

保持原有分析逻辑不变，仅增加统一的 BaseAgent 接口。
"""

from __future__ import annotations

from typing import Any

from .base import BaseAgent
from ..analyzers.git_analyzer import GitAnalyzer
from ..schemas import GitResult


class GitAgent(BaseAgent):
    """Git 活动分析 Agent，封装 GitAnalyzer。"""

    name = "git"

    def __init__(self) -> None:
        self._analyzer = GitAnalyzer()

    async def run(self, repo_path: str, **kwargs: Any) -> GitResult:
        """分析 Git 仓库提交历史与活动趋势。

        参数:
            repo_path: 克隆仓库的绝对路径。

        返回:
            GitResult 包含提交统计、贡献者、活跃文件、CI/CD 状态等。
        """
        return await self._analyzer.run(repo_path)
