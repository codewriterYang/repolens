"""MemoryManager — SharedMemory 生命周期管理。

职责：
- create(): 每次流水线启动时创建新的 SharedMemory 实例
- clear(): 清空当前 SharedMemory
- get_memory(): 获取当前 SharedMemory 引用
"""

from __future__ import annotations

import logging
from typing import Optional

from .base import SharedMemory

logger = logging.getLogger(__name__)


class MemoryManager:
    """SharedMemory 生命周期管理器。

    用法::

        manager = MemoryManager()
        memory = manager.create()              # 流水线启动
        agent.inject_memory(memory)            # 注入 Agent
        # ... 分析过程中 Agent 读写 ...
        manager.clear()                        # 流水线结束清理

    注意：MemoryManager 只管理一个 SharedMemory 实例。
    每次 create() 会创建新实例并丢弃旧引用。
    """

    def __init__(self) -> None:
        self._memory: Optional[SharedMemory] = None

    def create(self) -> SharedMemory:
        """创建新的 SharedMemory 实例。

        旧的 SharedMemory 引用被丢弃（由 Python GC 回收）。
        每次流水线应调用一次 create()。

        返回:
            新的 SharedMemory 实例。
        """
        self._memory = SharedMemory()
        logger.debug("创建 SharedMemory 实例")
        return self._memory

    def clear(self) -> None:
        """清空当前 SharedMemory 中的所有数据。"""
        if self._memory is not None:
            self._memory.clear()
            logger.debug("SharedMemory 已清空")

    def get_memory(self) -> Optional[SharedMemory]:
        """获取当前 SharedMemory 实例。

        返回:
            SharedMemory 实例，尚未 create() 时返回 None。
        """
        return self._memory
