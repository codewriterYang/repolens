# RepoLens 系统总览文档

> 重点：数据模型 · 流程逻辑 · 架构设计

---

## 一、项目概述

**RepoLens** 是一个 AI 驱动的 GitHub 仓库分析平台，覆盖 **仓库克隆 → 三路并行分析 → 健康评分 → HTML 报告生成** 全链路。

- **领域**：Python 仓库的代码质量、项目意图、Git 活动分析
- **三路分析器并行**：
  - **StaticAnalyzer（静态分析）**：pylint + radon → 代码质量指标
  - **RepoAnalyzer（仓库分析）**：README + 目录树 + LLM 推理 → 项目意图理解
  - **GitAnalyzer（Git 分析）**：git 子进程 → 提交历史、贡献者、CI/CD
- **核心能力**：异步并行编排、优雅降级、LLM 缓存、自包含 HTML 报告、前后端分离
- **输出**：0-100 健康评分 + 三级优先级改进建议 + 行内 SVG 图表 + 可折叠文件风险表

---

## 二、数据模型

### 2.1 API 契约（Pydantic Schema）

RepoLens 使用 Pydantic v2 定义端到端的类型安全契约。共定义 **20 个模型类**，覆盖请求、响应、分析结果、报告四个层面。

#### 请求

| 模型 | 字段 | 说明 |
|------|------|------|
| `AnalyzeRequest` | `repo_url: str` (1-512字符) | GitHub URL 或本地文件系统路径 |

#### 响应

| 模型 | 关键字段 | 说明 |
|------|---------|------|
| `AnalyzeResponse` | `job_id, status` | 提交成功立即返回，status=queued |
| `StatusResponse` | `job_id, status, progress_pct, stage_label, partial_results` | 前端轮询进度 + 中间数据 |
| `HistoryItem` | `job_id, repo_url, status, health_score, created_at, duration_ms` | 历史列表条目 |
| `HealthResponse` | `status: "ok"` | 健康检查 |

#### 分析器结果

| 模型 | 关键字段 | 来源 |
|------|---------|------|
| `StaticResult` | `high_complexity_functions, file_heatmap, file_risk_summary, total_files_scanned, pylint_score` | StaticAnalyzer |
| `RepoResult` | `usage_patterns, core_modules, summary, readme_quality_score, inferred_risks` | RepoAnalyzer |
| `GitResult` | `total_commits, commits_per_week, unique_contributors, active_days, top_contributors, active_files, activity_over_time, ci_cd_config` | GitAnalyzer |

#### 报告聚合

| 模型 | 关键字段 | 说明 |
|------|---------|------|
| `ReportJson` | `job_id, repo_url, health_score(0-100), static_analysis, repo_analysis, git_analysis, recommendations, html_report, total_duration_ms` | 最终聚合报告 |
| `Recommendation` | `priority(1/2/3), category, title, detail` | 三级优先级改进建议 |

> 所有枚举均使用 `str, Enum` 基类，保证 JSON 序列化为人类可读字符串而非整数。

### 2.2 数据库结构（SQLite）

```sql
CREATE TABLE analyses (
    job_id        TEXT PRIMARY KEY,
    repo_url      TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'queued',
    progress_pct  INTEGER NOT NULL DEFAULT 0,
    stage_label   TEXT NOT NULL DEFAULT '',
    report_json   TEXT,           -- 序列化的 ReportJson
    html_report   TEXT,           -- 自包含 HTML 字符串
    health_score  INTEGER,
    error_msg     TEXT,
    duration_ms   INTEGER,
    partial_json  TEXT,           -- 分析器中间输出（合并而非覆盖）
    created_at    TEXT,
    updated_at    TEXT
);

CREATE TABLE llm_cache (
    cache_key  TEXT PRIMARY KEY,  -- sha256(repo_url|readme_hash|model)[:32]
    response   TEXT NOT NULL,
    created_at TEXT
);
```

设计要点：
- **无 ORM**，直接使用 `aiosqlite` + 原生 SQL + `Pydantic.model_dump_json()` 序列化
- `partial_json` 采用**合并策略**（多次调用 UPDATE 时 merge 而非覆盖），确保各分析器独立完成的结果都能被前端获取
- `llm_cache` 按 `(repo_url, README内容哈希, 模型名)` 复合键缓存，防止对同一仓库重复调用 LLM
- `PRAGMA journal_mode=WAL` 提升并发读性能

