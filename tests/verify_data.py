"""RepoLens MVP 数据正确性排查脚本。
对指定仓库手动采集 Git 基准数据，与 RepoLens 分析器输出逐项对比。
"""
import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path

# 确保 backend 可导入
BACKEND = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(BACKEND))


def run_cmd(cmd: list[str], cwd: str, timeout: int = 60) -> str:
    """运行命令并返回 stdout。"""
    result = subprocess.run(cmd, capture_output=True, cwd=cwd, timeout=timeout)
    return result.stdout.decode("utf-8", errors="replace")


def get_baseline(repo_path: str) -> dict:
    """手动采集 Git 基准数据。"""
    baseline: dict = {}

    # — 总提交数（非合并） —
    raw = run_cmd(
        ["git", "rev-list", "--count", "--no-merges", "HEAD"], cwd=repo_path
    )
    baseline["total_commits"] = int(raw.strip()) if raw.strip().isdigit() else 0

    # — 贡献者 —
    raw = run_cmd(["git", "shortlog", "-sne", "HEAD"], cwd=repo_path)
    baseline["shortlog_lines"] = [l.strip() for l in raw.strip().split("\n") if l.strip()]
    baseline["unique_contributors"] = len(baseline["shortlog_lines"])

    # — 活跃天数 —
    raw = run_cmd(
        ["git", "log", "--format=%ci", "--no-merges", "-n", "5000"], cwd=repo_path
    )
    dates = set()
    for line in raw.strip().split("\n"):
        if line:
            dates.add(line[:10].strip())  # YYYY-MM-DD
    baseline["active_days"] = len(dates)

    # — 每周提交（近 90 天） —
    raw = run_cmd(
        ["git", "log", "--format=%ci", "--no-merges", "--since=90.days.ago", "-n", "5000"],
        cwd=repo_path,
    )
    weeks: dict[str, int] = {}
    from datetime import datetime
    for line in raw.strip().split("\n"):
        if len(line) >= 19:
            try:
                dt = datetime.strptime(line[:19], "%Y-%m-%d %H:%M:%S")
                iso = dt.isocalendar()
                wk = f"{iso[0]}-W{iso[1]:02d}"
                weeks[wk] = weeks.get(wk, 0) + 1
            except ValueError:
                continue
    baseline["weeks_90d"] = weeks
    total_90d = sum(weeks.values())
    baseline["commits_per_week_90d"] = round(total_90d / max(1, len(weeks)), 1) if weeks else 0.0

    # — CI/CD 检测 —
    wf_dir = Path(repo_path) / ".github" / "workflows"
    baseline["ci_cd"] = wf_dir.exists() and any(
        f.suffix in (".yml", ".yaml") for f in wf_dir.iterdir()
    ) if wf_dir.exists() else False

    # — 活跃文件（近 90 天） —
    raw = run_cmd(
        ["git", "log", "--name-only", "--format=", "--no-merges", "--since=90.days.ago", "-n", "5000"],
        cwd=repo_path,
    )
    from collections import Counter
    counter: Counter[str] = Counter()
    for line in raw.strip().split("\n"):
        p = line.strip()
        if p:
            counter[p] += 1
    baseline["active_files_top10"] = counter.most_common(10)

    # — Python 文件统计 —
    py_files = list(Path(repo_path).rglob("*.py"))
    excluded = {"node_modules", ".git", "__pycache__", ".venv", "venv", "env", ".tox", "build", "dist", ".eggs", "site-packages", "__pypackages__"}
    py_files = [f for f in py_files if not set(f.parts) & excluded]
    baseline["total_py_files"] = len(py_files)

    return baseline


