# RepoLens 架构文档

## 概述

RepoLens 是一个异步优先的分析流水线，它克隆仓库、并行运行三个独立分析器，并生成结构化 HTML 报告。整个流水线是无状态的 — 每个任务分配 UUID，状态持久化到 SQLite，结果通过 REST 接口获取。

## 系统架构图 

```
┌─────────────────────────────────────────────────────────────────┐
│                        FastAPI 服务器                            │
│                                                                  │
│  POST /api/analyze ──▶ asyncio.create_task(run_pipeline)        │
│                                                                  │
│  GET /api/status/{id} ◀── 读取 analyses 表（轮询）              │
│  GET /api/report/{id}  ◀── 读取 analyses 表（已完成任务）       │
│  GET /api/history       ◀── 读取 analyses 表（全部记录）        │
│  GET /api/health        ◀── 静态返回 200                        │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                       编排器（Orchestrator）                      │
│                                                                  │
│  阶段 1：克隆（300s 超时）                                       │
│  阶段 2：分析（并行，各自独立超时）                               │
│           ├── StaticAnalyzer（420s）— pylint + radon             │
│           ├── RepoAnalyzer（150s）— LLM 推理                     │
│           └── GitAnalyzer（120s）— git 子进程                    │
│  阶段 3：报告 — Reporter.render()                                │
│  阶段 4：持久化 — save_report() 写入 SQLite                     │
│                                                                  │
│  流水线超时：600s（Config.pipeline_timeout_seconds）            │
└─────────────────────────────────────────────────────────────────┘
```

## 数据流

```
repo_url（字符串）
     │
     ▼
  Cloner.clone() ──▶ repo_path（本地文件系统路径）
     │
     ├──────────────────────────────────────────────┐
     │                    │                         │
     ▼                    ▼                         ▼
StaticAnalyzer      RepoAnalyzer              GitAnalyzer
     │                    │                         │
     ▼                    ▼                         ▼
StaticResult        RepoResult                GitResult
（Pydantic）        （Pydantic）              （Pydantic）
     │                    │                         │
     └────────────────────┼─────────────────────────┘
                          │
                          ▼
                   Reporter.render()
                          │
                          ▼
                    ReportJson
                   （health_score、
                    recommendations、
                    html_report、
                    static_analysis、
                    repo_analysis、
                    git_analysis）
```

## Agent 架构（v2.0）

v2.0 引入了 Agent 抽象层，将三个分析器通过统一接口包装。

### BaseAgent 接口

```python
class BaseAgent(ABC):
    name: str

    @abstractmethod
    async def run(self, context: RepositoryContext, **kwargs: Any) -> Any:
        ...
```

### Agent 实现

| Agent | 封装的分析器 | 从 Context 获取 |
|-------|-------------|----------------|
| `StaticAgent` | `StaticAnalyzer` | `context.repo_path` |
| `RepoAgent` | `RepoAnalyzer` | `context.repo_path`, `context.repo_url` |
| `GitAgent` | `GitAnalyzer` | `context.repo_path` |

每个 Agent 是纯包装层 — 内部直接委托给对应 Analyzer，
不修改原有分析逻辑。v2.1 起通过 `RepositoryContext` 获取参数。

### AgentRegistry 设计

```
AgentRegistry
├── register(agent)     # 按 name 注册 Agent
├── get(name) → Agent   # 按名称获取
├── list() → [str]      # 列出已注册名称
└── run_all(tasks, ctx) # 并行调度多个 Agent（统一传递 Context）
```

Orchestrator 通过 AgentRegistry 获取和调度 Agent，
不再直接持有分析器实例。这为后续 Agent 热插拔、
动态启停提供了基础。

## Context 层（v2.1）

v2.1 引入了 Context 抽象层，在 Agent 和 Orchestrator 之间
插入不可变的上下文对象，解耦参数传递。

### RepositoryContext