### 2.3 配置模型

```python
@dataclass
class Config:
    # LLM
    llm_base_url: str        # 默认 https://api.openai.com/v1
    llm_api_key: str         # 从环境变量 LLM_API_KEY 读取
    llm_model: str           # 默认 gpt-4o-mini
    llm_timeout_seconds: 60

    # 流水线
    pipeline_timeout_seconds: 600   # 总超时
    clone_timeout_seconds: 300      # 克隆超时

    # 存储
    db_path: str                    # 默认 data/repolens.db
    tmp_dir: str                    # 克隆临时目录（自动适配系统临时目录）

    # 服务器
    host: str      # 默认 0.0.0.0
    port: int      # 默认 8770
```

> 使用 `@dataclass` + `field(default_factory=...)` 而非 Pydantic Settings，保持极简依赖。

---

## 三、流程逻辑

### 3.1 总体流水线

```
POST /api/analyze  →  后台任务 (asyncio.create_task)
                           │
    ┌──────────────────────┼──────────────────────┐
    │ 阶段一: 克隆                                   │
    │   RepoCloner.clone(repo_url, job_id)          │
    │   ├─ HTTP(S) URL → git clone --single-branch  │
    │   │     到 tmp_dir/repo_{job_id[:12]}         │
    │   └─ 本地路径 → 验证目录存在 + 安全检查        │
    │   超时: 300s                                   │
    └──────────────────────┬──────────────────────┘
                           │
    ┌──────────────────────┼──────────────────────┐
    │ 阶段二: 三路并行分析                            │
    │   asyncio.gather(                              │
    │     run_static(),   ← 420s 超时               │
    │     run_repo(),     ← 150s 超时               │
    │     run_git(),      ← 120s 超时               │
    │     return_exceptions=True                     │
    │   )                                            │
    │   ↓                                            │
    │   save_partial_results() 到 SQLite             │
    └──────────────────────┬──────────────────────┘
                           │
    ┌──────────────────────┼──────────────────────┐
    │ 阶段三: 报告生成                                │
    │   Reporter.render(                             │
    │     static_result, repo_result, git_result     │
    │   )                                            │
    │   → 健康评分(4维度) + 改进建议 + HTML报告      │
    └──────────────────────┬──────────────────────┘
                           │
    ┌──────────────────────┼──────────────────────┐
    │ 阶段四: 持久化                                  │
    │   save_report(db, job_id, report)              │
    │   → status='completed', progress_pct=100       │
    └──────────────────────┴──────────────────────┘
                           │
                     finally: cleanup()  清理克隆目录
```

### 3.2 StaticAnalyzer 详细流程

```
StaticAnalyzer.run(repo_path)
 ├─ _collect_python_files(repo_path)
 │     rglob("*.py") + 排除 node_modules/.git/__pycache__/.venv 等
 │
 ├─ [并行] asyncio.gather:
 │     ├─ _run_pylint_json()      # pylint --output-format=json
 │     │     → 按文件分组 {filepath: [msg_dict, ...]}
 │     │     退出码位掩码: bit5 (32)=调用错误, bit0-4=lint发现（正常）
 │     │
 │     ├─ _run_pylint_score()     # pylint --score=y --output-format=text
 │     │     正则解析 "rated at X.XX/10" → 总体评分
 │     │
 │     └─ _run_radon()            # radon cc --json --min=B
 │           → [{file, lineno, name, complexity, rank}, ...]
 │           筛选 CC >= 10 (MEDIUM) / CC >= 20 (HIGH)
 │
 ├─ _unwrap_pylint()              # 规范化为 _PylintOutput
 │     处理子进程任一失败的情况
 │
 ├─ _build_heatmap()              # pylint消息 → {file: [LineRisk]}
 │     error/fatal→HIGH, warning→MEDIUM, 其余→LOW
 │
 └─ _build_file_risk_summary()    # 聚合 lint + 复杂度
       每文件: 最大CC + lint严重度 → HIGH/MEDIUM/LOW
       排序: HIGH→MEDIUM→LOW, 同级按问题数降序
```

### 3.3 RepoAnalyzer 详细流程

