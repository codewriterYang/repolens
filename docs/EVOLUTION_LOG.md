# RepoLens 演进日志

## 项目背景

RepoLens 是一个 AI 驱动的 Python 仓库分析平台，由个人开发者独立完成，
采用 Vibe Coding 模式从零到一构建。

作为个人 AI 应用开发实践项目，RepoLens 旨在探索「AI 辅助编程」的全流程：
从架构设计、代码实现、测试验证，到文档编写、代码审查、架构演进，
每一行代码均由个人完成，AI 作为协作伙伴参与整个开发流程。

项目基于 FastAPI 异步后端 + React SPA 前端 + SQLite 持久化 + OpenAI 兼容 LLM，
后续逐步从单一流水线架构演进为 Multi-Agent 分析平台。

---

## Phase 0 — RepoLens MVP

- **时间**：2026-05-31
- **版本**：v1.0.0
- **Commit**：`29a1772`

### 目标

实现最小可用的 Python 仓库分析平台：输入 GitHub URL → 自动克隆 → 多维度分析 → HTML 报告。

### 核心能力

| 能力 | 实现方式 |
|------|---------|
| Git 活动分析 | `git rev-list` + `git shortlog` + `git log` 子进程，统计提交数、贡献者、活跃趋势 |
| 静态代码分析 | Pylint（lint 检查 + 评分）+ Radon（圈复杂度），3 个子进程并行 |
| README 意图分析 | LLM 推理（OpenAI 兼容 API），含启发式回退降级 |
| HTML 报告生成 | 自包含 HTML，含可折叠表格、SVG 趋势图、评分维度柱状图 |
| React 前端 | Vite + TypeScript + Zustand + Tailwind + shadcn/ui |
| SQLite 持久化 | aiosqlite WAL 模式，任务状态 + 报告 + LLM 缓存三张表 |

### 主要技术栈

```
后端:  Python 3.12+ / FastAPI / Pydantic v2 / Uvicorn
AI:    OpenAI Compatible API (response_format=json_object + 0.3 温度)
代码:  Pylint + Radon (subprocess + asyncio.to_thread)
版本:  Git 子进程 (rev-list / shortlog / log / log --name-only)
前端:  React 18 + TypeScript 5 + Vite 6 + Zustand + Tailwind + shadcn/ui
存储:  SQLite (aiosqlite, WAL 模式)
测试:  pytest-asyncio 集成测试
```

### 设计决策

1. **异步优先**：全链路 `asyncio`，后台任务用 `asyncio.create_task` 而非 Celery——项目单机场景不需要分布式队列
2. **无 ORM**：2 张表用原生 SQL + Pydantic 序列化，映射层样板代码量超过 SQL 本身
3. **分析器独立**：三个分析器通过 `asyncio.gather(return_exceptions=True)` 并行，单点失败不崩溃
4. **优雅降级链**：子进程 → 分析器 → 编排器 → Reporter，共 7 层降级路径
5. **双层超时**：分析器级 `wait_for`（120-180s）+ 流水线级 `wait_for`（600s）
6. **LLM 缓存**：`sha256(repo_url|readme_hash|model)` 三维键，避免重复分析时重复调用

### 收获

- `asyncio.to_thread(subprocess.run)` 是在所有平台默认事件循环下运行的唯一可靠方案，
  Windows `ProactorEventLoop` 不支持 `create_subprocess_exec`
- `return_exceptions=True` 是 `asyncio.gather` 并行调度的关键参数——不用它会导致一个子任务失败就全部取消
- SQLite WAL 模式对「前端高频轮询 + 后台低频写入」负载类型非常适配
- Pydantic v2 的 `model_dump_json()` 直接序列化到 SQLite TEXT 字段，零映射成本

---

## Phase 1 — 数据可信度治理与 MVP 修复

- **时间**：2026-05-31
- **版本**：v1.1
- **Commits**：`f028ae4` → `d3d339a` → `d19bbc6`

### 问题发现

MVP 发布后，通过实际分析 `tiangolo/fastapi` 仓库发现多个数据异常：

