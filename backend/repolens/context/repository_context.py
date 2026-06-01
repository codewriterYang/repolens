"""仓库上下文工厂函数。

提供便捷的 create_context() 方法，从原始参数构建 RepositoryContext。
"""

from __future__ import annotations

import os

from .base import RepositoryContext


def make_context(
    repo_url: str,
    repo_path: str,
    analysis_id: str,
) -> RepositoryContext:
    """从分析参数构建 RepositoryContext。

    参数:
        repo_url: 原始仓库 URL。
        repo_path: 克隆后的本地路径。
        analysis_id: 分析任务 ID。

    返回:
        不可变的 RepositoryContext 实例。
    """
    # 从 URL 或本地路径中提取仓库名
    repo_name = _extract_repo_name(repo_url)

    return RepositoryContext(
        repo_url=repo_url,
        repo_path=repo_path,
        repo_name=repo_name,
        analysis_id=analysis_id,
    )


def _extract_repo_name(url_or_path: str) -> str:
    """从 GitHub URL 或本地路径中提取仓库名。

    示例:
        https://github.com/tiangolo/fastapi → "fastapi"
        https://github.com/tiangolo/fastapi.git → "fastapi"
        C:/Users/admin/my-project → "my-project"
        /home/user/repo → "repo"
    """
    # 去掉末尾的 .git 和 /
    cleaned = url_or_path.rstrip("/")
    if cleaned.endswith(".git"):
        cleaned = cleaned[:-4]

    # URL 格式：取最后一个路径段
    if "://" in cleaned:
        name = cleaned.rsplit("/", 1)[-1]
    else:
        # 本地路径
        name = os.path.basename(cleaned) or cleaned.rsplit("/", 1)[-1] or cleaned.rsplit("\\", 1)[-1]

    return name or "unknown"
