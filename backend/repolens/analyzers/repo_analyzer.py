"""仓库分析器 — 使用 LLM 理解项目意图和结构。

读取 README、目录树和项目元数据；发送给 LLM 进行推理。
当 LLM 不可用时，回退到纯启发式分析。

设计：
  阶段 1（并行，无 LLM）：加载 README、构建目录树、提取元数据。
  阶段 2（LLM）：对使用模式、核心模块、风险进行结构化推理。
  阶段 3（解析）：JSON 解析（含截断修复）；启发式回退。

这是唯一需要 LLM 的分析器。LLM 失败不会导致整体崩溃：
分析器优雅降级到纯启发式输出。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Optional

from ..llm_service import LLMService
from ..schemas import InferredRisk, RepoResult, RiskLevel

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# LLM 系统提示词（发送给 LLM，保留英文以保证输出质量）
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are a senior software architect performing a code-review of a Python repository.

Given the README content, directory structure, and project metadata, analyze:
1. What this project does (2-4 usage patterns)
2. Which directories/files are the core modules (2-5)
3. A one-sentence summary (under 200 characters)
4. Project-level risks you can infer from the structure alone (2-4 items)

Output ONLY valid JSON — no markdown fences, no trailing commas — using exactly this schema:

{
  "usage_patterns": ["short phrase", "short phrase"],
  "core_modules": ["dirname", "dirname"],
  "summary": "One sentence describing the project.",
  "inferred_risks": [
    {
      "category": "架构风险|维护风险|安全风险|依赖风险|文档风险",
      "severity": "high|medium|low",
      "description": "One sentence risk description."
    }
  ]
}

Rules:
- usage_patterns: 2-4 short phrases (Chinese or English, match the README language)
- core_modules: 2-5 top-level directory/file names most critical to the project
- summary: a single sentence under 200 characters
- inferred_risks: 2-4 items only.  Only flag REAL risks you can see from structure.
  For example: no setup.py/pyproject.toml → dependency risk; no tests/ → maintenance risk;
  single monolithic file → architecture risk.  Do NOT invent risks.
- Be conservative — prefer fewer, higher-quality items.
- If you cannot determine something, use an empty list [] — never guess.
"""

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# 标志着项目身份 / 元数据的文件
_METADATA_FILES = (
    "pyproject.toml", "setup.py", "setup.cfg",
    "requirements.txt", "Pipfile", "Pipfile.lock",
    "poetry.lock", "environment.yml", "environment.yaml",
)

# 标志着测试基础设施的目录
_TEST_DIRS = {"tests", "test", "testing", "spec", "specs"}

# 标志着文档的目录
_DOC_DIRS = {"docs", "doc", "documentation", "examples"}

# README 文件名，按优先级搜索
_README_NAMES = (
    "README.md", "README.rst", "README.txt",
    "README", "readme.md", "readme.rst",
)

# README 最大读取字符数（控制 token 消耗）
_README_MAX_CHARS = 8000


# ---------------------------------------------------------------------------
# 分析器
# ---------------------------------------------------------------------------


