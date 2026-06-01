"""SharedMemory 辅助工具。

提供针对 SharedMemory 的便捷操作函数，
例如按前缀筛选、批量写入等。后续 Agent 协作阶段会用到。
"""

from __future__ import annotations

from typing import Any

from .base import SharedMemory


def get_by_prefix(
    memory: SharedMemory, prefix: str,
) -> dict[str, Any]:
    """按前缀筛选 SharedMemory 中的键值对。

    例如 prefix="static." 返回 StaticAgent 写入的所有数据。

    参数:
        memory: SharedMemory 实例。
        prefix: 键名前缀。

    返回:
        匹配前缀的 {key: value} 字典。
    """
    return {
        key: memory.get(key)
        for key in memory.keys()
        if key.startswith(prefix)
    }


def batch_set(memory: SharedMemory, data: dict[str, Any]) -> None:
    """批量写入键值对。

    参数:
        memory: SharedMemory 实例。
        data: 要写入的 {key: value} 字典。
    """
    for key, value in data.items():
        memory.set(key, value)
