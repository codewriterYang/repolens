"""GitAgent — GitAnalyzer 的 Agent 包装层。

保持原有分析逻辑不变，仅增加统一的 BaseAgent 接口。
v2.1: run() 入参升级为 RepositoryContext。
v2.2: 接入 SharedMemory。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from .base import BaseAgent
from ..analyzers.git_analyzer import GitAnalyzer
from ..schemas import GitResult

if TYPE_CHECKING:
    from ..context import RepositoryContext
    from ..memory import SharedMemory


class GitAgent(BaseAgent):
    """Git 活动分析 Agent，封装 GitAnalyzer。"""

    name = "git"

    def __init__(self, memory: Optional[SharedMemory] = None) -> None:
        super().__init__(memory=memory)
        self._analyzer = GitAnalyzer()

    async def run(self, context: RepositoryContext, **kwargs: Any) -> GitResult:
        """分析 Git 仓库提交历史与活动趋势。

        参数:
            context: 不可变分析上下文，从中提取 repo_path。

        返回:
            GitResult 包含提交统计、贡献者、活跃文件、CI/CD 状态等。
        """
        return await self._analyzer.run(context.repo_path)
