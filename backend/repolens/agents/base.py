"""BaseAgent — 所有 Agent 的抽象基类。

定义了统一的 run() 接口，保证 AgentRegistry 和 Orchestrator
可以对任意 Agent 进行统一调度与生命周期管理。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseAgent(ABC):
    """分析 Agent 的抽象基类。

    所有具体 Agent（StaticAgent / RepoAgent / GitAgent）
    均继承此类并实现 run() 方法。

    设计原则：
    - run() 接收仓库路径，返回分析结果（Pydantic 模型或 dict）
    - 不抛异常：失败时返回带 error 字段的结果
    - 无状态：Agent 实例可在多次调用中复用
    """

    # Agent 名称，子类覆盖
    name: str = "base"

    @abstractmethod
    async def run(self, repo_path: str, **kwargs: Any) -> Any:
        """对指定仓库路径执行分析。

        参数:
            repo_path: 克隆仓库的绝对路径。

        返回:
            分析结果对象（StaticResult / RepoResult / GitResult 等）。
            失败时不抛异常，返回带 error 字段的结果。
        """
        ...
