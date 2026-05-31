"""RepoLens 完整链路数据对账脚本。

逐层对比：
  L0  GitHub API 真实数据
  L1  本地 git 原生命令
  L2  GitAnalyzer 返回
  L3  Reporter.render() 中传递的值

最终输出对账报告，明确指出差异所在层级。
"""
import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

REPO_URL = "https://github.com/psf/requests"
CLONE_DIR = os.path.join(os.environ.get("TEMP", "/tmp"), "repolens_reconcile")

os.makedirs(CLONE_DIR, exist_ok=True)

SEP = "=" * 70


# ==========================================================================
# L0: GitHub REST API
# ==========================================================================

def get_github_stats(owner: str, repo: str):
    """通过 GitHub REST API 获取仓库统计。"""
    import urllib.request
    import urllib.error

    stats = {}
    # 仓库信息
    try:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{owner}/{repo}",
            headers={"Accept": "application/vnd.github.v3+json", "User-Agent": "RepoLens-Reconcile"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            stats["default_branch"] = data.get("default_branch", "")
            stats["open_issues"] = data.get("open_issues_count", 0)
    except urllib.error.URLError as e:
        stats["error"] = str(e)
    except Exception as e:
        stats["error"] = str(e)

    # 贡献者数
    try:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{owner}/{repo}/contributors?per_page=1&anon=true",
            headers={"Accept": "application/vnd.github.v3+json", "User-Agent": "RepoLens-Reconcile"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            # 从 Link header 取总数
            link = resp.headers.get("Link", "")
            if "page=" in link:
                last = link.rsplit("page=", 1)[-1].split("&")[0].split(">")[0]
                stats["contributors_github"] = int(last)
            else:
                data = json.loads(resp.read().decode())
                stats["contributors_github"] = len(data)
    except Exception:
        stats["contributors_github"] = "N/A"

    return stats


# ==========================================================================
# L1: 本地 git 原生命令
# ==========================================================================

def git_raw(repo_path: str) -> dict:
    """手动执行 git 原生命令获取基准数据。"""
    def run(cmd: list[str]) -> str:
        r = subprocess.run(cmd, capture_output=True, cwd=repo_path, timeout=60)
        return r.stdout.decode("utf-8", errors="replace")

    d = {}

    # 是否浅克隆
    r = run(["git", "rev-parse", "--is-shallow-repository"])
    d["is_shallow"] = r.strip()

    # rev-list 总数
    r = run(["git", "rev-list", "--count", "--no-merges", "HEAD"])
    d["total_commits"] = int(r.strip()) if r.strip().isdigit() else -1

    # shortlog 行数 = unique_contributors
    r = run(["git", "shortlog", "-sne", "HEAD"])
    d["shortlog_lines"] = [l.strip() for l in r.strip().split("\n") if l.strip()]
    d["unique_contributors"] = len(d["shortlog_lines"])

    # 活跃天数
    r = run(["git", "log", "--format=%ci", "--no-merges", "-n", "50000"])
    dates = set()
    for line in r.strip().split("\n"):
        if len(line) >= 10:
            dates.add(line[:10].strip())
    d["active_days"] = len(dates)

    # CI/CD
    wf = Path(repo_path) / ".github" / "workflows"
    d["ci_cd"] = wf.exists() and any(
        f.suffix in (".yml", ".yaml") for f in wf.iterdir()
    ) if wf.exists() else False

    # 仓库年龄 (first commit → last commit)
    r = run(["git", "log", "--reverse", "--format=%ci", "--no-merges", "-n", "1"])
    first = r.strip()[:19] if r.strip() else ""
    r = run(["git", "log", "--format=%ci", "--no-merges", "-n", "1"])
    last = r.strip()[:19] if r.strip() else ""
    d["first_commit"] = first
    d["last_commit"] = last

    return d


# ==========================================================================
# L2: GitAnalyzer
# ==========================================================================

async def run_analyzer(repo_path: str) -> dict:
    """运行 GitAnalyzer，返回完整 model_dump。"""
    from repolens.analyzers.git_analyzer import GitAnalyzer

    analyzer = GitAnalyzer()
    result = await analyzer.run(repo_path)
    return result.model_dump()


# ==========================================================================
# L3: Reporter 传值
# ==========================================================================

# ==========================================================================
# 主流程
# ==========================================================================


async def main():
    print(f"\n{SEP}")
    print("  RepoLens 完整链路数据对账")
    print(f"  仓库: {REPO_URL}")
    print(f"{SEP}")

    # ------------------------------------------------------------------
    # Step 1: Clone
    # ------------------------------------------------------------------
    print("\n[Step 1] 克隆仓库...")
    t0 = time.monotonic()

    def _clone():
        # 先清理旧目录
        if os.path.isdir(CLONE_DIR):
            import shutil
            shutil.rmtree(CLONE_DIR, ignore_errors=True)
        r = subprocess.run(
            ["git", "clone", "--single-branch", REPO_URL, CLONE_DIR],
            capture_output=True, timeout=120,
        )
        if r.returncode != 0:
            err = r.stderr.decode("utf-8", errors="replace")
            print(f"  ❌ clone 失败: {err}")
            sys.exit(1)

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _clone)
    elapsed = time.monotonic() - t0
    print(f"  ✅ clone 完成 ({elapsed:.1f}s)")

    # 检查 .git
    dotgit = os.path.join(CLONE_DIR, ".git")
    print(f"  .git exists = {os.path.isdir(dotgit)}")

    # ------------------------------------------------------------------
    # L0: GitHub API
    # ------------------------------------------------------------------
    print(f"\n{SEP}")
    print("  L0: GitHub REST API 数据")
    print(f"{SEP}")
    gh = get_github_stats("psf", "requests")
    gh_contributors = gh.pop("contributors_github", "N/A")
    for k, v in gh.items():
        print(f"  {k} = {v}")

    # ------------------------------------------------------------------
    # L1: 本地 git 原生命令
    # ------------------------------------------------------------------
    print(f"\n{SEP}")
    print("  L1: 本地 git 原生命令（基准真值）")
    print(f"{SEP}")
    git = git_raw(CLONE_DIR)
    for k, v in git.items():
        if k == "shortlog_lines":
            print(f"  {k} = [{len(v)} 条]")
            for i, line in enumerate(v[:5]):
                print(f"    {i+1}. {line}")
            if len(v) > 5:
                print(f"    ... 共 {len(v)} 人")
        else:
            print(f"  {k} = {v}")

    # ------------------------------------------------------------------
    # L2: GitAnalyzer
    # ------------------------------------------------------------------
    print(f"\n{SEP}")
    print("  L2: GitAnalyzer 输出")
    print(f"{SEP}")
    ga = await run_analyzer(CLONE_DIR)

    # 过滤只显示关键字段
    keys = [
        "total_commits", "commits_per_week", "unique_contributors",
        "active_days", "ci_cd_config", "error", "duration_ms",
    ]
    for k in keys:
        print(f"  {k} = {ga.get(k)}")
    print(f"  top_contributors = [{len(ga.get('top_contributors', []))} 人]")
    for c in ga.get("top_contributors", [])[:5]:
        print(f"    {c.get('name'):<35} {c.get('commits'):>5d} 提交")
    print(f"  activity_over_time = [{len(ga.get('activity_over_time', []))} 周]")
    for a in ga.get("activity_over_time", [])[-5:]:
        print(f"    {a.get('week'):<12} {a.get('commits'):>4d} 提交")

    # ------------------------------------------------------------------
    # L3: Reporter 值（从 GitAnalyzer 到报告中的映射）
    # ------------------------------------------------------------------
    print(f"\n{SEP}")
    print("  L3: Reporter.render() 中的 GitResult 传值")
    print(f"{SEP}")
    from repolens.reporter import Reporter
    from repolens.schemas import GitResult

    # 构造 GitResult 用 GA 返回的数据
    result_obj = GitResult(**{k: v for k, v in ga.items() if k != "error"})
    report = Reporter().render(
        "reconcile", REPO_URL,
        static_result=None,
        repo_result=None,
        git_result=result_obj,
        pipeline_start=time.monotonic() - 5,
    )
    print(f"  Report.health_score = {report.health_score}")
    print(f"  Report.git_analysis.total_commits = {report.git_analysis.total_commits}")
    print(f"  Report.git_analysis.unique_contributors = {report.git_analysis.unique_contributors}")
    print(f"  Report.git_analysis.active_days = {report.git_analysis.active_days}")
    print(f"  Report.git_analysis.commits_per_week = {report.git_analysis.commits_per_week}")

    # ------------------------------------------------------------------
    # 最终对账报告
    # ------------------------------------------------------------------
    print(f"\n{SEP}")
    print("  最终对账报告")
    print(f"{SEP}")

    def green(s): return s
    def red(s): return s

    rows = [
        ("total_commits", git["total_commits"], ga["total_commits"]),
        ("unique_contributors", git["unique_contributors"], ga["unique_contributors"]),
        ("active_days", git["active_days"], ga["active_days"]),
        ("ci_cd_config", git["ci_cd"], ga["ci_cd_config"]),
        ("is_shallow", git["is_shallow"], "—"),
    ]

    fmt = "{:<22} | {:>12} | {:>12} | {}"
    print(fmt.format("指标", "L1-git-raw", "L2-GitAnalyzer", "判定"))
    print("-" * 70)
    all_ok = True
    for name, raw, ana in rows:
        status = "✅" if raw == ana else "❌ DIFF"
        if raw != ana:
            all_ok = False
        print(fmt.format(name, str(raw), str(ana), status))

    # GitHub 对比（contributors 受 API pagination 影响，仅供参考）
    print(f"\n  与 GitHub REST API 交叉对比:")
    print(f"  GitHub contributors ≈ {gh_contributors}")
    print(f"  L1 git shortlog    = {git['unique_contributors']}")
    print(f"  L2 GitAnalyzer     = {ga['unique_contributors']}")

    print(f"\n  分析:")
    if git["is_shallow"] == "true":
        print("  ⚠️ 仓库是浅克隆！GitAnalyzer 检测到后已尝试 deepen。")
        print("  → 如果 deepen 成功，数据应完整。")
        print("  → 如果 deepen 失败，贡献者/提交/活跃天都会偏少。")
    else:
        print("  ✅ 完整的 Git 历史")

    if all_ok:
        print("  ✅ L1(git原生命令) == L2(GitAnalyzer)：数据完全一致")
    else:
        print("  ❌ 存在数据不一致，需进一步排查")

    # cleanup
    import shutil
    shutil.rmtree(CLONE_DIR, ignore_errors=True)
    print(f"\n  🧹 清理完成: {CLONE_DIR}")


if __name__ == "__main__":
    asyncio.run(main())