```
RepoAnalyzer.run(repo_path, repo_url)
 ├─ [阶段1: 并行加载输入] asyncio.gather:
 │     ├─ _load_readme()           # 读前8000字符（7种文件名fallback + glob）
 │     ├─ _build_tree()            # os.walk 3层深，只展示关键文件类型
 │     └─ _extract_metadata()      # 检测 pyproject.toml/setup.py/tests/docs/依赖
 │
 ├─ [阶段2: LLM推理] 可能失败 → 自动回退
 │     ├─ 构建 user_prompt (README + 目录树 + 元数据提示)
 │     ├─ cache_key = sha256(repo_url|content_hash|model)[:32]
 │     ├─ LLMService.chat(system_prompt, user_prompt, temp=0.3, cache_key)
 │     │     response_format={"type": "json_object"}
 │     └─ _parse_llm_json() 解析 + 截断修复（关闭未闭合 {}[]）
 │         解析失败 → llm_data=None → 触发启发式回退
 │
 └─ [阶段3: 结果组装] _build_result()
       ├─ llm_data 可用 → 权威来源
       ├─ llm_data=None → _heuristic_analysis()
       │     关键词匹配使用模式 + 顶级目录作为核心模块 + README首行摘要
       └─ _score_readme() 纯启发式 (长度+结构+徽章+安装说明+示例 = 0-100)
```

**LLM 降级链**：
```
LLM 调用成功 + JSON 解析成功  →  使用 LLM 数据（权威来源）
LLM 超时 / 异常              →  纯启发式回退（关键词匹配 + 元数据信号）
LLM 返回非法 JSON            →  同超时，触发启发式回退
```

### 3.4 GitAnalyzer 详细流程

```
GitAnalyzer.run(repo_path)
 ├─ 检查 .git 目录是否存在 → 不是仓库直接返回 error
 ├─ _check_shallow() → 浅克隆检测
 │     └─ 浅克隆 → _unshallow() (git fetch --unshallow, 120s超时)
 │
 ├─ [并行] asyncio.gather (5个子进程):
 │     ├─ _run_rev_count()        # git rev-list --count --no-merges HEAD
 │     ├─ _run_shortlog()         # git shortlog -sne HEAD
 │     │     正则解析 "  42  Alice <email>" → [Contributor]
 │     ├─ _run_log_timeline()     # git log --format=%H|%ae|%ci --no-merges
 │     │     解析 ISO 日期 → 周聚合 + 活跃天数
 │     ├─ _run_file_freq()        # git log --name-only --format= --no-merges --no-renames
 │     │     Counter.most_common(50) → [ActiveFile]
 │     └─ _check_ci()             # os.listdir(.github/workflows/*.yml)
 │
 └─ 解包 gather 结果（BaseException → None/空列表）
       _safe_int() / _safe_bool() 兜底类型安全
```

### 3.5 Reporter 报告生成流程

```
Reporter.render(job_id, repo_url, static, repo, git, pipeline_start)
 ├─ _compute_health_score()  ──── 返回 {code_quality, repo_clarity, community, engineering}
 │     ├─ 代码质量 (0-40): 复杂度密度(20) + pylint评分(20)
 │     ├─ 仓库清晰度 (0-30): 有使用模式+15 + README质量按比例折算
 │     ├─ 社区活跃 (0-20): 周提交>=7→10 + 贡献者>=5→10
 │     └─ 工程实践 (0-10): 有CI/CD→10
 │
 ├─ _build_recommendations() ──── 生成优先级建议列表
 │     ├─ 优先级1: 高风险文件、高频+高风险重叠(热点)、高风险推断
 │     ├─ 优先级2: 无CI/CD、贡献者<2、未识别核心模块
 │     └─ 优先级3: 低活跃度、中复杂度函数>5、文档缺失
 │
 └─ _build_html()  ──── 自包含 HTML 输出
       ├─ 健康评分圆形仪表盘 + 4维度柱状图
       ├─ 改进建议 (按优先级分组, 彩色左边框)
       ├─ 代码质量: 统计摘要 + 可折叠文件风险表 (HIGH/MEDIUM/LOW分组) + 高复杂度函数表
       ├─ 仓库洞察: 使用模式、核心模块、风险表
       └─ Git 活动: 统计摘要 + 行内 SVG 周提交趋势图 + 可折叠贡献者/活跃文件表
```

---

## 四、架构设计

### 4.1 整体分层