def print_baseline(label: str, baseline: dict) -> None:
    """打印基准数据。"""
    print(f"\n{'='*60}")
    print(f"  基准数据: {label}")
    print(f"{'='*60}")
    print(f"  总提交数(非合并) : {baseline['total_commits']:,}")
    print(f"  unique_contributors : {baseline['unique_contributors']}")
    print(f"  active_days         : {baseline['active_days']}")
    print(f"  近90天周均提交     : {baseline['commits_per_week_90d']}")
    print(f"  近90天周数         : {len(baseline['weeks_90d'])}")
    print(f"  CI/CD 配置         : {'✅ 有' if baseline['ci_cd'] else '❌ 无'}")
    print(f"  Python 文件数      : {baseline['total_py_files']}")
    print(f"  贡献者列表:") if baseline["shortlog_lines"] else None
    for i, line in enumerate(baseline["shortlog_lines"][:15]):
        print(f"    {i+1:2d}. {line}")
    if len(baseline["shortlog_lines"]) > 15:
        print(f"    ... 共 {len(baseline['shortlog_lines'])} 人")
    print(f"  高频变更文件 Top 10:")
    for i, (path, count) in enumerate(baseline["active_files_top10"][:10]):
        print(f"    {i+1:2d}. [{count:3d}] {path}")


async def run_repolens(repo_path: str, repo_url: str = "local"):
    """运行 RepoLens 三个分析器，返回结果。"""
    from repolens.analyzers.static_analyzer import StaticAnalyzer
    from repolens.analyzers.git_analyzer import GitAnalyzer
    from repolens.reporter import Reporter

    git = GitAnalyzer()
    static = StaticAnalyzer()
    reporter = Reporter()

    t0 = time.monotonic()

    git_result, static_result = await asyncio.gather(
        git.run(repo_path),
        static.run(repo_path),
    )

    report = reporter.render(
        "verify", repo_url,
        static_result=static_result,
        repo_result=None,
        git_result=git_result,
        pipeline_start=t0,
    )

    return git_result, static_result, report


def compare(git_result, static_result, report, baseline: dict) -> list[dict]:
    """逐项对比，返回差异表。"""
    rows: list[dict] = []

    def add(metric: str, repolens_val, baseline_val, status: str = "✅"):
        rows.append({
            "指标": metric,
            "RepoLens": str(repolens_val),
            "基准值": str(baseline_val),
            "状态": status,
        })

    # Git
    add("总提交数", git_result.total_commits, baseline["total_commits"],
        "✅" if git_result.total_commits == baseline["total_commits"] else "⚠️")
    add("unique_contributors", git_result.unique_contributors, baseline["unique_contributors"],
        "✅" if git_result.unique_contributors == baseline["unique_contributors"] else "⚠️")
    add("active_days", git_result.active_days, baseline["active_days"],
        "✅" if git_result.active_days > 0 else "⚠️ 注意: 按 GitResult 的定义")
    add("近90天周均提交", git_result.commits_per_week, baseline["commits_per_week_90d"],
        "ℹ️" if abs(git_result.commits_per_week - baseline["commits_per_week_90d"]) < 2 else "⚠️")
    add("activity_over_time 周数", len(git_result.activity_over_time), len(baseline["weeks_90d"]),
        "✅" if abs(len(git_result.activity_over_time) - len(baseline["weeks_90d"])) < 3 else "⚠️")
    add("CI/CD 检测", git_result.ci_cd_config, baseline["ci_cd"],
        "✅" if git_result.ci_cd_config == baseline["ci_cd"] else "⚠️")

    # Static
    add("扫描文件数", static_result.total_files_scanned, baseline["total_py_files"],
        "✅" if static_result.total_files_scanned > 0 else "⚠️")
    add("pylint_score", static_result.pylint_score, "(0.0-10.0)",
        "✅" if static_result.pylint_score is not None else "⚠️ 未安装 pylint")
    n_high = len(static_result.high_complexity_functions)
    n_high_risk = sum(1 for f in static_result.high_complexity_functions if f.risk_level.value == "high")
    add("高复杂度函数数", n_high, f"≥10 (共{n_high_risk}个HIGH)",
        "✅" if n_high >= 0 else "⚠️")
    n_risk_files = len(static_result.file_risk_summary)
    add("file_risk_summary 条目", n_risk_files, f"(≤ 扫描文件数 {static_result.total_files_scanned})",
        "✅" if n_risk_files <= max(1, static_result.total_files_scanned) else "⚠️")

    # Health
    add("健康评分", report.health_score, "0-100",
        "✅" if 0 <= report.health_score <= 100 else "⚠️")

    # 贡献者详情
    add("top_contributors 条目", len(git_result.top_contributors),
        f"最多 10 (共 {baseline['unique_contributors']} 人)",
        "✅" if len(git_result.top_contributors) <= 10 else "⚠️")
    if git_result.top_contributors and baseline["shortlog_lines"]:
        top_c = git_result.top_contributors[0]
        first_baseline = baseline["shortlog_lines"][0]
        add("Top1 贡献者提交数", top_c.commits, f"基准: {first_baseline}",
            "✅ 待人工核对")

    return rows


