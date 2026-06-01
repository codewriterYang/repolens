# RepoLens 技术选型说明

本文档记录 RepoLens 每个关键技术栈的选择理由——"为什么选这个、不选那个"。

---

## 后端

### Python + FastAPI（非 Flask/Django）

| 考量点 | 理由 |
|--------|------|
| 原生异步 | `asyncio.create_task` 直接启动后台流水线任务，Django 需要额外引入 Celery |
| 类型安全 | Pydantic v2 强校验请求/响应，前后端共用一套数据契约 |
| 自动文档 | Swagger UI + OpenAPI JSON 零配置生成，`/docs` 直接可用 |
| 轻量 | 项目 6 个 API 路由，不需要 Django Admin / ORM / 模板引擎 |

本项目坚持"无依赖注入框架"原则——6 个路由、2 个共享依赖（数据库连接、编排器实例），用模块级单例 + `get_db()/get_orchestrator()` 辅助函数就够了，不需要 FastAPI `Depends` 体系的 provider 树。

### Pydantic v2（非 dataclass / marshmallow）

`BaseModel.model_dump_json()` 一行完成序列化，写入 SQLite 零映射成本。`model_validate()` 反序列化时带校验，数据流转全程类型安全。共定义 20 个模型覆盖 API 请求、分析器结果、报告输出全链路。

### 无 ORM（aiosqlite + 原生 SQL）

项目仅 2 张表、~10 个查询函数。SQLAlchemy 的映射样板代码量会超过原生 SQL 本身，没必要。Pydantic 的反序列化校验替代了 ORM 的类型映射角色。SQLite WAL 模式实现读写并发——前端轮询 `/api/status` 时不会阻塞后台写入 `partial_results`。

### Git 子进程（非 GitPython）

5 个 git 命令（`rev-list`、`shortlog`、`log` 等）通过 `subprocess.run` + `asyncio.to_thread` 在线程池中执行。不依赖 GitPython 的编译扩展，Windows 零安装问题。输出直接用正则 + `collections.Counter` 解析，完全可控。

### pylint + radon（子进程调用）

- **pylint**：Python 社区事实标准的代码质量工具，评分 0.0-10.0
- **radon**：圈复杂度分析，`--min=B` 过滤出 CC ≥ 10 的 Medium+ 函数

两者通过 `python -m pylint` / `python -m radon` 调用（非直接执行 `pylint` 命令），确保使用与 uvicorn 相同的 Python 环境，避免 Windows PATH 问题。传目录路径 + `--recursive=y` 而非逐一传 `.py` 文件，规避 Windows 命令行 32k 字符限制。

### OpenAI 兼容 API（非 LangChain 等框架）

本项目 LLM 调用极简单——仅需 `chat(system_prompt, user_prompt)` 返回文本。`openai` SDK 的 `AsyncOpenAI` 提供异步客户端 + 指数退避重试 + JSON 模式约束输出。不引入 LangChain 的抽象链、不引入本地模型推理框架。

缓存设计为 `sha256(repo_url|readme_hash|model)` 三维键，同一仓库重复分析时命中缓存零 LLM 消耗。

支持任何 `/v1/chat/completions` 格式的接口（OpenAI、SiliconFlow、本地 Ollama 等）。

### SQLite（非 PostgreSQL / MySQL）

单文件数据库，零运维。WAL 模式实现读写并发，匹配项目"前端高频轮询读 + 后台低频写"的负载模式。如果未来需要分布式，`db.py` 中全是标准 SQL 无 ORM 依赖，替换成本低。

---

## 前端

### React 18 + TypeScript + Vite（非 Vue / CRA / Next.js）

React 的 TypeScript 生态类型定义最完善（`@types/react`、`@types/react-dom` 官方维护）。Vite 利用浏览器原生 ESM 实现秒级 HMR，Webpack 的编译速度在开发体验上没法比。项目是纯 SPA 单页应用，不需要 Next.js 的 SSR / 文件路由——Vite 的极简配置刚好匹配。

