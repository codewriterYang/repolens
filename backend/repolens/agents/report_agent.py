"""ReportAgent — 汇总报告生成 Agent。

Phase 6: 从 SharedMemory 读取各 Agent 的分析结果，
生成结构化 JSON + HTML 汇总报告。

协作链路：
StaticAgent/RepoAgent/GitAgent → SharedMemory → ReportAgent → ReportResult
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Optional

from .base import BaseAgent
from ..schemas import AnalysisPlan, GitResult, ReportResult, RepoResult, StaticResult

if TYPE_CHECKING:
    from ..context import RepositoryContext

logger = logging.getLogger(__name__)


class ReportAgent(BaseAgent):
    """汇总报告 Agent。

    在三个分析 Agent 完成后运行，从 SharedMemory 中读取：
    - static_result (StaticAgent 产出)
    - repo_result (RepoAgent 产出)
    - git_result (GitAgent 产出)

    汇总为 ReportResult（JSON + HTML），写回 SharedMemory。
    """

    name = "report"

    async def run(self, context: RepositoryContext, **kwargs: Any) -> ReportResult:
        """从 SharedMemory 读取数据并生成汇总报告。

        参数:
            context: 不可变分析上下文。

        返回:
            ReportResult 包含 JSON 摘要和 HTML 报告。
        """
        # 从 SharedMemory 读取各 Agent 结果和计划
        static: Optional[StaticResult] = None
        repo: Optional[RepoResult] = None
        git: Optional[GitResult] = None
        plan: Optional[AnalysisPlan] = None
        agents_available: list[str] = []

        if self._memory is not None:
            static = self._memory.get("static_result")
            repo = self._memory.get("repo_result")
            git = self._memory.get("git_result")
            plan = self._memory.get("analysis_plan")

            if static is not None:
                agents_available.append("static")
            if repo is not None:
                agents_available.append("repo")
            if git is not None:
                agents_available.append("git")

            logger.info(
                "ReportAgent: 读取 SharedMemory — agents=%s plan=%s",
                agents_available,
                plan.tasks if plan else "N/A",
            )
        else:
            logger.warning("ReportAgent: SharedMemory 未注入，报告将为空")

        # 构建 ReportResult
        result = ReportResult(
            repo_name=context.repo_name,
            repo_url=context.repo_url,
            analysis_id=context.analysis_id,
            agents_available=agents_available,

            # 静态分析摘要
            total_files_scanned=static.total_files_scanned if static else 0,
            pylint_score=static.pylint_score if static else None,

            # 仓库分析摘要
            readme_quality_score=repo.readme_quality_score if repo else 0,

            # Git 分析摘要
            total_commits=git.total_commits if git else 0,
            unique_contributors=git.unique_contributors if git else 0,
            ci_cd_detected=git.ci_cd_config if git else False,

        # HTML 报告
        html_report=self._build_html(
            context=context,
            plan=plan,
            static=static,
            repo=repo,
            git=git,
            agents=agents_available,
        ),
        )

        # 写回 SharedMemory
        if self._memory is not None:
            self._memory.set("report_result", result)
            logger.info(
                "ReportAgent: 报告已写入 SharedMemory — "
                "agents=%s files=%d score=%.1f commits=%d",
                agents_available,
                result.total_files_scanned,
                result.pylint_score or 0,
                result.total_commits,
            )

        return result

    # ------------------------------------------------------------------
    # HTML 生成
    # ------------------------------------------------------------------

    @staticmethod
    def _build_html(
        context: RepositoryContext,
        plan: Optional[AnalysisPlan],
        static: Optional[StaticResult],
        repo: Optional[RepoResult],
        git: Optional[GitResult],
        agents: list[str],
    ) -> str:
        """生成可折叠的自包含 HTML 汇总报告。"""

        now_str = context.started_at.strftime("%Y-%m-%d %H:%M:%S")

        return f"""\
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>RepoLens Report — {context.repo_name}</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f8fafc; color: #1e293b; padding:24px; }}
.container {{ max-width:800px; margin:0 auto; }}
h1 {{ font-size:22px; margin-bottom:4px; }}
h2 {{ font-size:16px; margin:20px 0 10px; border-bottom:2px solid #e2e8f0; padding-bottom:4px; cursor:pointer; user-select:none; }}
h2::before {{ content:'▸ '; display:inline-block; transition:transform 0.2s; }}
h2.open::before {{ transform:rotate(90deg); }}
.section-content {{ display:none; }}
.section-content.open {{ display:block; }}
.card {{ background:#fff; border-radius:8px; padding:16px; margin-bottom:12px; box-shadow:0 1px 3px rgba(0,0,0,.06); }}
.stat {{ display:inline-block; padding:8px 14px; background:#f1f5f9; border-radius:6px; text-align:center; margin:4px; }}
.stat-val {{ font-size:20px; font-weight:700; }}
.stat-label {{ font-size:11px; color:#64748b; }}
.meta {{ color:#64748b; font-size:13px; }}
.na {{ color:#94a3b8; font-style:italic; }}
footer {{ text-align:center; margin-top:28px; color:#94a3b8; font-size:12px; }}
</style>
<script>
function toggle(id) {{
  var el = document.getElementById(id);
  var hdr = document.getElementById(id+'-hdr');
  if (el && hdr) {{ el.classList.toggle('open'); hdr.classList.toggle('open'); }}
}}
</script>
</head>
<body>
<div class="container">
<h1>{context.repo_name}</h1>
<p class="meta">{context.repo_url} · {now_str} · ID: {context.analysis_id[:12]}</p>

<!-- Agent 概览 -->
<h2 class="open" onclick="toggle('overview')" id="overview-hdr">Agent 状态</h2>
<div class="section-content open" id="overview">
<div class="card">
{ReportAgent._agent_badges(agents)}
{ReportAgent._plan_summary(plan)}
</div>
</div>

<!-- 静态分析 -->
<h2 class="open" onclick="toggle('static')" id="static-hdr">静态分析</h2>
<div class="section-content open" id="static">
<div class="card">
{ReportAgent._static_section(static)}
</div>
</div>

<!-- 仓库洞察 -->
<h2 class="open" onclick="toggle('repo')" id="repo-hdr">仓库洞察</h2>
<div class="section-content open" id="repo">
<div class="card">
{ReportAgent._repo_section(repo)}
</div>
</div>

<!-- Git 活动 -->
<h2 class="open" onclick="toggle('git')" id="git-hdr">Git 活动</h2>
<div class="section-content open" id="git">
<div class="card">
{ReportAgent._git_section(git)}
</div>
</div>

<footer>由 RepoLens ReportAgent 生成 — {now_str}</footer>
</div>
<script>
// 向父窗口报告实际内容高度，避免 sandbox 限制 contentDocument 读取
// 使用 DOMContentLoaded + setTimeout 确保布局完全计算完成
document.addEventListener('DOMContentLoaded', function() {{
  setTimeout(function() {{
    var h = Math.max(
      document.body.scrollHeight,
      document.body.offsetHeight,
      document.documentElement.clientHeight,
      document.documentElement.scrollHeight,
      document.documentElement.offsetHeight
    );
    if (window.parent && window.parent !== window) {{
      window.parent.postMessage({{ type: 'repolens-height', height: h }}, '*');
    }}
  }}, 100);
}});
</script>
</body>
</html>"""

    # ------------------------------------------------------------------
    # 子区域渲染
    # ------------------------------------------------------------------

    @staticmethod
    def _plan_summary(plan: Optional[AnalysisPlan]) -> str:
        if plan is None:
            return ""
        lines = ['<div style="margin-top:12px;padding:10px;background:#f0f9ff;border-radius:6px;">']
        lines.append('<p style="font-weight:600;margin-bottom:6px;">📋 Plan Summary</p>')
        lines.append(f'<p>执行任务: {", ".join(plan.tasks)}</p>')

        # Phase 8: 展示 strategy 和 confidence
        if hasattr(plan, 'strategy') and plan.strategy is not None:
            strategy = plan.strategy
            lines.append('<div style="margin-top:6px;">')
            lines.append('<p style="font-weight:600;font-size:12px;">📊 分析策略</p>')
            lines.append(
                f'<p style="font-size:11px;">'
                f'静态分析: {strategy.static}（置信度 {strategy.static_confidence}%） · '
                f'仓库分析: {strategy.repo} · '
                f'Git 分析: {strategy.git}'
                f'</p>'
            )
            # 显示 strategy 选择理由
            if plan.reasons:
                for key, reason in plan.reasons.items():
                    lines.append(
                        f'<p style="font-size:10px;color:#64748b;">'
                        f'→ {reason}</p>'
                    )
            lines.append('</div>')

        lines.append(f'<p style="font-size:11px;color:#64748b;">优先级: {plan.priority}</p>')
        lines.append('</div>')
        return "\n".join(lines)

    @staticmethod
    def _agent_badges(agents: list[str]) -> str:
        if not agents:
            return '<p class="na">无 Agent 产出</p>'
        colors = {"static": "#3b82f6", "repo": "#8b5cf6", "git": "#10b981"}
        badges = " ".join(
            f'<span style="display:inline-block;padding:4px 12px;margin:4px;'
            f'border-radius:4px;background:{colors.get(a,"#94a3b8")};color:#fff;'
            f'font-size:13px;font-weight:600;">{a}</span>'
            for a in agents
        )
        return f'<p>{badges}</p><p class="meta" style="margin-top:8px;">共 {len(agents)} 个 Agent 产出分析结果</p>'

    @staticmethod
    def _static_section(result: Optional[StaticResult]) -> str:
        if result is None:
            return '<p class="na">静态分析结果不可用</p>'
        score_text = f"{result.pylint_score:.1f}/10" if result.pylint_score is not None else "N/A"
        return (
            f'<div class="stat"><div class="stat-val">{result.total_files_scanned}</div>'
            f'<div class="stat-label">扫描文件</div></div>'
            f'<div class="stat"><div class="stat-val">{score_text}</div>'
            f'<div class="stat-label">Pylint 评分</div></div>'
            f'<div class="stat"><div class="stat-val">{len(result.high_complexity_functions)}</div>'
            f'<div class="stat-label">复杂函数</div></div>'
        )

    @staticmethod
    def _repo_section(result: Optional[RepoResult]) -> str:
        if result is None:
            return '<p class="na">仓库分析结果不可用</p>'
        patterns = ", ".join(result.usage_patterns) if result.usage_patterns else "未识别"
        modules = ", ".join(result.core_modules) if result.core_modules else "未识别"
        summary = result.summary or "无"
        return (
            f'<p><strong>使用模式:</strong> {patterns}</p>'
            f'<p><strong>核心模块:</strong> {modules}</p>'
            f'<p><strong>摘要:</strong> {summary}</p>'
            f'<div class="stat"><div class="stat-val">{result.readme_quality_score}</div>'
            f'<div class="stat-label">README 质量</div></div>'
        )

    @staticmethod
    def _git_section(result: Optional[GitResult]) -> str:
        if result is None:
            return '<p class="na">Git 分析结果不可用</p>'
        ci = "✅ 已配置" if result.ci_cd_config else "❌ 未检测到"
        return (
            f'<div class="stat"><div class="stat-val">{result.total_commits:,}</div>'
            f'<div class="stat-label">总提交</div></div>'
            f'<div class="stat"><div class="stat-val">{result.unique_contributors}</div>'
            f'<div class="stat-label">贡献者</div></div>'
            f'<div class="stat"><div class="stat-val">{result.active_days}</div>'
            f'<div class="stat-label">活跃天数</div></div>'
            f'<div class="stat"><div class="stat-val">{ci}</div>'
            f'<div class="stat-label">CI/CD</div></div>'
        )