| 异常 | 表现 | 根因 |
|------|------|------|
| Pylint 评分始终 N/A | 页面显示 N/A | `_PYLINT_SCORE_RE` 正则定义了但从未被调用 |
| Git 提交数偏少 | L1(git原生命令) 7203 提交 vs L2(GitAnalyzer) 仅 1 提交 | 早期用了 `--depth 1` 浅克隆 |
| 时间显示 UTC | 18:00 显示为 10:00 | `datetime.utcnow()` 未转本地时间 |
| 控制台无日志 | uvicorn 运行但看不到分析进度 | `main.py` 缺少 `logging.basicConfig()` |
| pylint 找不到 | `pylint: command not found` | `subprocess.run(["pylint"])` 依赖 PATH，Windows reload 模式下 PATH 不完整 |
| pylint 命令超长 | 1118 个文件路径拼接超 32k | Windows 命令行长度限制 |

### 修复内容

**数据可信度修复**：
- 移除 `--depth 1` 浅克隆，改为完整克隆
- 增加浅克隆检测 `git rev-parse --is-shallow-repository` + 自动 `git fetch --unshallow`
- 新增 `verify_data.py` 数据对账脚本（对比 git 原生命令基准值与分析器输出）
- 删除冗余 `reconcile.py`（功能被 `verify_data.py` 覆盖）

**Pylint 修复**：
- `_parse_pylint_scores()` 增加 `_PYLINT_SCORE_RE` 对 "Your code has been rated at X.XX/10" 的匹配
- `_unwrap_pylint()` 改为优先读取 `__overall__` 键（来自正则匹配），回退计算旧版模块级评分平均值
- 子进程调用从 `pylint` 改为 `python -m pylint / radon`，确保使用 uvicorn 同一 Python 环境
- 子进程参数从逐一传 `.py` 文件改为传目录路径 + `--recursive=y`，规避 Windows 命令行长度限制

**超时配置**：
- `PYLINT_TIMEOUT`: 120s → 300s（1118 文件仓库实际需 ~200s）
- `_TIMEOUT_STATIC`: 180s → 420s
- `clone_timeout_seconds`: 120s → 300s
- `pipeline_timeout_seconds`: 180s → 600s
- 所有超时支持 `.env` 自定义（`PIPELINE_TIMEOUT_SECONDS` / `CLONE_TIMEOUT_SECONDS`）

**环境与日志**：
- `requirements.txt` 新增 `pylint>=3.0` + `radon>=6.0`
- `main.py` 添加 `logging.basicConfig()`，恢复分析器日志输出
- `.env` 缺失时输出警告而非静默失败
- 时间格式统一为 `YYYY-MM-DD HH:MM:SS`（本地时间）

**安全审查**：
- `ReportViewer.vue` iframe sandbox 移除 `allow-same-origin`，防止 XSS 同源访问
- `cloner.py` 本地路径增加系统目录拦截（`/etc`、`/proc`、`C:\Windows` 等）
- `main.py` 断言回退改为 `HTTPException(503)`，`-O` 模式下不失效

**代码质量清理**：
- 前端：删除未使用的 `clampProgress`、`formatDurationMs`、`fetchHealth`、`CardFooter`、
  `lucide-react` 依赖、`warning`/`success` Tailwind 颜色
- 前端：`JobStatus`（store）重命名为 `UiJobStatus`，消除与后端类型冲突

**文档补充**：
- 新增 `WORKFLOW.md`（端到端流程详解）、`frontend/README.md`、`tests/README.md`、`scripts/README.md`
- 重写 `backend/README.md`（从 2 行占位符扩展为完整文档）、`samples/README.md`（推荐测试仓库）
- 新增 `DECISIONS.md`（技术选型说明）

### 对账结果

使用 `verify_data.py` 对 `tiangolo/fastapi` 仓库进行 L1(git原生命令) 与 L2(GitAnalyzer) 对账：

```
total_commits:        L1=7203  L2=7203  ✅
unique_contributors:  L1=931   L2=931   ✅
active_days:          L1=xxx   L2=xxx   ✅
ci_cd_config:         一致            ✅
```

### 测试结果

全部 12 个集成测试用例通过：Schema 序列化、Reporter HTML、数据库操作、错误场景、API 路由。

---

## Phase 2 — Multi-Agent Architecture

- **时间**：2026-06-01
- **版本**：v2.0
- **Commit**：`10814a3`

### 目标

引入 Agent 抽象层，为后续多 Agent 协作奠定基础，而不引入框架级依赖。

### 新增