class RepoAnalyzer:
    """使用 README + 目录树 + 元数据通过 LLM 分析仓库意图。

    用法::

        analyzer = RepoAnalyzer(llm_service)
        result = await analyzer.run("/path/to/cloned/repo", "https://github.com/...")

    结果是 RepoResult Pydantic 模型。LLM 失败时产出纯启发式结果 —
    只有在整体失败时才会填充 error 字段。
    """

    LLM_TIMEOUT = 180         # LLM 整体超时（秒），预留 3 次请求+退避
    METADATA_MAX_BYTES = 4096  # 每个元数据文件的最大读取字节数

    def __init__(self, llm: LLMService) -> None:
        self._llm = llm

    # ------------------------------------------------------------------
    # 公开入口
    # ------------------------------------------------------------------

    async def run(self, repo_path: str, repo_url: str) -> RepoResult:
        """分析仓库结构和意图。

        参数:
            repo_path: 克隆仓库的绝对路径。
            repo_url: 原始 URL（用于缓存键和启发式分析）。

        返回:
            包含使用模式、核心模块、摘要和推断风险的 RepoResult。
            从不抛出异常 — 错误会捕获到结果对象的 error 字段中。
        """
        start = time.monotonic()

        try:
            # ------------------------------------------------------------------
            # 阶段 1：并行加载输入（尚未涉及 LLM）
            # ------------------------------------------------------------------
            readme, tree, metadata = await asyncio.gather(
                self._load_readme(repo_path),
                self._build_tree(repo_path),
                self._extract_metadata(repo_path),
            )

            if not readme and not tree:
                return RepoResult(
                    duration_ms=int((time.monotonic() - start) * 1000),
                    error="未找到 README 或源码文件",
                )

            # ------------------------------------------------------------------
            # 阶段 2：LLM 推理（可能失败 → 回退到启发式分析）
            # ------------------------------------------------------------------
            llm_data: Optional[dict] = None
            llm_error: Optional[str] = None

            try:
                content_hash = hashlib.sha256(
                    (readme + tree + json.dumps(metadata, sort_keys=True)).encode()
                ).hexdigest()[:16]
                cache_key = self._llm.make_cache_key(repo_url, content_hash)

                raw = await asyncio.wait_for(
                    self._llm.chat(
                        system_prompt=SYSTEM_PROMPT,
                        user_prompt=self._build_user_prompt(readme, tree, metadata),
                        temperature=0.3,
                        max_tokens=1024,
                        cache_key=cache_key,
                    ),
                    timeout=self.LLM_TIMEOUT,
                )
                llm_data = self._parse_llm_json(raw)

            except asyncio.TimeoutError:
                llm_error = "LLM 分析超时"
                logger.warning("RepoAnalyzer: %s", llm_error)
            except Exception as exc:
                llm_error = f"LLM 调用失败: {exc}"
                logger.warning("RepoAnalyzer: %s", llm_error)

            # ------------------------------------------------------------------
            # 阶段 3：构建结果 — 合并 LLM 数据与启发式分析
            # ------------------------------------------------------------------
            return self._build_result(
                start=start,
                llm_data=llm_data,
                llm_error=llm_error,
                readme=readme,
                tree=tree,
                metadata=metadata,
                repo_path=repo_path,
            )

        except Exception as exc:
            logger.exception("RepoAnalyzer.run: unhandled error")
            return RepoResult(
                duration_ms=int((time.monotonic() - start) * 1000),
                error=str(exc),
            )

    # ------------------------------------------------------------------
    # 阶段 1 辅助方法 — 文件 I/O（在线程中运行以避免阻塞）
    # ------------------------------------------------------------------

    async def _load_readme(self, repo_path: str) -> str:
        """加载 README 内容的前 N 个字符。

        以不区分大小写的方式搜索常见的 README 文件名，
        然后回退到 glob 匹配任何以 'readme' 开头的文件。
        """

        def _read() -> str:
            # 优先：精确的常见名称
            for name in _README_NAMES:
                p = os.path.join(repo_path, name)
                if os.path.isfile(p):
                    try:
                        with open(p, "r", encoding="utf-8", errors="replace") as f:
                            return f.read(_README_MAX_CHARS)
                    except OSError:
                        continue

            # 回退：glob 匹配任何 readme* 开头的文件
            try:
                for entry in Path(repo_path).iterdir():
                    if entry.is_file() and entry.name.lower().startswith("readme"):
                        try:
                            with open(entry, "r", encoding="utf-8", errors="replace") as f:
                                return f.read(_README_MAX_CHARS)
                        except OSError:
                            continue
            except OSError:
                pass

            return ""

        return await asyncio.to_thread(_read)

    async def _build_tree(self, repo_path: str, max_depth: int = 3) -> str:
        """构建目录树字符串（深度受限）。

        只包含与源码相关的文件以聚焦 LLM 提示词。
        隐藏目录和常见非源码目录会被排除。
        """

        def _build() -> str:
            excluded = {
                "node_modules", ".git", "__pycache__",
                ".venv", "venv", "env", ".tox",
                "build", "dist", ".eggs", "*.egg-info",
                "site-packages", "__pypackages__", ".mypy_cache",
                ".pytest_cache", ".ruff_cache",
            }
            lines: list[str] = []
            root_name = os.path.basename(repo_path.rstrip(os.sep)) or "repo"

            for root, dirs, files in os.walk(repo_path):
                rel = os.path.relpath(root, repo_path)
                depth = 0 if rel == "." else rel.count(os.sep) + 1
                if depth > max_depth:
                    dirs.clear()
                    continue

                # 就地过滤排除/隐藏目录
                dirs[:] = [
                    d for d in dirs
                    if d not in excluded and not d.startswith(".")
                ]
                dirs.sort()

                indent = "  " * depth
                dirname = root_name if depth == 0 else os.path.basename(root)
                lines.append(f"{indent}{dirname}/")

                # 只展示关键文件
                shown = 0
                for f in sorted(files):
                    if shown >= 25:
                        lines.append(f"{indent}  ... ({len(files) - 25} more files)")
                        break
                    if f.endswith((
                        ".py", ".md", ".rst", ".txt",
                        ".yml", ".yaml", ".toml", ".cfg", ".ini",
                        ".json", ".cfg",
                    )):
                        lines.append(f"{indent}  {f}")
                        shown += 1

            return "\n".join(lines)

        return await asyncio.to_thread(_build)

    async def _extract_metadata(self, repo_path: str) -> dict:
        """从配置文件中提取项目元数据。

        返回字典包含:
          - has_setup: bool
          - has_tests: bool
          - has_docs: bool
          - dependencies: list[str]（仅顶层依赖名）
          - python_requires: str 或 None
          - project_name: str 或 None
        """

        def _extract() -> dict:
            result: dict = {
                "has_setup": False,
                "has_tests": False,
                "has_docs": False,
                "dependencies": [],
                "python_requires": None,
                "project_name": None,
            }

            # 检查 test/doc 目录
            try:
                entries = {e.name.lower(): e for e in Path(repo_path).iterdir()}
            except OSError:
                entries = {}

            result["has_tests"] = bool(
                set(e.name for e in entries.values() if e.is_dir()) & _TEST_DIRS
            )
            result["has_docs"] = bool(
                set(e.name for e in entries.values() if e.is_dir()) & _DOC_DIRS
            )

            # 尝试 pyproject.toml（PEP 621 / Poetry）
            pyproject = entries.get("pyproject.toml")
            if pyproject and pyproject.is_file():
                result["has_setup"] = True
                try:
                    content = pyproject.read_text(encoding="utf-8", errors="replace")
                    result = self._parse_pyproject_toml(content, result)
                except OSError:
                    pass

            # 尝试 setup.py / setup.cfg
            if not result["has_setup"]:
                for name in ("setup.py", "setup.cfg"):
                    f = entries.get(name)
                    if f and f.is_file():
                        result["has_setup"] = True
                        try:
                            content = f.read_text(encoding="utf-8", errors="replace")
                            result = self._parse_setup_like(content, result)
                        except OSError:
                            pass
                        break

            # 尝试 requirements.txt 获取依赖
            req_file = entries.get("requirements.txt")
            if req_file and req_file.is_file():
                try:
                    for line in req_file.read_text(
                        encoding="utf-8", errors="replace"
                    ).splitlines()[:30]:
                        line = line.strip()
                        if line and not line.startswith("#") and not line.startswith("-"):
                            # 提取版本说明符前的包名
                            pkg = re.split(r"[<>=!~;\s]", line)[0].strip()
                            if pkg:
                                result["dependencies"].append(pkg)
                except OSError:
                    pass

            return result

        return await asyncio.to_thread(_extract)

    # ------------------------------------------------------------------
    # 元数据解析辅助方法
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_pyproject_toml(content: str, result: dict) -> dict:
        """从 pyproject.toml 中提取项目名、依赖、python_requires。

        使用正则而非 TOML 解析器，避免引入额外依赖。
        这是有意宽松的 — 我们只需要信号，不需要精确。
        """
        # [project] name (PEP 621)
        m = re.search(r'name\s*=\s*"([^"]+)"', content)
        if m:
            result["project_name"] = m.group(1)

        # python_requires
        m = re.search(r'requires-python\s*=\s*"([^"]+)"', content)
        if m:
            result["python_requires"] = m.group(1)

        # Dependencies 来自 [project] dependencies（PEP 621）
        dep_section = re.search(
            r'dependencies\s*=\s*\[(.*?)\]', content, re.DOTALL
        )
        if dep_section:
            for dep in re.findall(r'"([^"]+)"', dep_section.group(1)):
                pkg = re.split(r"[<>=!~;\s]", dep)[0].strip()
                if pkg and pkg not in result["dependencies"]:
                    result["dependencies"].append(pkg)

        # Dependencies 来自 [tool.poetry.dependencies]
        poetry_section = re.search(
            r'\[tool\.poetry\.dependencies\](.*?)(?=\[|$)', content, re.DOTALL
        )
        if poetry_section:
            for line in poetry_section.group(1).splitlines():
                line = line.strip()
                if line and not line.startswith("#") and not line.startswith("["):
                    pkg = re.split(r"\s*=\s*", line)[0].strip()
                    if pkg and pkg != "python" and pkg not in result["dependencies"]:
                        result["dependencies"].append(pkg)

        return result

    @staticmethod
    def _parse_setup_like(content: str, result: dict) -> dict:
        """从 setup.py/setup.cfg 提取项目名和依赖。"""
        # setup.py: name="xxx"
        m = re.search(r'name\s*=\s*["\']([^"\']+)["\']', content)
        if m:
            result["project_name"] = m.group(1)

        # setup.py: install_requires=[...]
        deps = re.search(
            r'install_requires\s*=\s*\[(.*?)\]', content, re.DOTALL
        )
        if deps:
            for dep in re.findall(r'"([^"]+)"', deps.group(1)):
                pkg = re.split(r"[<>=!~;\s]", dep)[0].strip()
                if pkg and pkg not in result["dependencies"]:
                    result["dependencies"].append(pkg)

        # setup.cfg: [options] install_requires = ...
        for line in content.splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and not stripped.startswith("["):
                if "=" not in stripped:
                    pkg = re.split(r"[<>=!~;\s]", stripped)[0].strip()
                    if pkg and pkg not in result["dependencies"]:
                        result["dependencies"].append(pkg)

        return result

    # ------------------------------------------------------------------
    # 阶段 2 辅助 — LLM
    # ------------------------------------------------------------------

    def _build_user_prompt(
        self, readme: str, tree: str, metadata: dict
    ) -> str:
        """将收集到的输入组装为用户提示词。

        将元数据作为结构化提示包含在内，这样 LLM 就不需要
        猜测是否存在测试/文档/setup 文件。
        """
        parts: list[str] = []

        if readme:
            parts.append(f"## README (first {_README_MAX_CHARS} chars)\n```\n{readme}\n```")

        if tree:
            parts.append(f"## Directory Structure (depth 3)\n```\n{tree}\n```")

        # Metadata hints
        hints: list[str] = []
        if metadata.get("project_name"):
            hints.append(f"Project name: {metadata['project_name']}")
        if metadata.get("has_setup"):
            hints.append("Has packaging config (setup.py or pyproject.toml)")
        else:
            hints.append("No packaging config found — may be a script, not a package")
        if metadata.get("has_tests"):
            hints.append("Has test directory")
        else:
            hints.append("No test directory found")
        if metadata.get("has_docs"):
            hints.append("Has docs directory")
        if metadata.get("dependencies"):
            hints.append(
                f"Dependencies: {', '.join(metadata['dependencies'][:10])}"
            )
        if metadata.get("python_requires"):
            hints.append(f"Python requires: {metadata['python_requires']}")

        if hints:
            parts.append("## Metadata Hints\n" + "\n".join(f"- {h}" for h in hints))

        return "\n\n".join(parts)

    @staticmethod
    def _parse_llm_json(raw: str) -> Optional[dict]:
        """解析 LLM 输出为 JSON，含截断修复。

        LLM 有时在达到 max_tokens 上限时产生截断的 JSON。
        我们尝试通过关闭未闭合的大括号/方括号来修复。
        """
        if not raw or not raw.strip():
            return None

        raw = raw.strip()

        # Strip markdown fences if present
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*\n?", "", raw)
            raw = re.sub(r"\n?```\s*$", "", raw)

        # Try direct parse first
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass

        # Attempt truncation repair: close unclosed structures
        repaired = _repair_truncated_json(raw)
        if repaired:
            try:
                data = json.loads(repaired)
                if isinstance(data, dict):
                    logger.info("RepoAnalyzer: repaired truncated JSON")
                    return data
            except json.JSONDecodeError:
                pass

        logger.warning("RepoAnalyzer: could not parse LLM JSON output")
        return None

    # ------------------------------------------------------------------
    # 阶段 3 — 结果组装
    # ------------------------------------------------------------------

    def _build_result(
        self,
        *,
        start: float,
        llm_data: Optional[dict],
        llm_error: Optional[str],
        readme: str,
        tree: str,
        metadata: dict,
        repo_path: str,
    ) -> RepoResult:
        """从 LLM 数据 + 启发式分析组装最终 RepoResult。

        策略：
        - LLM 数据在可用时作为权威来源。
        - 启发式分析在 LLM 缺失或不完整时填补空缺。
        - 当 LLM 未提供任何风险时，添加纯启发式风险。
        """
        if llm_data:
            patterns = llm_data.get("usage_patterns", [])[:5]
            modules = llm_data.get("core_modules", [])[:5]
            summary = llm_data.get("summary", "")
            risks = self._parse_inferred_risks(llm_data.get("inferred_risks", []))
        else:
            patterns, modules, summary, risks = self._heuristic_analysis(
                readme, tree, metadata, repo_path
            )

        # Heuristic README quality score (computed locally, not from LLM)
        quality = self._score_readme(readme, metadata)

        return RepoResult(
            usage_patterns=patterns if patterns else [],
            core_modules=modules if modules else [],
            summary=summary or "",
            readme_quality_score=quality,
            inferred_risks=risks,
            duration_ms=int((time.monotonic() - start) * 1000),
            error=llm_error if llm_error and not llm_data else None,
        )

    def _parse_inferred_risks(
        self, raw_risks: list
    ) -> list[InferredRisk]:
        """将 LLM 返回的风险字典解析为 InferredRisk 模型。

        验证并规范化：未知严重度 → medium，未知类别 → '其他风险'，
        空描述 → 跳过。
        """
        valid_categories = {
            "架构风险", "维护风险", "安全风险", "依赖风险", "文档风险", "其他风险",
        }
        valid_severities = {"high", "medium", "low"}

        results: list[InferredRisk] = []
        for item in raw_risks[:4]:  # Cap at 4
            if not isinstance(item, dict):
                continue
            desc = str(item.get("description", "")).strip()
            if not desc:
                continue

            cat = str(item.get("category", "其他风险")).strip()
            if cat not in valid_categories:
                cat = "其他风险"

            sev = str(item.get("severity", "medium")).strip().lower()
            if sev not in valid_severities:
                sev = "medium"

            results.append(InferredRisk(
                category=cat,
                severity=RiskLevel(sev),
                description=desc,
            ))

        return results

    # ------------------------------------------------------------------
    # 启发式回退（无 LLM 可用时）
    # ------------------------------------------------------------------

    def _heuristic_analysis(
        self,
        readme: str,
        tree: str,
        metadata: dict,
        repo_path: str,
    ) -> tuple[list[str], list[str], str, list[InferredRisk]]:
        """在不使用 LLM 的情况下产出最佳努力分析。

        使用：
        - README 第一行作为摘要
        - 顶级目录作为核心模块
        - 元数据信号推断风险
        """
        # Summary: first non-empty, non-heading line of README
        summary = ""
        if readme:
            for line in readme.splitlines():
                stripped = line.strip()
                if stripped and not stripped.startswith("#"):
                    summary = stripped[:200]
                    break

        # Core modules: top-level directories that contain .py files
        modules: list[str] = []
        try:
            for entry in sorted(Path(repo_path).iterdir()):
                if entry.is_dir() and not entry.name.startswith("."):
                    if entry.name not in {
                        "tests", "test", "docs", "doc", "examples",
                        "node_modules", "__pycache__", ".git",
                        "venv", ".venv", "env", "build", "dist",
                    }:
                        modules.append(entry.name)
        except OSError:
            pass
        modules = modules[:5]

        # Usage patterns: derive from project name + README keywords
        patterns: list[str] = []
        if metadata.get("project_name"):
            patterns.append(f"项目: {metadata['project_name']}")
        if readme:
            lower = readme.lower()
            keyword_map = {
                "api": "提供 API 服务",
                "cli": "命令行工具",
                "web": "Web 应用",
                "framework": "开发框架",
                "library": "代码库/SDK",
                "machine learning": "机器学习",
                "ml": "机器学习",
                "data": "数据处理",
                "bot": "聊天机器人",
                "test": "测试工具",
                "docker": "容器化部署",
                "database": "数据库相关",
                "爬虫": "网络爬虫",
                "crawl": "网络爬虫",
                "scrape": "网络爬虫",
            }
            for kw, label in keyword_map.items():
                if kw in lower:
                    patterns.append(label)
            patterns = list(dict.fromkeys(patterns))[:4]  # dedup, limit

        # Inferred risks: from metadata signals
        risks = self._heuristic_risks(readme, metadata, tree)

        return patterns, modules, summary, risks

    def _heuristic_risks(
        self, readme: str, metadata: dict, tree: str
    ) -> list[InferredRisk]:
        """从元数据中的可观察信号生成风险。"""
        risks: list[InferredRisk] = []

        # No packaging config → dependency/install risk
        if not metadata.get("has_setup"):
            risks.append(InferredRisk(
                category="依赖风险",
                severity=RiskLevel.MEDIUM,
                description="未找到 pyproject.toml 或 setup.py，依赖管理可能不规范",
            ))

        # No tests directory → maintenance risk
        if not metadata.get("has_tests"):
            risks.append(InferredRisk(
                category="维护风险",
                severity=RiskLevel.HIGH,
                description="未发现测试目录，缺少自动化测试覆盖",
            ))

        # No docs directory + short README → documentation risk
        if not metadata.get("has_docs") and len(readme) < 500:
            risks.append(InferredRisk(
                category="文档风险",
                severity=RiskLevel.MEDIUM,
                description="README 内容较短且无独立文档目录，文档可能不完善",
            ))

        # Very few dependencies but has_setup → might be a simple script
        if metadata.get("has_setup") and len(metadata.get("dependencies", [])) == 0:
            risks.append(InferredRisk(
                category="架构风险",
                severity=RiskLevel.LOW,
                description="项目有打包配置但未声明依赖，可能为简单脚本或依赖管理不规范",
            ))

        return risks

    # ------------------------------------------------------------------
    # README 质量评分
    # ------------------------------------------------------------------

    @staticmethod
    def _score_readme(readme: str, metadata: dict) -> int:
        """使用启发式方法对 README 质量进行 0-100 评分。

        维度：
        - 长度 (0-25 分): 越长越好，但有递减效应
        - 结构 (0-25 分): 是否含有标题、代码块、列表
        - 徽章 (0-15 分): CI/coverage/pypi 徽章表示项目成熟度
        - 安装说明 (0-15 分): 是否含有安装指引
        - 示例 (0-20 分): 是否含有使用示例 / 代码片段
        """
        if not readme:
            return 0

        score = 0

        # --- Length (0-25) ---
        length = len(readme)
        if length >= 3000:
            score += 25
        elif length >= 1500:
            score += 20
        elif length >= 500:
            score += 15
        elif length >= 200:
            score += 8
        else:
            score += 3

        # --- Structure (0-25) ---
        has_headings = bool(re.search(r"^#{1,3}\s", readme, re.MULTILINE))
        has_code_blocks = "```" in readme
        has_lists = bool(re.search(r"^\s*[-*+]\s", readme, re.MULTILINE))
        has_table = "|" in readme and "---" in readme

        if has_headings:
            score += 10
        if has_code_blocks:
            score += 8
        if has_lists:
            score += 4
        if has_table:
            score += 3

        # --- Badges (0-15) ---
        badge_count = len(re.findall(
            r'!\[.*?\]\(https?://img\.shields\.io/',
            readme,
        ))
        if badge_count >= 5:
            score += 15
        elif badge_count >= 2:
            score += 10
        elif badge_count >= 1:
            score += 5

        # --- Installation instructions (0-15) ---
        lower = readme.lower()
        has_install = any(
            phrase in lower
            for phrase in ("pip install", "poetry install", "pipenv install",
                           "conda install", "npm install", "yarn add",
                           "git clone", "install", "安装")
        )
        if has_install:
            score += 15

        # --- Usage examples (0-20) ---
        has_examples = any(
            phrase in lower
            for phrase in ("usage", "example", "quickstart", "getting started",
                           "quick start", "tutorial", "使用", "示例", "快速开始")
        )
        if has_examples and has_code_blocks:
            score += 20
        elif has_examples:
            score += 10

        return min(100, max(0, score))


# ---------------------------------------------------------------------------
# JSON truncation repair utility
# ---------------------------------------------------------------------------


def _repair_truncated_json(raw: str) -> Optional[str]:
    """Attempt to repair JSON that was truncated by token limits.

    Strategy: count open/close brackets and braces, append the missing
    closing characters in the correct order.  This is a best-effort
    heuristic — it works for the flat-ish JSON the LLM produces but
    won't fix deeply nested truncation.
    """
    if not raw:
        return None

    # Remove trailing comma (common LLM artifact)
    raw = raw.rstrip()
    if raw.endswith(","):
        raw = raw[:-1]

    # Stack-based repair
    stack: list[str] = []
    in_string = False
    escape_next = False

    for ch in raw:
        if escape_next:
            escape_next = False
            continue
        if ch == "\\":
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue

        if ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]":
            if stack and stack[-1] == ch:
                stack.pop()
            # else: mismatched — don't try to fix, let it fail

    if not stack:
        return None  # nothing to repair

    # Close in reverse order
    closing = "".join(reversed(stack))

    # Close any unclosed string
    if in_string:
        closing = '"' + closing

    return raw + closing