```
┌─────────────────────────────────────────────────────────────────┐
│  Web 前端 (React 18 + Vite 6 + TS + Tailwind 4 + shadcn/ui)     │
│  RepoInput | ProgressPanel | ReportViewer(iframe) | HistoryList │
│  Zustand store → useAnalysisJob hook → api.ts (Axios)           │
└────────────┬────────────────────────────────────────────────────┘
             │ HTTP (Vite proxy /api → 后端)
┌────────────▼────────────────────────────────────────────────────┐
│  FastAPI 后端 (server/)                                          │
│  lifespan: 初始化 aiosqlite + LLMService + Orchestrator          │
│  6 个路由: /analyze /status/{id} /report/{id} /report/{id}/html│
│            /history /health                                      │
│  模块级单例 (_db, _orchestrator) — 无 DI 框架                    │
└────────┬──────────────────────────────────┬──────────────────────┘
         │                                  │
┌────────▼──────────┐              ┌────────▼──────────┐
│  编排器            │              │  数据库             │
│  Orchestrator     │              │  aiosqlite (WAL)   │
│  4 阶段流水线      │              │  analyses + llm_cache│
│  超时: 600s       │              │  原生 SQL + Row    │
└────────┬──────────┘              └────────────────────┘
         │
    ┌────┼────────────────────┐
    │    │                    │
┌───▼──┐┌───▼──┐        ┌───▼──┐
│Static││Repo  │        │Git   │
│Analy ││Analy │        │Analy │
│zer   ││zer   │        │zer   │
│      ││      │        │      │
│pylint││README│        │git   │
│+     ││+树   │        │子进程│
│radon ││+LLM  │        │      │
└──┬───┘└──┬───┘        └──┬───┘
   │       │               │
   ▼       ▼               ▼
StaticResult RepoResult GitResult
         │
         ▼
    Reporter
         │
         ▼
    ReportJson
```

### 4.2 模块清单

| 模块 | 关键类 | 职责 |
|------|-------|------|
| `config.py` | `Config` (dataclass) | 环境变量加载 + 默认值，全局单例 `config` |
| `schemas.py` | 20 个 Pydantic 模型 | API 契约、分析结果、报告的全部数据结构 |
| `main.py` | `app` (FastAPI), `lifespan` | 应用入口、路由注册、CORS、生命周期管理 |
| `orchestrator.py` | `Orchestrator` | 4 阶段流水线编排：克隆→分析→报告→持久化 |
| `cloner.py` | `RepoCloner` | git clone（线程中 subprocess.run）+ 本地路径验证 + 清理 |
| `llm_service.py` | `LLMService` | OpenAI 兼容 API + 重试 + SQLite 缓存 |
| `db.py` | `init_db`, CRUD 函数 | SQLite 初始化、任务状态、报告、LLM 缓存的读写 |
| `reporter.py` | `Reporter` | 健康评分、改进建议、HTML 生成（折叠+SVG） |
| `analyzers/static_analyzer.py` | `StaticAnalyzer` | pylint(JSON+文本) + radon(CC) 并行子进程 |
| `analyzers/repo_analyzer.py` | `RepoAnalyzer` | README+树+元数据 → LLM推理 → 启发式回退 |
| `analyzers/git_analyzer.py` | `GitAnalyzer` | 5 个 git 子进程并行 → 活动/贡献者/CI |

### 4.3 关键设计模式

| 模式 | 应用位置 | 说明 |
|------|---------|------|
| **管线（Pipeline）** | `Orchestrator._execute()` | 4 阶段串行，每阶段更新数据库进度 |
| **并行 Gather** | `Orchestrator._run_analyzers()` | 3 个分析器 `asyncio.gather`，各自独立超时 |
| **优雅降级** | 所有分析器 + Reporter | 单个分析器失败不阻断整体；返回带 error 字段的结果 |
| **策略模式** | `RepoAnalyzer` | LLM 推理 vs 启发式回退，透明切换 |
| **工厂 + 适配器** | `LLMService` | 封装 OpenAI 兼容 API，通过 `AsyncOpenAI` 统一接口 |
| **单例（模块级）** | `main.py` 中的 `_db`, `_orchestrator` | FastAPI lifespan 初始化，路由通过 `get_db()` 获取 |
| **模板方法** | `Reporter._build_html()` | 固定 HTML 模板骨架 + 静态方法渲染子区域 |
| **观察者轮询** | 前端 `useAnalysisJob` | 2 秒间隔轮询 `/api/status/{job_id}`，完成后拉取报告 |

