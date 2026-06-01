"""
验证 samples/README.md 中仓库的 .py 文件数。
使用与 RepositoryProfiler 完全一致的计数逻辑。
"""
import subprocess, shutil, tempfile
from pathlib import Path

REPOS = [
    {"name": "psf/requests",     "url": "https://github.com/psf/requests",     "claimed": 200 , "claimed_range": "≤500 (full)"},
    {"name": "pallets/flask",    "url": "https://github.com/pallets/flask",    "claimed": 150 , "claimed_range": "≤500 (full)"},
    {"name": "encode/httpx",     "url": "https://github.com/encode/httpx",     "claimed": 300 , "claimed_range": "≤500 (full)"},
    {"name": "tiangolo/fastapi", "url": "https://github.com/tiangolo/fastapi", "claimed": 1100, "claimed_range": ">1000 (fast)"},
    {"name": "pytest-dev/pytest","url": "https://github.com/pytest-dev/pytest","claimed": 600 , "claimed_range": "501-1000 (focused)"},
]

EXCLUDED = {"node_modules", ".git", "__pycache__", ".venv", "venv", "env",
            ".tox", "build", "dist", ".eggs", "site-packages"}

def count_py_files(repo_path: str) -> int:
    """使用与 RepositoryProfiler 完全一致的逻辑计数。"""
    root = Path(repo_path)
    if not root.is_dir():
        return 0
    py_files = [f for f in root.rglob("*.py") if not set(f.parts) & EXCLUDED]
    return len(py_files)

def strategy_label(count: int) -> str:
    if count <= 500:    return "full"
    if count <= 1000:   return "focused"
    return "fast"

print("=" * 60)
print(" RepoLens Samples 仓库文件数实测")
print(" 计数逻辑: rglob *.py, exclude node_modules/.git/venv/etc.")
print("=" * 60)

tmpdir = Path(tempfile.gettempdir()) / "repolens_samples_verify"
tmpdir.mkdir(exist_ok=True)
results = []

for repo in REPOS:
    local = tmpdir / repo["name"].replace("/", "_")

    if not (local / ".git").exists():
        print(f"\n[{repo['name']}] cloning (--depth 1)...")
        subprocess.run(["git", "clone", "--depth", "1", repo["url"], str(local)],
                       capture_output=True, check=True)
    else:
        print(f"\n[{repo['name']}] using cached...")

    actual = count_py_files(str(local))
    actual_s = strategy_label(actual)
    claimed_s = strategy_label(repo["claimed"])
    match = "OK" if actual_s == claimed_s else "WRONG"
    results.append((repo["name"], repo["claimed"], actual, claimed_s, actual_s, match))

    delta = actual - repo["claimed"]
    sign = "+" if delta >= 0 else ""
    print(f"  Claimed : {repo['claimed']:>5} files ({repo['claimed_range']})")
    print(f"  Actual  : {actual:>5} files → {actual_s}")
    print(f"  Delta   : {sign}{delta} / Strategy match: {match}")

# Summary
print("\n" + "=" * 60)
print(" SUMMARY: 推荐策略标签")
print("=" * 60)
for name, claimed, actual, cs, a_s, match in results:
    tag = "[OK]" if match == "OK" else "[XX]"
    print(f"  {tag} {name:<22s} strategy={a_s:<7s} ({actual:>5} files)")

print(f"\nTotal repos: {len(results)} | Matches: {sum(1 for r in results if r[5]=='OK')}/{len(results)}")
print(f"Cache kept at: {tmpdir}")

# 检查覆盖度
modes = {r[4] for r in results}
missing = {"full", "focused", "fast"} - modes
if missing:
    print(f"\n[!] Missing strategy modes: {', '.join(sorted(missing))}")
else:
    print(f"\n[OK] All 3 strategy modes covered")
