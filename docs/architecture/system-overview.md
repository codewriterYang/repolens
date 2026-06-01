# RepoLens 系统架构总览

## 整体架构

```mermaid
graph TD
    subgraph Frontend["前端 (React + TypeScript)"]
        UI[RepoInput] --> |POST /api/analyze| API
        Status[ProgressPanel] --> |轮询 /api/status| API
        Report[ReportViewer] --> |GET /api/report| API
        Hist[HistoryList] --> |GET /api/history| API
    end

    subgraph Backend["后端 (FastAPI + asyncio)"]
        API[FastAPI Routes] --> Orch[Orchestrator]
        Orch --> Clone[RepoCloner]
        Clone --> |repo_path| CM[ContextManager]
        CM --> |RepositoryContext| Orch

        Orch --> |create| MM[MemoryManager]
        MM --> |SharedMemory| Agents

        Orch --> Planner[PlannerAgent]
        Planner --> |DynamicPlanner| Rules[PlanningRules]
        Rules --> |RepositoryProfiler| Profile[仓库特征分析]
        Planner --> |AnalysisPlan| Mem[(SharedMemory)]

        Orch --> Static[StaticAgent]
        Orch --> Repo[RepoAgent]
        Orch --> Git[GitAgent]

        Static --> |StaticAnalyzer| Pylint[pylint + radon]
        Repo --> |RepoAnalyzer| LLM[LLM 推理]
        Git --> |GitAnalyzer| GitLog[git log]

        Static --> |StaticResult| Mem
        Repo --> |RepoResult| Mem
        Git --> |GitResult| Mem

        Orch --> Reporter[Reporter]
        Reporter --> |ReportJson| DB[(SQLite)]
    end

    API --> DB
    DB --> |report_json| API
```

## 核心模块

| 层 | 模块 | 职责 |
|----|------|------|
| API | `main.py` | FastAPI 路由，6 个端点 |
| 编排 | `orchestrator.py` | 管理流水线生命周期：克隆 → 分析 → 报告 |
| Agent | `agents/` | 7 个 Agent（Planner/Static/Repo/Git/Report + Registry） |
| 上下文 | `context/` | RepositoryContext 不可变分析上下文 |
| 记忆 | `memory/` | SharedMemory 线程安全 KV 共享存储 |
| 规划 | `planner/` | DynamicPlanner + PlanningRules 策略引擎 |
| 分析 | `analyzers/` | StaticAnalyzer/RepoAnalyzer/GitAnalyzer |
| 报告 | `reporter.py` | HTML 报告生成，健康评分，改进建议 |
| 持久化 | `db.py` | SQLite 存储（aiosqlite 异步） |

## 数据流

```
POST /api/analyze
  → Orchestrator.run_pipeline()
    → Clone repo
    → ContextManager.create() → RepositoryContext
    → MemoryManager.create()  → SharedMemory
    → PlannerAgent.run(ctx)   → AnalysisPlan(strategy)
    → StaticAgent.run(ctx)    → StaticResult
    → RepoAgent.run(ctx)      → RepoResult
    → GitAgent.run(ctx)       → GitResult
    → Reporter.render()       → ReportJson
    → save_report()           → SQLite
  → GET /api/report/{id}      → ReportJson
```

## 策略引擎

仓库规模决定 StaticAgent 的执行深度（所有 Agent 始终执行）：

| 文件数 | 策略 | 置信度 | 行为 |
|--------|------|--------|------|
| ≤ 500 | full | 100% | 完整 pylint + radon |
| 501-1000 | focused | 75% | 非测试文件 pylint + 全量 radon |
| > 1000 | fast | 50% | 仅 radon cc |
