# RepoLens 后端

FastAPI 异步服务，提供仓库分析流水线的 REST API。

## 技术栈

- **Python 3.11+** · FastAPI · uvicorn
- **aiosqlite** — 任务状态与报告持久化
- **pylint + radon** — 静态代码分析
- **Git subprocess** — 提交历史与贡献者统计
- **OpenAI 兼容 API** — LLM 仓库意图分析

## 快速开始

```bash
cd backend

# 1. 安装依赖
pip install -e ".[dev]"

# 2. 配置环境变量（项目根目录）
cp ../.env.example ../.env
# 编辑 ../.env，填入 LLM_API_KEY

# 3. 启动开发服务器
python -m uvicorn repolens.main:app --host 0.0.0.0 --port 8770 --reload
```

API 服务运行在 `http://localhost:8770`，交互式文档在 `http://localhost:8770/docs`。

## 项目结构

```
backend/
├── repolens/
│   ├── main.py              # FastAPI 应用入口，路由注册
│   ├── config.py            # 环境变量配置（.env → Config 对象）
│   ├── schemas.py           # Pydantic 数据模型（API 契约）
│   ├── db.py                # SQLite 持久化（任务/报告/LLM缓存）
│   ├── orchestrator.py      # 流水线编排器（clone → analyze → report）
│   ├── reporter.py          # HTML 报告生成器（评分 + 建议 + 可视化）
│   ├── cloner.py            # Git 仓库克隆与清理
│   ├── llm_service.py       # OpenAI 兼容 LLM 客户端（含缓存）
│   ├── agents/               # Agent 层（v2.0，分析器的统一包装）
│   │   ├── base.py           # BaseAgent 抽象基类
│   │   ├── static_agent.py   # 封装 StaticAnalyzer
│   │   ├── repo_agent.py     # 封装 RepoAnalyzer
│   │   ├── git_agent.py      # 封装 GitAnalyzer
│   │   └── registry.py       # AgentRegistry 注册与调度
│   ├── context/              # Context 层（v2.1，分析上下文管理）
│   │   ├── base.py           # RepositoryContext 不可变上下文
│   │   ├── repository_context.py # 上下文工厂函数
│   │   └── context_manager.py    # ContextManager 生命周期
│   ├── memory/               # Memory 层（v2.2，Agent 共享记忆）
│   │   ├── base.py           # SharedMemory 线程安全 KV 存储
│   │   ├── shared_memory.py   # 辅助函数
│   │   └── memory_manager.py  # MemoryManager 生命周期
│   └── analyzers/
│       ├── static_analyzer.py   # pylint + radon 静态分析
│       ├── repo_analyzer.py     # README + 目录树 + LLM 仓库分析
│       └── git_analyzer.py      # Git 活动分析（提交/贡献者/CI）
├── pyproject.toml
└── README.md
```

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/analyze` | 提交分析请求，返回 `job_id` |
| `GET` | `/api/status/{job_id}` | 轮询进度与部分结果 |
| `GET` | `/api/report/{job_id}` | 获取完成报告（JSON） |
| `GET` | `/api/report/{job_id}/html` | 获取完成报告（HTML） |
| `GET` | `/api/history` | 列出最近分析任务 |
| `GET` | `/api/health` | 健康检查 |

## 配置

所有配置通过项目根目录的 `.env` 文件设置：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `LLM_API_KEY` | （必填） | LLM 厂商 API Key |
| `LLM_BASE_URL` | `https://api.openai.com/v1` | API 地址 |
| `LLM_MODEL` | `gpt-4o-mini` | 模型名称 |
| `HOST` | `0.0.0.0` | 监听地址 |
| `PORT` | `8770` | 监听端口 |
| `DB_PATH` | `data/repolens.db` | SQLite 数据库路径 |
| `TMP_DIR` | （系统临时目录） | 仓库克隆存储目录 |
| `PIPELINE_TIMEOUT_SECONDS` | `600` | 流水线超时（秒） |
| `CLONE_TIMEOUT_SECONDS` | `300` | 克隆超时（秒） |

## 测试

```bash
# 从项目根目录运行
PYTHONPATH=backend python -m pytest tests/ -v
```

## 更多文档

- [项目总览](../README.md)
- [工作流程详解](../WORKFLOW.md)
- [系统架构](../ARCHITECTURE.md)