| 模块 | 文件 | 职责 |
|------|------|------|
| `BaseAgent` | `agents/base.py` | 抽象基类，定义统一 `async run(context, **kwargs)` 接口 |
| `StaticAgent` | `agents/static_agent.py` | 封装 `StaticAnalyzer`，委托代码质量分析 |
| `RepoAgent` | `agents/repo_agent.py` | 封装 `RepoAnalyzer`，委托仓库意图分析（从 Context 获取 repo_url） |
| `GitAgent` | `agents/git_agent.py` | 封装 `GitAnalyzer`，委托 Git 活动分析 |
| `AgentRegistry` | `agents/registry.py` | 注册中心：注册/获取/调度/生命周期管理 |

### 架构变化

```
v1.x:
  Orchestrator ──→ StaticAnalyzer.run()
                ├─→ RepoAnalyzer.run()
                └─→ GitAnalyzer.run()

v2.0:
  Orchestrator ──→ AgentRegistry.get("static") ──→ StaticAgent.run(ctx)
                ├─→ AgentRegistry.get("repo")   ──→ RepoAgent.run(ctx)
                └─→ AgentRegistry.get("git")    ──→ GitAgent.run(ctx)
                     ↑
              AgentRegistry + RepositoryContext
              (register / get / list / run_all)
```

### 设计原则

1. **无侵入**：三个 Analyzer 源码完全不变，Agent 是纯包装层。分析逻辑、超时处理、错误降级一字节未改
2. **接口统一**：`BaseAgent.run(context, **kwargs)` 统一入口，`Registry.run_all()` 批量并行调度
3. **职责分离**：Analyzer 专注分析逻辑，Agent 专注调度与生命周期，Registry 专注注册与发现
4. **零破坏**：前端代码零修改、API 路由零修改、所有现有测试 12/12 通过

### 测试结果

```
=== RepoLens 端到端验证 ===
12/12 全部通过（Schema / Reporter / DB / 错误场景 / API路由）
```

### 收益

- 为后续阶段提供可插拔的 Agent 接口
- `AgentRegistry.run_all()` 可被 Orchestrator Agent 直接调用
- `RepositoryContext` 统一了 Agent 入参，消除 `**kwargs` 传参的不确定性
- Analyzer 源码零改动

---

## Phase 3 — Agent Context Layer

- **时间**：2026-06-01
- **版本**：v2.1
- **Commit**：`24230bc`

### 目标

在 Agent 层和 Orchestrator 之间引入不可变的分析上下文（RepositoryContext），
解耦 Agent 与原始参数的传递方式。`BaseAgent.run(repo_path)` 升级为
`BaseAgent.run(context)`。

### 为什么引入 Context

Phase 2 中 Agent 的 `run()` 接口存在两个问题：

1. **参数不一致**：`StaticAgent.run(repo_path)` 和 `GitAgent.run(repo_path)` 只需路径，
   但 `RepoAgent.run(repo_path, repo_url=...)` 需要通过 `**kwargs` 额外传 `repo_url`。
   `**kwargs` 不够类型安全，且调用方需记住不同 Agent 需要哪些参数。

2. **扩展困难**：未来 Agent 可能需要更多元信息（缓存键、历史快照、分析策略），
   逐参数添加会导致接口持续膨胀。

解决方案：将所有分析上下文封装为不可变对象，Agent 从中按需提取。
这类似 HTTP 框架中 `Request` 对象的设计模式——通过上下文解耦入参。

### 新增

| 模块 | 文件 | 职责 |
|------|------|------|
| `RepositoryContext` | `context/base.py` | 不可变 dataclass（`frozen=True`）：repo_url、repo_path、repo_name、analysis_id、started_at |
| `make_context()` | `context/repository_context.py` | 工厂函数：从原始参数构建 RepositoryContext，自动提取仓库名 |
| `ContextManager` | `context/context_manager.py` | 生命周期管理：`create()` / `validate()` / `create_and_validate()` |

### 架构变化

```
v2.0:
  Orchestrator
    └─→ AgentRegistry.get("static") ──→ StaticAgent.run(repo_path)
         AgentRegistry.get("repo")   ──→ RepoAgent.run(repo_path, repo_url=...)
         AgentRegistry.get("git")    ──→ GitAgent.run(repo_path)

v2.1:
  Orchestrator
    └─→ ContextManager.create(repo_url, repo_path, job_id) ──→ RepositoryContext
         └─→ AgentRegistry.get("static") ──→ StaticAgent.run(ctx)
              AgentRegistry.get("repo")   ──→ RepoAgent.run(ctx)  # ctx.repo_url / ctx.repo_path
              AgentRegistry.get("git")    ──→ GitAgent.run(ctx)
```

### Agent 接口变更

