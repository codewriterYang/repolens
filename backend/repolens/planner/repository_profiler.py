"""RepositoryProfiler — 仓库基础信息分析。

扫描仓库目录，提取用于决策的元信息：
文件数、是否包含 README、CI/CD 配置、Docker 配置等。

输入: repo_path
输出: dict {language, file_count, has_readme, has_ci, has_docker}
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class RepositoryProfiler:
    """分析仓库基础特征，供 PlanningRules 做决策。

    用法::

        profiler = RepositoryProfiler()
        profile = profiler.analyze(repo_path)
        # {"language": "python", "file_count": 1118, "has_readme": True, ...}
    """

    def analyze(self, repo_path: str) -> dict:
        """扫描仓库目录并提取决策元信息。

        参数:
            repo_path: 克隆仓库的绝对路径。

        返回:
            dict 包含 language, file_count, has_readme, has_ci, has_docker。
        """
        from pathlib import Path

        root = Path(repo_path)
        if not root.is_dir():
            return self._empty_profile()

        # 统计 .py 文件数
        py_files = list(root.rglob("*.py"))
        excluded = {
            "node_modules", ".git", "__pycache__",
            ".venv", "venv", "env", ".tox",
            "build", "dist", ".eggs", "site-packages",
        }
        py_files = [f for f in py_files if not set(f.parts) & excluded]
        file_count = len(py_files)

        # README 检测
        readme_names = {
            "README.md", "README.rst", "README.txt",
            "README", "readme.md", "readme.rst",
        }
        has_readme = any(
            (root / name).is_file() for name in readme_names
        ) or any(
            f.is_file() and f.name.lower().startswith("readme")
            for f in root.iterdir()
        )

        # CI/CD 检测
        workflows_dir = root / ".github" / "workflows"
        has_ci = workflows_dir.is_dir() and any(
            f.suffix in (".yml", ".yaml") for f in workflows_dir.iterdir()
        ) if workflows_dir.is_dir() else False

        # Docker 检测
        has_docker = (root / "Dockerfile").is_file() or (root / "docker-compose.yml").is_file()

        profile = {
            "language": "python",
            "file_count": file_count,
            "has_readme": has_readme,
            "has_ci": has_ci,
            "has_docker": has_docker,
        }

        logger.debug(
            "RepositoryProfiler: files=%d readme=%s ci=%s docker=%s",
            file_count, has_readme, has_ci, has_docker,
        )
        return profile

    @staticmethod
    def _empty_profile() -> dict:
        return {
            "language": "unknown",
            "file_count": 0,
            "has_readme": False,
            "has_ci": False,
            "has_docker": False,
        }