```python
@dataclass(frozen=True)
class RepositoryContext:
    repo_url: str        # 原始仓库 URL
    repo_path: str       # 克隆后的本地路径
    repo_name: str       # 仓库名（从 URL 提取）
    analysis_id: str     # 唯一 job_id
    started_at: datetime # 分析启动时间
```

`frozen=True` 保证上下文在分析过程中不可被任何 Agent 修改。

### ContextManager

```
ContextManager
├── create(repo_url, repo_path, job_id) → RepositoryContext
├── validate(ctx)                        → 校验完整性
└── create_and_validate(...)             → 创建 + 校验
```

Orchestrator 在克隆完成后调用 `ContextManager.create()` 构建上下文，
通过 AgentRegistry 统一传递给三个 Agent。

### 架构层次

```
Orchestrator
  ├─→ ContextManager.create()       ──→ RepositoryContext
  ├─→ MemoryManager.create()        ──→ SharedMemory
  └─→ AgentRegistry.inject_memory(memory)
       └─→ AgentRegistry.get("static")  ──→ StaticAgent.run(ctx)
           AgentRegistry.get("repo")    ──→ RepoAgent.run(ctx)
           AgentRegistry.get("git")     ──→ GitAgent.run(ctx)
                ↓
           Agent 可通过 self.memory.set/get 共享数据
```

## Memory 层（v2.2）

v2.2 引入了 SharedMemory，Agent 可通过线程安全的键值存储
在分析过程中共享中间结果。

### SharedMemory

```python
class SharedMemory:
    set(key, value) → None       # 写入
    get(key, default=None) → Any # 读取
    has(key) → bool              # 存在检查
    delete(key) → None           # 删除
    keys() → list[str]           # 所有键名
    snapshot() → dict            # 只读快照
    clear() → None               # 清空
```

使用 `threading.RLock` 保证线程安全，兼容 `asyncio.to_thread` 场景。

### MemoryManager

```python
class MemoryManager:
    create() → SharedMemory    # 创建新 Memory 实例
    clear() → None             # 清空当前 Memory
    get_memory() → SharedMemory|None  # 获取引用
```

Orchestrator 每次流水线调用 `create()`，结束后调用 `clear()`。

### Agent 接入（Phase 5: PlannerAgent 协作）

Phase 5–7 实现了完整的动态 Agent 协作链路：

```
Orchestrator → Context+Memory
  ├─→ PlannerAgent.run(ctx)
  │     └─→ DynamicPlanner (Profiler + Rules) → AnalysisPlan
  │           ├─ skipped: file_count>1000→skip static, !readme→skip repo
  │           └─→ memory.set("analysis_plan", plan)
  ├─→ [StaticAgent | RepoAgent | GitAgent].run(ctx)  # 根据 Plan 动态跳过
  │     └─→ memory.set("..._result", result)
  └─→ ReportAgent.run(ctx)
        └─→ memory.get(...) → ReportResult (含 Plan Summary)
```

Phase 7 引入 DynamicPlanner：规则引擎根据仓库特征（文件数、README）
自动决定分析策略，Orchestrator 按 Plan 动态执行——不再硬编码三路并行。

---

## 分析器设计

### StaticAnalyzer（静态分析器）

- **目的**：代码质量指标（复杂度、lint 问题）
- **工具**：pylint（代码检查）、radon（圈复杂度）
- **策略**：3 个子进程并行 → 在内存中合并结果
- **产出**：`StaticResult`，包含文件风险摘要、复杂度热点、pylint 评分
- **降级**：任何失败时返回 `StaticResult(error=...)`

### RepoAnalyzer（仓库分析器）

- **目的**：通过 README、目录树和元数据理解项目意图
- **工具**：LLM（OpenAI 兼容 API），使用结构化提示词
- **策略**：并行加载输入（readme + tree + metadata）→ 带缓存的 LLM 调用
- **产出**：`RepoResult`，包含使用模式、核心模块、推断风险、README 质量
- **降级**：LLM 不可用时启用纯启发式分析（关键词匹配、结构检查）

### GitAnalyzer（Git 分析器）

