"""SharedMemory — 线程安全的键值存储。

Agent 通过 SharedMemory 在分析过程中共享中间结果，
例如 StaticAgent 发现的高风险文件列表可供后续 Agent 查询。

使用 threading.RLock 保证多线程访问安全（兼容 asyncio.to_thread 场景）。
"""

from __future__ import annotations

import threading
from typing import Any, Optional


class SharedMemory:
    """线程安全的键值存储。

    Agent 可通过此对象在分析过程中共享数据，
    无需通过 Orchestrator 中转。

    用法::

        memory = SharedMemory()
        memory.set("static.high_risk_files", ["a.py", "b.py"])
        files = memory.get("static.high_risk_files")
        if memory.has("static.high_risk_files"):
            ...
    """

    def __init__(self) -> None:
        self._store: dict[str, Any] = {}
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # 读写接口
    # ------------------------------------------------------------------

    def set(self, key: str, value: Any) -> None:
        """写入键值对。

        参数:
            key: 键名，建议使用 "agent_name.field_name" 格式避免冲突。
            value: 任意可序列化的值。
        """
        with self._lock:
            self._store[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        """读取键值。

        参数:
            key: 键名。
            default: 键不存在时返回的默认值。

        返回:
            存储的值，键不存在时返回 default。
        """
        with self._lock:
            return self._store.get(key, default)

    def has(self, key: str) -> bool:
        """检查键是否存在。"""
        with self._lock:
            return key in self._store

    def delete(self, key: str) -> None:
        """删除键值对。键不存在时不报错。"""
        with self._lock:
            self._store.pop(key, None)

    def keys(self) -> list[str]:
        """返回所有键名列表。"""
        with self._lock:
            return list(self._store.keys())

    # ------------------------------------------------------------------
    # 批量操作
    # ------------------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        """返回当前存储的只读快照（浅拷贝）。"""
        with self._lock:
            return dict(self._store)

    def clear(self) -> None:
        """清空所有存储。"""
        with self._lock:
            self._store.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)

    def __repr__(self) -> str:
        with self._lock:
            return f"SharedMemory({len(self._store)} keys: {list(self._store.keys())[:5]})"
