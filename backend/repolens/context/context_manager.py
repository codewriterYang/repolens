"""ContextManager — 上下文生命周期管理。

职责：
- 创建：调用 make_context() 构建不可变上下文
- 校验：检查上下文完整性（必填字段非空、路径存在等）
- 分发：向 Agent 统一传递上下文，替代原始传参方式
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

from .base import RepositoryContext
from .repository_context import make_context

logger = logging.getLogger(__name__)


class ContextManager:
    """上下文管理器。

    用法::

        manager = ContextManager()
        ctx = manager.create(repo_url, repo_path, job_id)
        manager.validate(ctx)       # 校验通过则正常，否则抛 ValueError
        agent.run(ctx)              # Agent 通过 Context 获取所需信息
    """

    def create(
        self,
        repo_url: str,
        repo_path: str,
        analysis_id: str,
    ) -> RepositoryContext:
        """创建分析上下文。

        参数:
            repo_url: 原始仓库 URL。
            repo_path: 克隆后的本地路径。
            analysis_id: 分析任务 ID。

        返回:
            不可变 RepositoryContext。
        """
        ctx = make_context(repo_url, repo_path, analysis_id)
        logger.debug(
            "创建上下文: analysis=%s repo=%s path=%s",
            ctx.analysis_id, ctx.repo_name, ctx.repo_path,
        )
        return ctx

    def validate(self, ctx: RepositoryContext) -> None:
        """校验上下文完整性。

        参数:
            ctx: 待校验的上下文。

        异常:
            ValueError: 必填字段为空或路径不存在。
        """
        if not ctx.repo_url:
            raise ValueError("repo_url 不能为空")
        if not ctx.repo_path:
            raise ValueError("repo_path 不能为空")
        if not ctx.analysis_id:
            raise ValueError("analysis_id 不能为空")
        if not os.path.isdir(ctx.repo_path):
            raise ValueError(f"repo_path 不存在或不是目录: {ctx.repo_path}")
        logger.debug(
            "上下文校验通过: analysis=%s repo=%s",
            ctx.analysis_id, ctx.repo_name,
        )

    def create_and_validate(
        self,
        repo_url: str,
        repo_path: str,
        analysis_id: str,
    ) -> RepositoryContext:
        """创建上下文并立即校验。

        等同于 create() + validate()。

        参数:
            repo_url: 原始仓库 URL。
            repo_path: 克隆后的本地路径。
            analysis_id: 分析任务 ID。

        返回:
            校验通过的不可变 RepositoryContext。
        """
        ctx = self.create(repo_url, repo_path, analysis_id)
        self.validate(ctx)
        return ctx
