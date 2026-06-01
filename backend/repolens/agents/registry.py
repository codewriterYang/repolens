"""AgentRegistry — Agent 注册中心与生命周期管理。

职责：
- 注册：将 Agent 实例按名称注册到中心注册表
- 获取：通过名称获取已注册的 Agent
- 生命周期：统一管理 Agent 实例的创建与销毁
- 调度：提供并行调度多个 Agent 的便捷方法

设计原则：
- 单例模式：每个应用生命周期一个 Registry 实例
- 延迟实例化：Agent 在注册时才创建内部 Analyzer
- 无侵入：已有 Analyzer 代码完全不变
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from .base import BaseAgent

logger = logging.getLogger(__name__)


class AgentRegistry:
    """Agent 注册中心。

    用法::

        registry = AgentRegistry()

        # 注册
        registry.register(StaticAgent())
        registry.register(RepoAgent(llm))
        registry.register(GitAgent())

        # 获取
        agent = registry.get("static")

        # 并行调度
        results = await registry.run_all(
            [("static", repo_path), ("git", repo_path)],
            return_exceptions=True,
        )
    """

    def __init__(self) -> None:
        self._agents: dict[str, BaseAgent] = {}

    # ------------------------------------------------------------------
    # 注册
    # ------------------------------------------------------------------

    def register(self, agent: BaseAgent) -> None:
        """将 Agent 实例注册到中心注册表。

        参数:
            agent: 继承自 BaseAgent 的实例。

        异常:
            ValueError: 如果同名 Agent 已注册。
        """
        if agent.name in self._agents:
            raise ValueError(
                f"Agent '{agent.name}' 已注册，不能重复注册"
            )
        self._agents[agent.name] = agent
        logger.debug("注册 Agent: %s → %s", agent.name, type(agent).__name__)

    # ------------------------------------------------------------------
    # 获取
    # ------------------------------------------------------------------

    def get(self, name: str) -> Optional[BaseAgent]:
        """通过名称获取已注册的 Agent。

        参数:
            name: Agent 名称（如 "static"、"repo"、"git"）。

        返回:
            Agent 实例，未注册时返回 None。
        """
        return self._agents.get(name)

    def list(self) -> list[str]:
        """返回所有已注册 Agent 的名称列表。"""
        return list(self._agents.keys())

    # ------------------------------------------------------------------
    # 调度
    # ------------------------------------------------------------------

    async def run_all(
        self,
        tasks: list[tuple[str, str]],
        *,
        return_exceptions: bool = True,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """并行运行多个 Agent，返回名称→结果的映射。

        参数:
            tasks: [(agent_name, repo_path), ...] 列表。
            return_exceptions: True 时异常作为结果返回而非抛出。
            **kwargs: 传递给每个 Agent.run() 的额外参数。

        返回:
            {agent_name: result} 字典，失败时结果为对应异常对象。
        """

        async def _run_one(name: str, repo_path: str) -> tuple[str, Any]:
            agent = self.get(name)
            if agent is None:
                return name, ValueError(f"未注册的 Agent: {name}")
            try:
                result = await agent.run(repo_path, **kwargs)
                return name, result
            except Exception as exc:
                if return_exceptions:
                    return name, exc
                raise

        coros = [_run_one(name, path) for name, path in tasks]
        gathered = await asyncio.gather(*coros, return_exceptions=return_exceptions)

        # 如果最外层也 return_exceptions=True 且某个内部抛了异常，
        # gather 会返回异常对象而非 (name, result) 元组。此处做二次解包。
        results: dict[str, Any] = {}
        for item in gathered:
            if isinstance(item, BaseException):
                logger.error("Agent 调度异常: %s", item)
                continue
            name, result = item
            results[name] = result
        return results

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def clear(self) -> None:
        """清空所有注册的 Agent。"""
        self._agents.clear()
        logger.debug("AgentRegistry 已清空")

    def __len__(self) -> int:
        return len(self._agents)

    def __contains__(self, name: str) -> bool:
        return name in self._agents
