"""RepoLens Memory 层 — Agent 共享记忆。

提供线程安全的键值存储，Agent 可通过 SharedMemory
在分析过程中共享中间结果和上下文信息。

v2.2: Phase 4 Shared Memory Layer
"""

from .base import SharedMemory
from .memory_manager import MemoryManager

__all__ = [
    "SharedMemory",
    "MemoryManager",
]