### 4.4 并发模型

```
asyncio.create_task(orch.run_pipeline(job_id, url))
    │
    ├── await cloner.clone()                     [串行 — 必须先完成]
    │       subprocess.run 在线程池中运行 (asyncio.to_thread)
    │
    ├── await asyncio.gather(                    [并行 — 三个同时启动]
    │       run_static(),                         各自用 asyncio.wait_for() 包装独立超时
    │       run_repo(),                           return_exceptions=True
    │       run_git(),
    │   )
    │       StaticAnalyzer 内部:
    │         └── asyncio.gather(pylint_json, pylint_score, radon)  [子并行]
    │       GitAnalyzer 内部:
    │         └── asyncio.gather(rev_count, shortlog, timeline, file_freq, check_ci)  [5路并行]
    │
    └── reporter.render()                        [串行 — 需要所有结果]
```

### 4.5 技术栈

| 层 | 技术 | 说明 |
|---|------|------|
| **存储** | SQLite (aiosqlite) | WAL 模式、两表、原生 SQL |
| **后端** | Python 3.11+ / FastAPI / Pydantic v2 / Uvicorn | 异步优先、严格类型 |
| **LLM** | OpenAI Async Client | 兼容 OpenAI/SiliconFlow 等 `/v1/chat/completions` 接口 |
| **代码分析** | pylint + radon | 子进程 `subprocess.run` + `asyncio.to_thread` |
| **版本控制** | Git 子进程 | `git clone`, `git log`, `git shortlog`, `git rev-list` |
| **前端** | React 18 + TypeScript 5 + Vite 6 + Tailwind 4 + shadcn/ui | SPA 单页应用 |
| **状态管理** | Zustand | 极简、无样板代码 |
| **测试** | pytest + pytest-asyncio + Vitest + Testing Library | 后端集成测试 + 前端组件测试 |

### 4.6 部署形态

```
开发模式:
  前端: vite dev (5173) ──proxy──> FastAPI (8770) ──> SQLite (data/repolens.db)
                                              └─> LLM API (外部)

生产模式:
  nginx ──> uvicorn (8770) [--workers N] [挂载 frontend/dist 静态文件]
                ├──> SQLite (WAL 模式)
                └──> LLM Provider (SiliconFlow / OpenAI)
```

---

## 五、核心调用链速查

| 用户操作 | 触发链路 |
|---------|---------|
| 输入 GitHub URL 提交分析 | RepoInput → `useAnalysisJob.submit()` → `api.startAnalysis()` → `POST /api/analyze` → `asyncio.create_task(orch.run_pipeline)` → 返回 `{job_id}` |
| 轮询分析进度 | `useAnalysisJob` 定时器(2s) → `api.fetchJobStatus(job_id)` → `GET /api/status/{job_id}` → `store.updateProgress()` |
| 分析完成获取报告 | `api.fetchReportJson(job_id)` → `GET /api/report/{job_id}` → `store.setReport()` → `ReportViewer` 渲染 |
| 查看 HTML 报告 | `ReportViewer` → iframe `srcDoc={report.html_report}` → 零外部依赖渲染 |
| 浏览历史记录 | `HistoryList` → `api.fetchHistory()` → `GET /api/history` → 表格渲染最近50条 |
| 系统健康检查 | 开发脚本/监控 → `GET /api/health` → `{"status": "ok"}` |

---

## 六、扩展建议

### 短期（MVP 完善）
- 支持更多语言（JavaScript/TypeScript 用 ESLint，Rust 用 Clippy）
- 增加代码安全扫描（bandit / Semgrep）
- 前端增加分析器中间结果实时展示（当前 partial_results 已就绪，前端未消费）

### 中期（多智能体架构演进）
- Agent 化：将三个分析器拆分为独立 Agent（StaticAgent / RepoAgent / GitAgent）
- 引入编排 Agent（Orchestrator Agent）负责分析策略决策（哪些分析器启用、超时动态调整）
- 增加 Reviewer Agent 审查分析结果质量

### 长期（产品化）
- 多仓库对比分析
- 趋势追踪（同一仓库多次快照对比）
- Webhook 触发分析（GitHub App 集成）
- 引入向量库（仓库语义检索）
- Prometheus + Grafana 监控
- 用户认证 + 多租户
