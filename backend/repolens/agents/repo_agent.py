"""RepoAgent — RepoAnalyzer 的 Agent 包装层。

保持原有分析逻辑不变，仅增加统一的 BaseAgent 接口。
v2.1: run() 入参升级为 RepositoryContext，
      repo_url 从 context 中获取而非通过 kwargs。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .base import BaseAgent
from ..analyzers.repo_analyzer import RepoAnalyzer
from ..llm_service import LLMService
from ..schemas import RepoResult

if TYPE_CHECKING:
    from ..context import RepositoryContext


class RepoAgent(BaseAgent):
    """仓库意图分析 Agent，封装 RepoAnalyzer。"""

    name = "repo"

    def __init__(self, llm: LLMService) -> None:
        self._analyzer = RepoAnalyzer(llm)

    async def run(self, context: RepositoryContext, **kwargs: Any) -> RepoResult:
        """通过 README + 目录树 + LLM 理解项目意图。

        参数:
            context: 不可变分析上下文，从中提取 repo_path 和 repo_url。

        返回:
            RepoResult 包含使用模式、核心模块、推断风险等。
        """
        return await self._analyzer.run(context.repo_path, context.repo_url)
