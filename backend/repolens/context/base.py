"""RepositoryContext — 不可变的分析上下文。

封装一次分析任务所需的所有元信息，作为 Agent.run() 的唯一入参。
使用 frozen dataclass 保证上下文在分析过程中不被修改。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class RepositoryContext:
    """单次分析任务的不可变上下文。

    属性:
        repo_url: 原始仓库 URL（GitHub 或本地路径）。
        repo_path: 克隆后的本地文件系统路径。
        repo_name: 仓库名（从 URL 提取，如 "fastapi"）。
        analysis_id: 此次分析的唯一 job_id。
        started_at: 分析启动时间戳。
    """

    repo_url: str
    repo_path: str
    repo_name: str
    analysis_id: str
    started_at: datetime = field(default_factory=datetime.now)
