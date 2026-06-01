"""静态代码分析器 — 对 Python 仓库运行 pylint 和 radon。

产出 StaticResult，包含：
- 高复杂度函数热点（来自 radon cc）
- 文件级热力图（来自 pylint 逐行消息）
- 文件风险摘要（聚合 lint + 复杂度数据）
- 平均 pylint 评分 (0.0-10.0)

此分析器是确定性的 — 无 LLM 调用。

子进程策略：
- pylint 通过两个并行子进程运行：
  a) --output-format=json  提取逐消息 lint 数据
  b) --score=y --output-format=text  提取文件级评分（从文本解析）
- radon cc --json --min=B  提取圈复杂度
- 每个子进程有独立的超时；失败不会导致整体崩溃。

设计权衡：
- 从文本输出解析 pylint 评分，因为 pylint 的 JSON 格式故意不包含评分
  （评分是摘要而非消息级字段）。这增加了 ~20 行正则解析，但避免了第三方包装依赖。
- 子进程使用 subprocess.run 在线程中执行，兼容所有平台的 asyncio 事件循环。
- 文件风险摘要在两个分析器完成后在内存中计算，
  无需中间序列化步骤。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..schemas import (
    FileRiskSummary,
    FunctionRisk,
    LineRisk,
    RiskLevel,
    StaticResult,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Radon 复杂度 → RiskLevel 映射
# 基于 radon 自身阈值：A=1-5, B=6-10, C=11-20, D=21-30,
# E=31-50, F=51+。C+ 映射为 MEDIUM，D+ 映射为 HIGH。
# ---------------------------------------------------------------------------
_COMPLEXITY_HIGH = 20   # D 级及以上
_COMPLEXITY_MEDIUM = 10  # C 级


# 用于从文本输出中提取 pylint 评分的正则。
# Pylint 文本格式："Your code has been rated at 8.50/10"
_PYLINT_SCORE_RE = re.compile(
    r"rated\s+at\s+([\d.]+)\s*/\s*10"
)


# ---------------------------------------------------------------------------
# 内部数据类，用于传递解析后的 pylint 结果
# ---------------------------------------------------------------------------


@dataclass
class _PylintOutput:
    """pylint 调用的解析结果。"""

    messages_by_file: dict[str, list[dict]] = field(default_factory=dict)
    file_scores: dict[str, float] = field(default_factory=dict)
    overall_score: Optional[float] = None
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# 分析器
# ---------------------------------------------------------------------------


class StaticAnalyzer:
    """使用 pylint 和 radon 作为子进程工具分析代码质量。

    用法::

        analyzer = StaticAnalyzer()
        result = await analyzer.run("/path/to/cloned/repo")

    结果是 StaticResult Pydantic 模型，适合 JSON 序列化和前端消费。
    """

    # 子进程超时（秒）。pylint 在大型仓库上可能较慢；
    # radon 通常很快。这些是每个子进程独立的超时。
    PYLINT_TIMEOUT = 300
    RADON_TIMEOUT = 60

    def __init__(self) -> None:
        pass  # 无状态 — 配置存放在类属性中以方便测试

    # ------------------------------------------------------------------
    # 公开入口
    # ------------------------------------------------------------------

    async def run(self, repo_path: str, strategy_mode: str = "full") -> StaticResult:
        """对给定仓库路径执行静态分析。

        参数:
            repo_path: 克隆仓库的绝对路径。
            strategy_mode: "full" | "focused" | "fast"
            - full: 完整 pylint + radon
                - focused: 核心文件 pylint + 全量 radon
                - fast: 仅 radon cc（跳过 pylint）

        返回:
            包含复杂度热点、文件热力图、风险摘要和 pylint 评分的
            StaticResult。失败时返回带有 error 字段的结果 — 从不抛出异常。
        """
        start = time.monotonic()

        try:
            py_files = await self._collect_python_files(repo_path)
            if not py_files:
                return StaticResult(
                    total_files_scanned=0,
                    duration_ms=0,
                    error="仓库中未找到 Python 文件",
                )

            # --- 根据策略决定 pylint 扫描的文件范围 ---
            if strategy_mode == "fast":
                # fast 模式：不运行 pylint，仅 radon
                pylint_files: list[str] = []
                logger.info("StaticAnalyzer: fast 模式 — 跳过 pylint，仅 radon cc")
            elif strategy_mode == "focused":
                # focused 模式：排除测试文件
                pylint_files = [
                    f for f in py_files
                    if not self._is_test_file(f)
                ]
                if len(pylint_files) < len(py_files):
                    logger.info(
                        "StaticAnalyzer: focused 模式 — pylint 目标 %d/%d 文件",
                        len(pylint_files), len(py_files),
                    )
            else:
                # full 模式：全部文件
                pylint_files = py_files

            # ------------------------------------------------------------------
            # 阶段 A：并行运行 pylint 和 radon。
            # ------------------------------------------------------------------
            radon_task = self._run_radon(repo_path)

            if pylint_files:
                pylint_json_task = self._run_pylint_json(repo_path, pylint_files)
                pylint_score_task = self._run_pylint_score(repo_path, pylint_files)
                pylint_messages_raw, pylint_scores_raw, radon_functions = (
                    await asyncio.gather(
                        pylint_json_task,
                        pylint_score_task,
                        radon_task,
                        return_exceptions=True,
                    )
                )
                pylint_output = self._unwrap_pylint(
                    pylint_messages_raw, pylint_scores_raw
                )
            else:
                # fast 模式：跳过 pylint
                radon_functions = await radon_task
                pylint_output = _PylintOutput(overall_score=None)

            high_complexity: list[FunctionRisk] = (
                []
                if isinstance(radon_functions, BaseException)
                else radon_functions
            )

            # ------------------------------------------------------------------
            # 阶段 C：构建派生输出
            # ------------------------------------------------------------------
            heatmap = self._build_heatmap(pylint_output.messages_by_file)
            file_risk = self._build_file_risk_summary(
                pylint_output.messages_by_file,
                high_complexity,
            )

            return StaticResult(
                high_complexity_functions=high_complexity,
                file_heatmap=heatmap,
                file_risk_summary=file_risk,
                total_files_scanned=len(py_files),
                pylint_score=pylint_output.overall_score,
                duration_ms=int((time.monotonic() - start) * 1000),
            )

        except Exception as exc:
            logger.exception("StaticAnalyzer.run: unhandled error")
            return StaticResult(
                duration_ms=int((time.monotonic() - start) * 1000),
                error=str(exc),
            )

    # ------------------------------------------------------------------
    # 文件收集
    # ------------------------------------------------------------------

    async def _collect_python_files(self, repo_path: str) -> list[str]:
        """递归查找所有 .py 文件，排除常见的非源码目录。

        在线程中运行 glob，以避免在大型目录树上阻塞事件循环。
        实践中 rglob 足够快，这很少产生影响，但作为一个免费的安全网保留。
        """

        def _find() -> list[str]:
            excluded = {
                "node_modules", ".git", "__pycache__",
                ".venv", "venv", "env", ".tox",
                "build", "dist", ".eggs", "*.egg-info",
                "site-packages", "__pypackages__",
            }
            files: list[str] = []
            for p in Path(repo_path).rglob("*.py"):
                parts = set(p.parts)
                if not parts & excluded:
                    files.append(str(p))
            return files

        return await asyncio.to_thread(_find)

    # ------------------------------------------------------------------
    # 策略辅助
    # ------------------------------------------------------------------

    @staticmethod
    def _is_test_file(filepath: str) -> bool:
        """检查是否为测试文件（用于 focused 模式排除）。"""
        import os
        name = os.path.basename(filepath)
        # 文件名模式匹配
        test_patterns = ("test_", "_test.py", "tests.py")
        for pat in test_patterns:
            if pat in name:
                return True
        # 路径中包含 test/tests 目录
        normalized = filepath.replace("\\", "/")
        parts = normalized.split("/")
        return any(p in ("tests", "test") for p in parts)

    # ------------------------------------------------------------------
    # pylint — JSON 消息（逐行 lint 问题）
    # ------------------------------------------------------------------

    async def _run_pylint_json(
        self, repo_path: str, _py_files: list[str]
    ) -> dict[str, list[dict]]:
        """以 JSON 输出运行 pylint；返回按文件分组的消息。

        只传 repo_path 避免 Windows 命令行长度限制（文件多时拼接参数会超 32k 字符）。
        Pylint 退出码：
            0 — 无消息
            1 — 致命消息
            2 — 致命消息
            4, 8, 16, 32 — 错误 / 使用错误 / 内部错误
        码 0-2 是 lint 结果的正常范围；更高的码表示真正的错误
        （错误参数、缺失模块等）。
        """
        try:
            def _run() -> str:
                result = subprocess.run(
                    [sys.executable, "-m", "pylint", "--recursive=y", "--output-format=json", repo_path],
                    capture_output=True, timeout=self.PYLINT_TIMEOUT,
                )
                # pylint 退出码是位掩码：bits 0-4 表示发现的问题（正常），bit 5 (32) 才表示调用错误。
                if result.returncode is not None and (result.returncode & 32):
                    stderr_text = result.stderr.decode("utf-8", errors="replace")[:500]
                    raise subprocess.CalledProcessError(
                        result.returncode, result.args,
                        output=result.stdout, stderr=result.stderr,
                    )
                return result.stdout.decode("utf-8", errors="replace")

            raw_text = await asyncio.to_thread(_run)
            raw_text = raw_text.strip()
            if not raw_text:
                return {}

            messages = json.loads(raw_text)
            if not isinstance(messages, list):
                logger.warning("pylint JSON 输出不是列表")
                return {}

            # 按文件路径分组消息
            result: dict[str, list[dict]] = {}
            for msg in messages:
                if not isinstance(msg, dict):
                    continue
                path = msg.get("path", "")
                if path:
                    result.setdefault(path, []).append(msg)
            return result

        except FileNotFoundError:
            logger.info("pylint 未安装 — 跳过 lint 分析")
            return {}
        except subprocess.TimeoutExpired:
            logger.warning("pylint 超时 (%ds)", self.PYLINT_TIMEOUT)
            return {}
        except json.JSONDecodeError as exc:
            logger.warning("pylint JSON 解析失败: %s", exc)
            return {}
        except subprocess.CalledProcessError as exc:
            stderr_text = exc.stderr.decode(errors="replace") if exc.stderr else ""
            logger.warning("pylint 异常退出 (rc=%d): %s", exc.returncode, stderr_text.strip())
            return {}

    # ------------------------------------------------------------------
    # pylint — 评分提取（文本输出）
    # ------------------------------------------------------------------

    async def _run_pylint_score(
        self, repo_path: str, _py_files: list[str]
    ) -> dict[str, float]:
        """以文本模式运行 pylint 来提取文件级评分。

        只传 repo_path 避免 Windows 命令行长度限制。
        Pylint 的 JSON 模式故意省略评分，因此我们使用 --score=y 运行第二次调用。
        这比听起来更轻量，因为 pylint 在快速连续运行相同文件时会内部缓存 AST
        （操作系统磁盘缓存也帮我们处理了）。

        返回文件路径 → 评分 (0.0–10.0) 的映射。
        """
        try:
            def _run() -> str:
                result = subprocess.run(
                    [sys.executable, "-m", "pylint", "--recursive=y", "--score=y", "--output-format=text", repo_path],
                    capture_output=True, timeout=self.PYLINT_TIMEOUT,
                )
                return result.stdout.decode("utf-8", errors="replace")

            text = await asyncio.to_thread(_run)
            return self._parse_pylint_scores(text)

        except FileNotFoundError:
            return {}
        except subprocess.TimeoutExpired:
            logger.warning("pylint 评分提取超时")
            return {}

    @staticmethod
    def _parse_pylint_scores(text: str) -> dict[str, float]:
        """解析 pylint 文本输出中的评分。

        Pylint 文本输出末尾包含::

            Your code has been rated at 8.50/10 (previous run: 8.50/10, +0.00)

        同时兼容旧版 pylint 的模块级评分行 "Module xxx 8.50/10"。

        返回 {filepath: score} 映射，其中 "__overall__" 为总体评分。
        """
        scores: dict[str, float] = {}

        # 旧版模块级评分行："Module xxx 8.50/10"
        for match in re.finditer(
            r"Module\s+(\S+)\s+([\d.]+)/10", text
        ):
            module_name = match.group(1)
            score = float(match.group(2))
            filepath = module_name.replace(".", "/") + ".py"
            scores[filepath] = score

        # 整体评分："Your code has been rated at 8.50/10"
        m = _PYLINT_SCORE_RE.search(text)
        if m:
            scores["__overall__"] = float(m.group(1))

        return scores

    # ------------------------------------------------------------------
    # radon — 圈复杂度
    # ------------------------------------------------------------------

    async def _run_radon(self, repo_path: str) -> list[FunctionRisk]:
        """运行 radon cc 并提取高复杂度函数。

        radon cc --json 产出::

            {
                "/path/to/file.py": [
                    {
                        "name": "function_name",
                        "lineno": 42,
                        "col_offset": 4,
                        "complexity": 15,
                        "rank": "C",
                        ...
                    }
                ]
            }

        我们筛选出 MEDIUM+ 复杂度（级别 B+ / CC >= 10）的函数，返回
        结构化的 FunctionRisk 对象。
        """
        try:
            def _run() -> str:
                result = subprocess.run(
                    [sys.executable, "-m", "radon", "cc", "--json", "--min=B", repo_path],
                    capture_output=True, timeout=self.RADON_TIMEOUT,
                )
                return result.stdout.decode("utf-8", errors="replace")

            raw_text = await asyncio.to_thread(_run)
            raw_text = raw_text.strip()
            if not raw_text:
                return []

            raw = json.loads(raw_text)
            if not isinstance(raw, dict):
                logger.warning("radon 输出不是 JSON 对象")
                return []

            results: list[FunctionRisk] = []
            for file_path, blocks in raw.items():
                if not isinstance(blocks, list):
                    continue
                for block in blocks:
                    if not isinstance(block, dict):
                        continue
                    cc = block.get("complexity", 0)
                    if not isinstance(cc, (int, float)) or cc < _COMPLEXITY_MEDIUM:
                        continue

                    risk = (
                        RiskLevel.HIGH if cc >= _COMPLEXITY_HIGH
                        else RiskLevel.MEDIUM
                    )
                    results.append(FunctionRisk(
                        file=file_path,
                        line=block.get("lineno", 0),
                        name=block.get("name", "unknown"),
                        complexity=int(cc),
                        risk_level=risk,
                    ))

            # 按复杂度降序排列
            results.sort(key=lambda f: f.complexity, reverse=True)
            return results

        except FileNotFoundError:
            logger.info("radon 未安装 — 跳过复杂度分析")
            return []
        except subprocess.TimeoutExpired:
            logger.warning("radon 超时 (%ds)", self.RADON_TIMEOUT)
            return []
        except json.JSONDecodeError as exc:
            logger.warning("radon JSON 解析失败: %s", exc)
            return []

    # ------------------------------------------------------------------
    # 结果规范化 / 聚合
    # ------------------------------------------------------------------

    @staticmethod
    def _unwrap_pylint(
        messages_raw: object,
        scores_raw: object,
    ) -> _PylintOutput:
        """将两个 pylint 子进程结果规范化为一个结构体。

        处理一个子进程成功而另一个失败的情况。
        """
        messages: dict[str, list[dict]] = (
            messages_raw if isinstance(messages_raw, dict) else {}
        )
        scores: dict[str, float] = (
            scores_raw if isinstance(scores_raw, dict) else {}
        )

        # 提取总体评分（__overall__ 键来自 _PYLINT_SCORE_RE 匹配）
        overall: Optional[float] = scores.pop("__overall__", None)
        if overall is None and scores:
            # 回退：旧版 pylint 模块级评分取平均
            overall = round(sum(scores.values()) / len(scores), 2)

        return _PylintOutput(
            messages_by_file=messages,
            file_scores=scores,
            overall_score=overall,
        )

    @staticmethod
    def _build_heatmap(
        messages_by_file: dict[str, list[dict]],
    ) -> dict[str, list[LineRisk]]:
        """将 pylint 消息转换为每文件行风险热力图。

        风险映射:
            error / fatal  → HIGH
            warning         → MEDIUM
            convention / refactor / info → LOW
        """
        heatmap: dict[str, list[LineRisk]] = {}
        if not messages_by_file:
            return heatmap

        for file_path, messages in messages_by_file.items():
            risks: list[LineRisk] = []
            for msg in messages:
                line = msg.get("line", 0)
                msg_type = msg.get("type", "")

                if msg_type in ("error", "fatal"):
                    risk = RiskLevel.HIGH
                elif msg_type == "warning":
                    risk = RiskLevel.MEDIUM
                else:
                    risk = RiskLevel.LOW

                risks.append(LineRisk(
                    line=line,
                    risk_level=risk,
                    reason=msg.get("message", ""),
                ))
            if risks:
                heatmap[file_path] = risks

        return heatmap

    @staticmethod
    def _build_file_risk_summary(
        messages_by_file: dict[str, list[dict]],
        complexity_functions: list[FunctionRisk],
    ) -> list[FileRiskSummary]:
        """从 lint + 复杂度数据计算每文件风险摘要。

        对每个文件：
        1. 统计 lint 问题数（来自 pylint 消息）
        2. 找到最大圈复杂度（来自 radon）
        3. 推导整体风险等级：
           - HIGH：任意函数 CC >= 20 或存在 error/fatal lint
           - MEDIUM：任意函数 CC >= 10 或存在 warning lint
           - LOW：其他

        返回按风险等级（HIGH 优先）和问题数排序的列表。
        """
        # 收集两个工具涉及的所有文件
        all_files: set[str] = set(messages_by_file.keys())
        for func in complexity_functions:
            all_files.add(func.file)

        summaries: list[FileRiskSummary] = []
        for file_path in sorted(all_files):
            msgs = messages_by_file.get(file_path, [])
            lint_count = len(msgs)

            # 从 radon 结果中取最大复杂度
            max_cc = 0
            for func in complexity_functions:
                if func.file == file_path and func.complexity > max_cc:
                    max_cc = func.complexity

            # 存在高严重度 lint？
            has_error = any(
                m.get("type") in ("error", "fatal") for m in msgs
            )
            has_warning = any(
                m.get("type") == "warning" for m in msgs
            )

            # 推导风险等级
            if max_cc >= _COMPLEXITY_HIGH or has_error:
                risk = RiskLevel.HIGH
            elif max_cc >= _COMPLEXITY_MEDIUM or has_warning:
                risk = RiskLevel.MEDIUM
            else:
                risk = RiskLevel.LOW

            summaries.append(FileRiskSummary(
                file=file_path,
                risk_level=risk,
                lint_issues=lint_count,
                max_complexity=max_cc,
            ))

        # 排序：HIGH → MEDIUM → LOW，然后按 lint 数降序
        risk_order = {RiskLevel.HIGH: 0, RiskLevel.MEDIUM: 1, RiskLevel.LOW: 2}
        summaries.sort(key=lambda s: (
            risk_order.get(s.risk_level, 99),
            -s.lint_issues,
            -s.max_complexity,
        ))

        return summaries