def print_table(rows: list[dict]) -> None:
    """打印对比表。"""
    print(f"\n{'='*90}")
    print(f"  指标对比表")
    print(f"{'='*90}")
    header = f"{'指标':<24} | {'RepoLens':<18} | {'基准值':<24} | 状态"
    print(header)
    print("-" * len(header))
    for row in rows:
        print(f"{row['指标']:<24} | {row['RepoLens']:<18} | {row['基准值']:<24} | {row['状态']}")
    print("-" * len(header))

    issues = [r for r in rows if r["状态"].startswith("⚠️")]
    if issues:
        print(f"\n⚠️ 需关注的指标 ({len(issues)} 项):")
        for r in issues:
            print(f"   - {r['指标']}: RepoLens={r['RepoLens']} vs 基准={r['基准值']}")
    else:
        print("\n✅ 所有指标无异常")


async def main():
    import sys

    if len(sys.argv) < 2:
        print("用法: python verify_data.py <repo_path>")
        print("示例: python verify_data.py C:/tmp/requests")
        sys.exit(1)

    repo_path = sys.argv[1]
    if not Path(repo_path).is_dir():
        print(f"❌ 目录不存在: {repo_path}")
        sys.exit(1)

    # 1) 基准数据
    print("\n[1/3] 正在采集基准数据...")
    baseline = get_baseline(repo_path)
    print_baseline(repo_path, baseline)

    # 2) RepoLens 分析
    print("\n[2/3] 正在运行 RepoLens 分析器...")
    git_result, static_result, report = await run_repolens(repo_path)

    print(f"\n{'='*60}")
    print(f"  RepoLens 分析结果")
    print(f"{'='*60}")
    print(f"  Git:   提交={git_result.total_commits:,} 贡献者={git_result.unique_contributors} "
          f"活跃天={git_result.active_days} 周均={git_result.commits_per_week} "
          f"CI={'✅' if git_result.ci_cd_config else '❌'}")
    if git_result.error:
        print(f"  Git 错误: {git_result.error}")
    print(f"  Static: 扫描={static_result.total_files_scanned} 文件 "
          f"pylint={static_result.pylint_score} "
          f"高复杂度={len(static_result.high_complexity_functions)} "
          f"风险摘要={len(static_result.file_risk_summary)}")
    if static_result.error:
        print(f"  Static 错误: {static_result.error}")
    print(f"  Health: {report.health_score}/100 建议={len(report.recommendations)}")

    # 3) 打印贡献者列表
    if git_result.top_contributors:
        print(f"\n  RepoLens top_contributors:")
        for i, c in enumerate(git_result.top_contributors):
            print(f"    {i+1:2d}. {c.name:<30} {c.email:<40} {c.commits:>5d} 提交")

    # 4) 打印风险文件统计
    if static_result.file_risk_summary:
        from collections import Counter
        risk_dist = Counter(s.risk_level.value for s in static_result.file_risk_summary)
        print(f"\n  文件风险分布: HIGH={risk_dist.get('high',0)} MEDIUM={risk_dist.get('medium',0)} LOW={risk_dist.get('low',0)}")

    # 5) 对比
    rows = compare(git_result, static_result, report, baseline)
    print_table(rows)

    # 6) 健康评分公式
    print(f"\n{'='*60}")
    print(f"  健康评分公式说明")
    print(f"{'='*60}")
    print(f"  总分 = 代码质量(0-40) + 仓库清晰度(0-30) + 社区活跃(0-20) + 工程实践(0-10)")
    print(f"  代码质量: 复杂度密度分(0-20) + pylint 评分分(0-20)  → 来源: StaticAnalyzer")
    print(f"  社区活跃: 周均提交档位(0-10) + 贡献者数档位(0-10) → 来源: GitAnalyzer")
    print(f"  工程实践: CI/CD 存在 10 分, 否则 0                → 来源: GitAnalyzer")


if __name__ == "__main__":
    asyncio.run(main())
