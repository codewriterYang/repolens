"""RepoAgent — RepoAnalyzer 的 Agent 包装层。

保持原有分析逻辑不变，仅增加统一的 BaseAgent 接口。
由于 RepoAnalyzer 需要 LLM 服务和 repo_url 参数，
Agent 在 run() 中额外接收这些参数。
"""

from __future__ import annotations

from typing import Any

from .base import BaseAgent
from ..analyzers.repo_analyzer import RepoAnalyzer
from ..llm_service import LLMService
from ..schemas import RepoResult


class RepoAgent(BaseAgent):
    """仓库意图分析 Agent，封装 RepoAnalyzer。"""

    name = "repo"

    def __init__(self, llm: LLMService) -> None:
        self._analyzer = RepoAnalyzer(llm)

    async def run(self, repo_path: str, **kwargs: Any) -> RepoResult:
        """通过 README + 目录树 + LLM 理解项目意图。

        参数:
            repo_path: 克隆仓库的绝对路径。
            repo_url: 必须通过 kwargs 传入原始仓库 URL。

        返回:
            RepoResult 包含使用模式、核心模块、推断风险等。
        """
        repo_url = kwargs.get("repo_url", "")
        return await self._analyzer.run(repo_path, repo_url)
