"""RepoLens Context 层 — 分析上下文管理。

提供不可变的分析上下文（RepositoryContext）和上下文管理器，
为 Agent 提供统一的输入接口，解耦 Agent 与原始参数传递。

v2.1: Phase 3 Agent Context Layer
"""

from .base import RepositoryContext
from .repository_context import make_context
from .context_manager import ContextManager

__all__ = [
    "RepositoryContext",
    "make_context",
    "ContextManager",
]
