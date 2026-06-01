"""RepoLens Agent 层 — 分析器的统一抽象包装。

每个 Agent 封装一个 Analyzer，通过 BaseAgent 接口暴露，
由 AgentRegistry 统一注册与调度。
"""

from .base import BaseAgent
from .static_agent import StaticAgent
from .repo_agent import RepoAgent
from .git_agent import GitAgent
from .planner_agent import PlannerAgent
from .registry import AgentRegistry

__all__ = [
    "BaseAgent",
    "StaticAgent",
    "RepoAgent",
    "GitAgent",
    "PlannerAgent",
    "AgentRegistry",
]
