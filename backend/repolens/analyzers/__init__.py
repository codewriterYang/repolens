"""RepoLens 分析器 — 独立的分析模块。

每个分析器是自包含的，通过 subprocess.run + asyncio.to_thread 运行，
产出带类型的 Pydantic 结果。分析器失败不会导致整体崩溃 —
编排器负责优雅降级处理。
"""