| Agent | v2.0 入参 | v2.1 入参 |
|-------|----------|----------|
| `StaticAgent` | `run(repo_path)` | `run(context)` → `context.repo_path` |
| `RepoAgent` | `run(repo_path, repo_url=xxx)` | `run(context)` → `context.repo_url` + `context.repo_path` |
| `GitAgent` | `run(repo_path)` | `run(context)` → `context.repo_path` |

### 测试结果

```
=== RepoLens 端到端验证 ===
12/12 全部通过（Schema / Reporter / DB / 错误场景 / API路由）
```

### 收益

- Agent 入参接口完全统一：所有 Agent 接收同一个 `RepositoryContext`
- `**kwargs` 被消除：`repo_url` 等额外参数直接从 context 获取
- `frozen=True` 保证上下文不可变，Agent 间无副作用
- Analyzer 源码零改动、API 零改动、前端零改动

---

## Phase 4 — Shared Memory Layer

- **时间**：2026-06-01
- **版本**：v2.2
- **Commit**：待提交

### 目标

在 Agent 架构中引入 SharedMemory，为 Agent 间数据共享铺设基础设施。
当前阶段铺设通道，暂不产生业务使用。

### 为什么引入 SharedMemory

Phase 2-3 中 Agent 之间完全隔离——每个 Agent 独立完成分析后返回结果，
Agent 之间无法在分析过程中共享中间数据。未来场景需要：

- StaticAgent 发现高风险文件后通知 GitAgent 聚焦分析其变更历史
- RepoAgent 识别核心模块后传递给 StaticAgent 提高评分权重
- 多个 Agent 写入同一分析结果供 Reporter 聚合

解决方案：在 Agent 间引入线程安全的共享键值存储，Agent 在 `run()` 中
可读写此存储，Orchestrator 和 Reporter 也可读取。

### 新增

| 模块 | 文件 | 职责 |
|------|------|------|
| `SharedMemory` | `memory/base.py` | 线程安全 KV 存储：`set/get/has/delete/keys/snapshot`，`threading.RLock` |
| `get_by_prefix()` / `batch_set()` | `memory/shared_memory.py` | 辅助函数：按前缀筛选、批量写入 |
| `MemoryManager` | `memory/memory_manager.py` | 生命周期管理：`create()/clear()/get_memory()` |

### 架构变化

```
v2.1:
  Orchestrator → ContextManager → Context → AgentRegistry → Agent

v2.2:
  Orchestrator
    ├─→ ContextManager.create()           → RepositoryContext
    ├─→ MemoryManager.create()            → SharedMemory
    └─→ AgentRegistry.inject_memory()
         └─→ Agent.run(ctx)  # self.memory 可用
```

### Agent 接口变更

| 组件 | 变更 |
|------|------|
| `BaseAgent` | 构造函数新增 `memory: SharedMemory`, 属性 `self.memory` |
| `StaticAgent` | 构造函数新增 `memory` 参数 |
| `RepoAgent` | 构造函数新增 `memory` 参数 |
| `GitAgent` | 构造函数新增 `memory` 参数 |
| `AgentRegistry` | 新增 `inject_memory(memory)` 方法，向所有 Agent 注入 |
| `Orchestrator` | 新增 `MemoryManager`，每流水线 `create()` → `inject_memory()` → 结束后 `clear()` |

### 测试结果

```
=== RepoLens 端到端验证 ===
12/12 全部通过
```

### 收益

- Agent 间数据共享通道已就绪，Phase 5+ 可直接使用
- `threading.RLock` 保证线程安全，兼容 `asyncio.to_thread` 场景
- Memory 每次流水线独立实例，无数据泄漏风险

---

## 后续规划

### Phase 5 — Agent Collaboration

引入协调 Agent（Orchestrator Agent），Agent 间可传递分析结果。例如 StaticAgent 发现高风险文件后通知 GitAgent 聚焦分析该文件的变更历史。

### Phase 5 — Security Agent

新增安全扫描 Agent，集成 Bandit / Semgrep，分析依赖漏洞和代码安全风险。

### Phase 6 — Code Review Agent

LLM 驱动的代码审查 Agent，对高风险文件和函数进行深度语义分析，生成具体重构建议。

### Phase 7 — Multi-Agent Repository Intelligence Platform

完整的多 Agent 仓库智能分析平台，支持多语言（JS/TS/Rust/Go）、多仓库对比、趋势追踪、Webhook 触发。