- **目的**：Git 历史活动、贡献者统计、CI/CD 检测
- **工具**：4 个 git 子进程（`rev-list`、`shortlog`、`log`、`log --name-only`）+ 1 个文件系统 CI 检查
- **策略**：所有 5 个任务通过 `asyncio.gather` 并发运行
- **产出**：`GitResult`，包含提交数、贡献者、活动时间线、活跃文件、CI/CD 状态
- **降级**：每个子进程独立捕获异常；部分数据即可用

## 并发模型

```
asyncio.create_task(orch.run_pipeline(job_id, url))
    │
    ├── await cloner.clone()                     [串行 — 必须先完成]
    │
    ├── await asyncio.gather(                    [并行 — 三个同时启动]
    │       run_static(),                         各自用 asyncio.wait_for() 包装
    │       run_repo(),                           独立超时
    │       run_git(),                            return_exceptions=True
    │   )
    │
    └── reporter.render()                        [串行 — 需要所有结果]
```

关键设计决策：
- `gather()` 中 `return_exceptions=True` 意味着失败的分析器返回其异常对象 — 我们解包并转换为带错误标记的结果对象
- 每个分析器内部使用 `asyncio.wait_for()` 实现双重防护
- 编排器在整个流水线外再包装一层 `asyncio.wait_for()` 作为总超时

## 数据库结构

```sql
CREATE TABLE analyses (
    job_id        TEXT PRIMARY KEY,
    repo_url      TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'queued',
    progress_pct  INTEGER NOT NULL DEFAULT 0,
    stage_label   TEXT NOT NULL DEFAULT '',
    report_json   TEXT,           -- 序列化的 ReportJson
    html_report   TEXT,           -- 自包含 HTML
    health_score  INTEGER,
    error_msg     TEXT,
    duration_ms   INTEGER,
    partial_json  TEXT,           -- 分析器中间输出
    created_at    TEXT,
    updated_at    TEXT
);

CREATE TABLE llm_cache (
    cache_key  TEXT PRIMARY KEY,
    response   TEXT NOT NULL,
    created_at TEXT
);
```

## 错误处理策略

| 层级 | 策略 |
|------|------|
| **分析器子进程** | try/except → 返回带 `error` 字段的结果 |
| **分析器超时** | `asyncio.wait_for()` → 捕获 `TimeoutError` → 返回错误结果 |
| **编排器 gather** | `return_exceptions=True` → 解包异常 → None 结果 |
| **流水线超时** | `asyncio.wait_for(600s)` → `JobStatus.TIMEOUT` 写入数据库 |
| **Reporter** | 处理 `None` 和错误标记的结果 → 仍然生成合法 HTML |
| **API 路由** | 缺失任务返回 `HTTPException(404)`；排队任务返回 `202 Accepted` |

## 安全考量

- **仓库隔离**：每个克隆仓库存放于任务专属临时目录；在 `finally` 代码块中清理
- **LLM Key 隔离**：API Key 仅存在于环境变量中；绝不被记录日志或存入数据库
- **无代码执行**：分析器只读取文件和运行 git/日志工具 — 不含 `eval`、不含 `exec`
- **HTML 输出**：自包含行内样式；不加载外部脚本；仅最小化行内 JS 用于可折叠区域

## 性能分析

目标：普通仓库 < 180 秒，大仓库 < 300 秒（流水线超时 600 秒为硬上限）

瓶颈（按顺序）：
1. **Pylint** — 复杂度 O(文件数 × 行数)；在大型仓库上是主要成本
2. **LLM 调用** — 约 2-5 秒（取决于模型和厂商）；通过仓库内容哈希缓存
3. **Git log** — 复杂度 O(提交数)；对于 < 1 万次提交的仓库可忽略不计

优化措施：
- LLM 响应缓存在 SQLite 中（缓存键 = `sha256(repo_url + readme_hash + model)`）
- StaticAnalyzer 在并行子进程中运行 pylint/radon
- Git 命令使用 `--no-renames` 避免昂贵的重命名检测
