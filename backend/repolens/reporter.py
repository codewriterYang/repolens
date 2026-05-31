"""报告生成器 — 将分析器结果聚合为结构化报告。

产出：
- 健康评分 (0-100)，含各维度细分。
- 来自三个分析器的优先排序建议。
- 带折叠区域、时间线图表和文件级风险排序的行内 HTML 报告。
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Optional

from .schemas import (
    FileRiskSummary,
    FunctionRisk,
    GitResult,
    InferredRisk,
    Recommendation,
    ReportJson,
    RepoResult,
    StaticResult,
)


class Reporter:
    """聚合分析器产出为最终 ReportJson。"""

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    def render(
        self,
        job_id: str,
        repo_url: str,
        static_result: Optional[StaticResult],
        repo_result: Optional[RepoResult],
        git_result: Optional[GitResult],
        pipeline_start: float,
    ) -> ReportJson:
        """生成最终分析报告。

        参数：
            job_id: 唯一任务标识。
            repo_url: 原始仓库 URL。
            static_result: StaticAnalyzer 产出（或 None）。
            repo_result: RepoAnalyzer 产出（或 None）。
            git_result: GitAnalyzer 产出（或 None）。
            pipeline_start: 流水线启动时的 time.monotonic()。

        返回：
            包含健康评分、建议和 HTML 的完整 ReportJson。
        """
        recommendations = self._build_recommendations(
            static_result, repo_result, git_result
        )
        score_breakdown = self._compute_health_score(
            static_result, repo_result, git_result
        )
        health_score = sum(score_breakdown.values())
        html = self._build_html(
            job_id, repo_url, health_score, score_breakdown,
            static_result, repo_result, git_result,
            recommendations,
        )

        return ReportJson(
            job_id=job_id,
            repo_url=repo_url,
            health_score=health_score,
            static_analysis=static_result,
            repo_analysis=repo_result,
            git_analysis=git_result,
            recommendations=recommendations,
            html_report=html,
            total_duration_ms=int((time.monotonic() - pipeline_start) * 1000),
            created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )

    # ------------------------------------------------------------------
    # 评分 — 返回各维度细分
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_health_score(
        static_result: Optional[StaticResult],
        repo_result: Optional[RepoResult],
        git_result: Optional[GitResult],
    ) -> dict[str, int]:
        """计算 0-100 的综合健康评分及各维度细分。

        维度：
        - 代码质量 (0-40): 高复杂度函数越少 → 得分越高。
        - 仓库清晰度 (0-30): 基于 README 质量和模式识别。
        - 社区活跃 (0-20): 基于提交频率和贡献者数量。
        - 工程实践 (0-10): CI/CD 存在情况。

        返回：
            包含 code_quality, repo_clarity, community, engineering 键的字典。
        """
        code_quality = 0
        repo_clarity = 0
        community = 0
        engineering = 0

        # 代码质量 (0-40)
        if static_result and not static_result.error:
            # 维度 A：复杂度密度 (20 分)
            n_high = len(static_result.high_complexity_functions)
            n_files = max(1, static_result.total_files_scanned)
            ratio = min(1.0, n_high / n_files)
            code_quality += int(20 * (1.0 - ratio))

            # 维度 B：pylint 评分 (20 分)
            if static_result.pylint_score is not None:
                code_quality += min(20, int(static_result.pylint_score * 2))

        # 仓库清晰度 (0-30)
        if repo_result and not repo_result.error:
            if repo_result.usage_patterns:
                repo_clarity += 15
            repo_clarity += int(15 * (repo_result.readme_quality_score / 100))

        # 社区活跃 (0-20)
        if git_result and not git_result.error:
            cw = git_result.commits_per_week
            uc = git_result.unique_contributors
            if cw >= 7:
                community += 10
            elif cw >= 2:
                community += 6
            elif cw > 0:
                community += 3
            if uc >= 5:
                community += 10
            elif uc >= 2:
                community += 6
            elif uc > 0:
                community += 3

        # 工程实践 (0-10) — CI/CD
        if git_result and not git_result.error and git_result.ci_cd_config:
            engineering = 10

        return {
            "code_quality": code_quality,
            "repo_clarity": repo_clarity,
            "community": community,
            "engineering": engineering,
        }

    # ------------------------------------------------------------------
    # 建议 — 跨分析器统一
    # ------------------------------------------------------------------

    @staticmethod
    def _build_recommendations(
        static_result: Optional[StaticResult],
        repo_result: Optional[RepoResult],
        git_result: Optional[GitResult],
    ) -> list[Recommendation]:
        """从三个分析器生成带优先级的建议。

        分类按优先级排序：
        - 优先级 1（严重）：高风险代码、安全风险
        - 优先级 2（重要）：缺少 CI/CD、低贡献者数、结构问题
        - 优先级 3（建议）：低活跃度、文档缺失
        """
        recs: list[Recommendation] = []

        # --- 来自静态分析 ---
        if static_result and not static_result.error:
            # 高风险文件（按 file_risk_summary）
            high_risk_files = [
                s for s in static_result.file_risk_summary
                if s.risk_level.value == "high"
            ]
            if high_risk_files:
                top = sorted(high_risk_files, key=lambda s: -s.lint_issues)[:5]
                recs.append(Recommendation(
                    priority=1,
                    category="代码质量",
                    title=f"发现 {len(high_risk_files)} 个高风险文件",
                    detail=(
                        f"建议优先处理以下高风险文件: "
                        f"{', '.join(f'{f.file}({f.lint_issues} 问题)' for f in top)}"
                    ),
                ))

            # 高复杂度函数（仅当未被文件风险覆盖时）
            high_risk_funcs = [
                f for f in static_result.high_complexity_functions
                if f.risk_level.value == "high"
            ]
            if high_risk_funcs and not high_risk_files:
                recs.append(Recommendation(
                    priority=1,
                    category="代码质量",
                    title=f"发现 {len(high_risk_funcs)} 个高复杂度函数",
                    detail=(
                        f"建议重构以下函数以降低圈复杂度: "
                        f"{', '.join(f'{h.name} (CC={h.complexity})' for h in high_risk_funcs[:5])}"
                    ),
                ))

            # 中等复杂度函数
            medium_risk = [
                f for f in static_result.high_complexity_functions
                if f.risk_level.value == "medium"
            ]
            if medium_risk and len(medium_risk) > 5:
                recs.append(Recommendation(
                    priority=3,
                    category="代码质量",
                    title=f"{len(medium_risk)} 个函数存在中等复杂度",
                    detail="建议逐步重构中复杂度函数，将圈复杂度控制在 10 以下。",
                ))

        # --- 来自仓库分析 ---
        if repo_result and not repo_result.error:
            if not repo_result.core_modules:
                recs.append(Recommendation(
                    priority=2,
                    category="项目结构",
                    title="未能识别核心模块",
                    detail="建议完善 README 文档，明确项目的核心模块和入口点。",
                ))

            # LLM 或启发式推断的风险
            for risk in repo_result.inferred_risks[:3]:
                pri = 1 if risk.severity.value == "high" else 2 if risk.severity.value == "medium" else 3
                recs.append(Recommendation(
                    priority=pri,
                    category=risk.category,
                    title=risk.description,
                    detail=f"来源: {risk.category} 分析 (严重程度: {risk.severity.value})",
                ))

        # --- 来自 Git 分析 ---
        if git_result and not git_result.error:
            if not git_result.ci_cd_config:
                recs.append(Recommendation(
                    priority=2,
                    category="工程实践",
                    title="未检测到 CI/CD 配置",
                    detail="建议添加 .github/workflows 配置以实现自动化测试和部署。",
                ))

            if git_result.unique_contributors < 2:
                recs.append(Recommendation(
                    priority=2,
                    category="社区健康",
                    title="贡献者数量较少",
                    detail=(
                        f"当前仅有 {git_result.unique_contributors} 位贡献者，"
                        f"建议通过文档和 Issue 标签吸引更多社区参与。"
                    ),
                ))

            if git_result.commits_per_week < 1 and git_result.total_commits > 0:
                recs.append(Recommendation(
                    priority=3,
                    category="社区健康",
                    title="提交频率较低",
                    detail=(
                        f"近 90 天平均每周 {git_result.commits_per_week} 次提交，"
                        f"项目活跃度偏低。"
                    ),
                ))

            # 交叉分析：高频变更且高风险的"热点"文件
            if static_result and not static_result.error:
                high_change_files = {af.path for af in git_result.active_files[:10]}
                high_risk_file_paths = {
                    s.file for s in static_result.file_risk_summary
                    if s.risk_level.value == "high"
                }
                hotspot = high_change_files & high_risk_file_paths
                if hotspot:
                    recs.append(Recommendation(
                        priority=1,
                        category="代码质量",
                        title="高频变更与高风险文件重叠",
                        detail=(
                            f"以下文件同时具备高频变更和高风险特征，建议优先重构: "
                            f"{', '.join(sorted(hotspot)[:5])}"
                        ),
                    ))

        return sorted(recs, key=lambda r: r.priority)

    # ------------------------------------------------------------------
    # HTML 生成 — 含折叠区域、图表
    # ------------------------------------------------------------------

    @staticmethod
    def _build_html(
        job_id: str,
        repo_url: str,
        health_score: int,
        score_breakdown: dict[str, int],
        static_result: Optional[StaticResult],
        repo_result: Optional[RepoResult],
        git_result: Optional[GitResult],
        recommendations: list[Recommendation],
    ) -> str:
        """生成自包含的行内 HTML 报告。

        特性：
        - 可折叠的文件风险表格（按风险等级排序）
        - 行内 SVG 活动时间线图表
        - 健康评分维度柱状图
        - 零外部 CSS/JS 依赖。
        """
        score_color = (
            "#22c55e" if health_score >= 70
            else "#f59e0b" if health_score >= 40
            else "#ef4444"
        )

        return f"""\
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>RepoLens — {repo_url}</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f8fafc; color: #1e293b; line-height:1.6; padding:24px; }}
.container {{ max-width:960px; margin:0 auto; }}
h1 {{ font-size:24px; margin-bottom:8px; }}
h2 {{ font-size:18px; margin:24px 0 12px; border-bottom:2px solid #e2e8f0; padding-bottom:6px; display:flex; align-items:center; gap:8px; }}
h3 {{ font-size:15px; margin:16px 0 8px; }}
.card {{ background:#fff; border-radius:8px; padding:20px; margin-bottom:16px; box-shadow:0 1px 3px rgba(0,0,0,.08); }}
.score-circle {{ width:120px; height:120px; border-radius:50%; display:flex; align-items:center; justify-content:center; margin:0 auto 12px; border:6px solid {score_color}; }}
.score-num {{ font-size:48px; font-weight:800; color:{score_color}; }}
.breakdown {{ display:flex; gap:12px; flex-wrap:wrap; margin-top:12px; }}
.breakdown-item {{ flex:1; min-width:120px; text-align:center; padding:8px; background:#f8fafc; border-radius:6px; }}
.breakdown-bar {{ height:6px; border-radius:3px; margin-top:4px; }}
.breakdown-label {{ font-size:12px; color:#64748b; }}
.breakdown-val {{ font-size:20px; font-weight:700; }}
.rec {{ border-left:4px solid; padding:10px 16px; margin:8px 0; border-radius:0 4px 4px 0; }}
.rec.p1 {{ border-color:#ef4444; background:#fef2f2; }}
.rec.p2 {{ border-color:#f59e0b; background:#fffbeb; }}
.rec.p3 {{ border-color:#3b82f6; background:#eff6ff; }}
.tag {{ display:inline-block; padding:2px 8px; border-radius:4px; font-size:12px; font-weight:600; }}
.tag.high {{ background:#fee2e2; color:#991b1b; }}
.tag.medium {{ background:#fef3c7; color:#92400e; }}
.tag.low {{ background:#dcfce7; color:#166534; }}
.meta {{ color:#64748b; font-size:14px; }}
.na {{ color:#94a3b8; font-style:italic; }}
table {{ width:100%; border-collapse:collapse; font-size:13px; }}
th, td {{ text-align:left; padding:8px 12px; border-bottom:1px solid #e2e8f0; }}
th {{ font-weight:600; font-size:12px; color:#64748b; text-transform:uppercase; }}
tr:hover {{ background:#f8fafc; }}
.collapsible {{ cursor:pointer; user-select:none; }}
.collapsible::before {{ content:'▸ '; display:inline-block; transition:transform 0.2s; }}
.collapsible.open::before {{ transform:rotate(90deg); }}
.collapsible-content {{ display:none; }}
.collapsible-content.open {{ display:block; }}
.summary-stats {{ display:flex; gap:16px; flex-wrap:wrap; margin-bottom:12px; }}
.stat {{ padding:8px 16px; background:#f1f5f9; border-radius:6px; text-align:center; }}
.stat-val {{ font-size:22px; font-weight:700; }}
.stat-label {{ font-size:11px; color:#64748b; }}
.empty-state {{ text-align:center; padding:32px; color:#94a3b8; }}
.timeline-chart {{ display:flex; align-items:flex-end; gap:2px; height:100px; padding:0 4px; }}
.timeline-bar {{ flex:1; min-width:6px; border-radius:2px 2px 0 0; background:#3b82f6; position:relative; }}
.timeline-bar:hover {{ opacity:0.8; }}
.timeline-label {{ font-size:10px; color:#64748b; text-align:center; }}
.risk-sort-controls {{ margin-bottom:8px; display:flex; gap:8px; }}
.sort-btn {{ padding:4px 12px; border:1px solid #e2e8f0; border-radius:4px; background:#fff; cursor:pointer; font-size:12px; }}
.sort-btn:hover {{ background:#f1f5f9; }}
.sort-btn.active {{ background:#3b82f6; color:#fff; border-color:#3b82f6; }}
footer {{ text-align:center; margin-top:32px; color:#94a3b8; font-size:13px; }}
</style>
<script>
// 折叠区域最小 JS — 无框架依赖。
function toggleSection(id) {{
  var el = document.getElementById(id);
  var hdr = document.getElementById(id + '-hdr');
  if (el && hdr) {{
    el.classList.toggle('open');
    hdr.classList.toggle('open');
  }}
}}
function toggleAllRisk(show) {{
  document.querySelectorAll('.collapsible-content.risk-group').forEach(function(el) {{
    var hdr = document.getElementById(el.id + '-hdr');
    if (show) {{
      el.classList.add('open');
      if (hdr) hdr.classList.add('open');
    }} else {{
      el.classList.remove('open');
      if (hdr) hdr.classList.remove('open');
    }}
  }});
}}
</script>
</head>
<body>
<div class="container">
<h1>RepoLens 分析报告</h1>
<p class="meta">{repo_url}</p>

<!-- ====== 健康评分 ====== -->
<h2>健康评分</h2>
<div class="card">
<div class="score-circle"><span class="score-num">{health_score}</span></div>
<p style="text-align:center;color:#64748b;margin-bottom:16px;">综合评分 (0-100)</p>
<div class="breakdown">
{Reporter._html_score_breakdown(score_breakdown)}
</div>
</div>

<!-- ====== 改进建议 ====== -->
<h2>改进建议 <span class="meta">({len(recommendations)} 条)</span></h2>
<div class="card">
{Reporter._html_recommendations(recommendations)}
</div>

<!-- ====== 代码质量（可折叠文件风险表） ====== -->
<h2>代码质量</h2>
<div class="card">
{Reporter._html_static_enhanced(static_result)}
</div>

<!-- ====== 仓库洞察 ====== -->
<h2>仓库洞察</h2>
<div class="card">
{Reporter._html_repo_enhanced(repo_result)}
</div>

<!-- ====== Git 活动 ====== -->
<h2>Git 活动</h2>
<div class="card">
{Reporter._html_git_enhanced(git_result)}
</div>

<footer>
由 RepoLens 生成 &mdash; {datetime.now().strftime('%Y-%m-%d %H:%M')}
</footer>
</div>
</body>
</html>"""

    # ------------------------------------------------------------------
    # HTML 子区域 — 增强版本
    # ------------------------------------------------------------------

    @staticmethod
    def _html_score_breakdown(breakdown: dict[str, int]) -> str:
        """渲染健康评分维度柱状图。"""
        labels = {
            "code_quality": ("代码质量", "#3b82f6", 40),
            "repo_clarity": ("仓库清晰度", "#8b5cf6", 30),
            "community": ("社区活跃", "#10b981", 20),
            "engineering": ("工程实践", "#f59e0b", 10),
        }
        parts: list[str] = []
        for key, (label, color, max_val) in labels.items():
            val = breakdown.get(key, 0)
            pct = int(val / max_val * 100) if max_val > 0 else 0
            parts.append(
                f'<div class="breakdown-item">'
                f'<div class="breakdown-val" style="color:{color}">{val}</div>'
                f'<div class="breakdown-label">{label}</div>'
                f'<div class="breakdown-bar" style="width:100%;background:#e2e8f0;">'
                f'<div style="width:{pct}%;height:100%;background:{color};border-radius:3px;"></div>'
                f'</div>'
                f'<div class="breakdown-label">/ {max_val}</div>'
                f'</div>'
            )
        return "\n".join(parts)

    @staticmethod
    def _html_recommendations(recs: list[Recommendation]) -> str:
        """按优先级分组渲染建议。"""
        if not recs:
            return '<div class="empty-state">暂无改进建议 🎉</div>'

        priority_labels = {1: "严重", 2: "重要", 3: "建议"}
        groups: dict[int, list[Recommendation]] = {1: [], 2: [], 3: []}
        for r in recs:
            groups.setdefault(r.priority, []).append(r)

        parts: list[str] = []
        for pri in (1, 2, 3):
            items = groups.get(pri, [])
            if not items:
                continue
            parts.append(
                f'<div style="margin-bottom:8px;font-weight:600;color:#64748b;font-size:13px;">'
                f'优先级 {pri} — {priority_labels[pri]}</div>'
            )
            for r in items:
                parts.append(
                    f'<div class="rec p{r.priority}">'
                    f'<strong>[{r.category}] {r.title}</strong><br>'
                    f'<span class="meta">{r.detail}</span>'
                    f'</div>'
                )
        return "\n".join(parts)

    @staticmethod
    def _html_static_enhanced(result: Optional[StaticResult]) -> str:
        """渲染静态分析结果，含可折叠文件风险表。"""
        if result is None or result.error:
            return (
                f'<p class="na">{"代码分析失败: " + result.error if result else "N/A"}</p>'
            )

        parts: list[str] = []

        # 摘要统计
        score_text = (
            f"{result.pylint_score:.1f}/10"
            if result.pylint_score is not None
            else "N/A"
        )
        n_high = len(result.high_complexity_functions)
        n_high_risk = sum(
            1 for f in result.high_complexity_functions
            if f.risk_level.value == "high"
        )
        parts.append(
            '<div class="summary-stats">'
            f'<div class="stat"><div class="stat-val">{result.total_files_scanned}</div><div class="stat-label">扫描文件</div></div>'
            f'<div class="stat"><div class="stat-val">{score_text}</div><div class="stat-label">Pylint 评分</div></div>'
            f'<div class="stat"><div class="stat-val">{n_high}</div><div class="stat-label">复杂函数</div></div>'
            f'<div class="stat"><div class="stat-val">{n_high_risk}</div><div class="stat-label">高风险函数</div></div>'
            '</div>'
        )

        # --- 文件风险摘要含可折叠分组 ---
        if result.file_risk_summary:
            # 按风险等级分组
            high_files = [s for s in result.file_risk_summary if s.risk_level.value == "high"]
            med_files = [s for s in result.file_risk_summary if s.risk_level.value == "medium"]
            low_files = [s for s in result.file_risk_summary if s.risk_level.value == "low"]

            # 全局折叠按钮
            parts.append(
                '<div class="risk-sort-controls">'
                '<span style="font-size:13px;color:#64748b;line-height:28px;margin-right:8px;">文件风险:</span>'
                '<button class="sort-btn" onclick="toggleAllRisk(true)">全部展开</button>'
                '<button class="sort-btn" onclick="toggleAllRisk(false)">全部收起</button>'
                '</div>'
            )

            for group_id, label, color_class, files in [
                ("risk-high", "高风险", "high", high_files),
                ("risk-medium", "中等风险", "medium", med_files),
                ("risk-low", "低风险", "low", low_files),
            ]:
                if not files:
                    continue
                count = len(files)
                total_lint = sum(f.lint_issues for f in files)
                parts.append(
                    f'<h3 class="collapsible open" onclick="toggleSection(\'{group_id}\')" id="{group_id}-hdr">'
                    f'<span class="tag {color_class}">{label}</span> '
                    f'{count} 个文件 ({total_lint} 条 lint 问题)'
                    f'</h3>'
                )
                rows = "\n".join(
                    f'<tr>'
                    f'<td style="max-width:320px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="{s.file}">{s.file}</td>'
                    f'<td><span class="tag {s.risk_level.value}">{s.risk_level.value}</span></td>'
                    f'<td>{s.lint_issues}</td>'
                    f'<td>{s.max_complexity}</td>'
                    f'</tr>'
                    for s in files[:30]  # 每组最多展示 30 个
                )
                parts.append(
                    f'<div class="collapsible-content risk-group open" id="{group_id}">'
                    f'<table>'
                    f'<tr><th>文件</th><th>风险等级</th><th>Lint 问题数</th><th>最大圈复杂度</th></tr>'
                    f'{rows}'
                    f'</table>'
                    f'</div>'
                )

        # --- 高复杂度函数 ---
        if result.high_complexity_functions:
            func_id = "func-detail"
            parts.append(
                f'<h3 class="collapsible open" onclick="toggleSection(\'{func_id}\')" id="{func_id}-hdr">'
                f'高复杂度函数 ({len(result.high_complexity_functions)} 个)'
                f'</h3>'
            )
            func_rows = "\n".join(
                f'<tr><td style="max-width:260px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="{f.file}">{f.file}</td>'
                f'<td>{f.line}</td><td>{f.name}</td>'
                f'<td>{f.complexity}</td>'
                f'<td><span class="tag {f.risk_level.value}">{f.risk_level.value}</span></td></tr>'
                for f in result.high_complexity_functions[:30]
            )
            parts.append(
                f'<div class="collapsible-content open" id="{func_id}">'
                f'<table>'
                f'<tr><th>文件</th><th>行</th><th>函数</th><th>CC</th><th>风险</th></tr>'
                f'{func_rows}'
                f'</table>'
                f'</div>'
            )
        elif not result.file_risk_summary:
            parts.append('<p>未发现高复杂度函数</p>')

        return "\n".join(parts)

    @staticmethod
    def _html_repo_enhanced(result: Optional[RepoResult]) -> str:
        """渲染仓库分析结果，含风险与元数据。"""
        if result is None or result.error:
            return (
                f'<p class="na">{"仓库分析失败: " + result.error if result else "N/A"}</p>'
            )

        parts: list[str] = []

        # 摘要统计
        patterns = ", ".join(result.usage_patterns) if result.usage_patterns else "未识别"
        modules = ", ".join(result.core_modules) if result.core_modules else "未识别"

        parts.append(
            '<div class="summary-stats">'
            f'<div class="stat"><div class="stat-val">{result.readme_quality_score}</div><div class="stat-label">README 质量</div></div>'
            f'<div class="stat"><div class="stat-val">{len(result.core_modules)}</div><div class="stat-label">核心模块</div></div>'
            f'<div class="stat"><div class="stat-val">{len(result.usage_patterns)}</div><div class="stat-label">使用模式</div></div>'
            f'<div class="stat"><div class="stat-val">{len(result.inferred_risks)}</div><div class="stat-label">推断风险</div></div>'
            '</div>'
        )

        parts.append(f'<p><strong>使用模式:</strong> {patterns}</p>')
        parts.append(f'<p><strong>核心模块:</strong> {modules}</p>')
        if result.summary:
            parts.append(f'<p style="margin-top:8px;padding:12px;background:#f0f9ff;border-radius:6px;">{result.summary}</p>')

        # 推断风险
        if result.inferred_risks:
            risk_rows = "\n".join(
                f'<tr>'
                f'<td><span class="tag {r.severity.value}">{r.severity.value}</span></td>'
                f'<td>{r.category}</td>'
                f'<td>{r.description}</td>'
                f'</tr>'
                for r in result.inferred_risks
            )
            parts.append(
                '<h3>推断风险</h3>'
                '<table>'
                '<tr><th>严重度</th><th>类别</th><th>描述</th></tr>'
                f'{risk_rows}'
                '</table>'
            )

        return "\n".join(parts)

    @staticmethod
    def _html_git_enhanced(result: Optional[GitResult]) -> str:
        """渲染 Git 活动，含行内 SVG 时间线图表。"""
        if result is None or result.error:
            return (
                f'<p class="na">{"Git 分析失败: " + result.error if result else "N/A"}</p>'
            )

        parts: list[str] = []

        # 摘要统计
        ci_badge = "✅ 已配置" if result.ci_cd_config else "❌ 未检测到"
        parts.append(
            '<div class="summary-stats">'
            f'<div class="stat"><div class="stat-val">{result.total_commits:,}</div><div class="stat-label">总提交数</div></div>'
            f'<div class="stat"><div class="stat-val">{result.commits_per_week}</div><div class="stat-label">周均提交</div></div>'
            f'<div class="stat"><div class="stat-val">{result.unique_contributors}</div><div class="stat-label">贡献者</div></div>'
            f'<div class="stat"><div class="stat-val">{result.active_days}</div><div class="stat-label">活跃天数</div></div>'
            f'<div class="stat"><div class="stat-val">{ci_badge}</div><div class="stat-label">CI/CD</div></div>'
            '</div>'
        )

        # --- 每周活动趋势图表（行内 SVG） ---
        if result.activity_over_time:
            recent = result.activity_over_time[-12:]
            if recent:
                max_commits = max(a.commits for a in recent) or 1
                svg_width = 600
                svg_height = 120
                bar_width = max(8, (svg_width - 40) // len(recent) - 2)
                bars_svg: list[str] = []
                labels_svg: list[str] = []

                for i, a in enumerate(recent):
                    bar_h = max(2, int(a.commits / max_commits * (svg_height - 24)))
                    x = 20 + i * (bar_width + 2)
                    y = svg_height - bar_h - 16
                    bars_svg.append(
                        f'<rect x="{x}" y="{y}" width="{bar_width}" height="{bar_h}" '
                        f'rx="2" fill="#3b82f6">'
                        f'<title>{a.week}: {a.commits} commits</title>'
                        f'</rect>'
                    )
                    labels_svg.append(
                        f'<text x="{x + bar_width/2}" y="{svg_height - 2}" '
                        f'text-anchor="middle" font-size="9" fill="#64748b">{a.week[-2:]}W</text>'
                    )

                parts.append(
                    '<h3>每周提交趋势（最近 12 周）</h3>'
                    f'<svg viewBox="0 0 {svg_width} {svg_height}" width="100%" height="130" style="background:#fafbfc;border-radius:4px;">'
                    f'{"".join(bars_svg)}'
                    f'{"".join(labels_svg)}'
                    f'</svg>'
                )

        # --- 主要贡献者（可折叠） ---
        if result.top_contributors:
            contrib_id = "contrib-detail"
            parts.append(
                f'<h3 class="collapsible open" onclick="toggleSection(\'{contrib_id}\')" id="{contrib_id}-hdr">'
                f'主要贡献者 ({len(result.top_contributors)} 人)'
                f'</h3>'
            )
            rows = "\n".join(
                f'<tr><td>{c.name}</td><td>{c.email}</td><td>{c.commits}</td></tr>'
                for c in result.top_contributors[:10]
            )
            parts.append(
                f'<div class="collapsible-content open" id="{contrib_id}">'
                f'<table>'
                f'<tr><th>名称</th><th>邮箱</th><th>提交数</th></tr>'
                f'{rows}'
                f'</table>'
                f'</div>'
            )

        # --- 高频变更文件（可折叠） ---
        if result.active_files:
            files_id = "active-files-detail"
            parts.append(
                f'<h3 class="collapsible open" onclick="toggleSection(\'{files_id}\')" id="{files_id}-hdr">'
                f'高频变更文件 ({len(result.active_files)} 个)'
                f'</h3>'
            )
            file_rows = "\n".join(
                f'<tr><td style="max-width:400px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="{f.path}">{f.path}</td>'
                f'<td>{f.changes}</td></tr>'
                for f in result.active_files[:20]
            )
            parts.append(
                f'<div class="collapsible-content open" id="{files_id}">'
                f'<table>'
                f'<tr><th>文件</th><th>变更次数</th></tr>'
                f'{file_rows}'
                f'</table>'
                f'</div>'
            )

        return "\n".join(parts)