### Zustand（非 Redux）

本项目仅 1 个全局 store（分析任务状态），Zustand ~30 行代码搞定。Redux 需要 action types + reducer + selector + middleware 四件套，样板代码量远超 store 本身。Zustand 的 `store.setReport(report)` 直调方式也比 `dispatch({type, payload})` 更直观。

### Tailwind CSS + shadcn/ui（非 Ant Design / MUI）

shadcn/ui 不是 npm 包，是"复制源码到项目"的模式——3 个组件（Button / Card / Input）直接可控、可按需增减。Tailwind 原子化 CSS 消除样式命名冲突和全局样式污染，Vite + PostCSS 编译时生成，零运行时开销。Ant Design 整套组件库太重，不适合这个体量的项目。

### Axios（非原生 fetch）

原生 fetch 缺少请求/响应拦截器、请求超时设置、baseURL 自动前缀。Axios 加上泛型响应类型，与 `contracts.ts` 的类型定义无缝联动。

### iframe 渲染 HTML 报告（非 dangerouslySetInnerHTML）

后端生成的 HTML 报告包含行内 JS（可折叠区域交互）。直接 `dangerouslySetInnerHTML` 存在 XSS 风险——报告内容可能篡改主应用 DOM。`<iframe srcDoc={html} sandbox="allow-scripts">` 创建独立沙箱：JS 在 iframe 内执行、样式不泄漏、无法访问父页面。

---

## 工程实践

### 模块化单仓库（非 pnpm workspaces Monorepo）

`backend/` 和 `frontend/` 各自独立管理依赖（`requirements.txt` / `package.json`），不引入 monorepo 工具链（npm workspaces / pnpm -w / turborepo）。开发模式通过 Vite proxy 联通前后端（`/api` → `localhost:8770`），生产模式 nginx 反代 + 静态文件托管。对 2 个子项目的规模，独立管理比统一 workspace 更清晰。

### 跨平台 subprocess 策略

| 层级 | 策略 |
|------|------|
| Python async | `asyncio.to_thread(subprocess.run)`，兼容 Windows `ProactorEventLoop` |
| 路径处理 | `pathlib.Path` 统一 Windows/Linux，`tempfile.gettempdir()` 自动适配临时目录 |
| 工具调用 | `python -m pylint/radon` 而非直接调用可执行文件 |
| 命令行长度 | 传目录路径而非逐一传文件路径，规避 Windows 32k 字符限制 |

### 异常处理分层

```
分析器子进程 try/except → 返回带 error 字段的结果
分析器级 asyncio.wait_for() → 捕获 TimeoutError → 返回错误结果
编排器 asyncio.gather(return_exceptions=True) → 异常解包为 None
流水线总 asyncio.wait_for(600s) → JobStatus.TIMEOUT
Reporter 处理 None/错误 → 仍产出合法 HTML
RepoAnalyzer LLM 失败 → 纯启发式回退
```
每一层都有独立降级路径，单点故障不崩溃。

---

## 选型总结

```
后端: FastAPI + Pydantic v2 + aiosqlite + subprocess(git/pylint/radon) + OpenAI兼容API
前端: React 18 + TypeScript + Vite + Zustand + Tailwind + shadcn/ui + Axios
存储: SQLite (WAL)
架构: Agent 抽象层 (BaseAgent + AgentRegistry) + Context 层 (RepositoryContext + ContextManager) + 三层优雅降级
工程: 模块化单仓库 + 跨平台 subprocess
测试: pytest 集成测试 (12 用例) + Vitest 组件测试
```

> 核心原则：**"不引入比项目更重的依赖"**。2 张表不需要 ORM，1 个 store 不需要 Redux，1 个 LLM 方法不需要 LangChain。
> v2.0 引入 Agent 抽象层——通过 BaseAgent 接口 + AgentRegistry 实现分析器的统一调度与生命周期管理，为后续多 Agent 协作奠定基础，而不引入框架级依赖。
