# RepoLens — AI 驱动的仓库分析平台

**在 3 分钟内分析任意 GitHub 仓库。** 获取代码质量洞察、仓库结构理解、Git 活动趋势和结构化 HTML 报告 — 全部通过一个 API 调用完成。

## 项目简介

RepoLens 对克隆的仓库并行运行三个独立分析器：

| 分析器 | 检查内容 | 产出 |
|--------|---------|------|
| **StaticAnalyzer（静态分析）** | Pylint + Radon 圈复杂度 | 高风险文件、复杂函数、lint 热力图 |
| **RepoAnalyzer（仓库分析）** | README + 目录树 + 包元数据（LLM 推理） | 使用模式、核心模块、推断风险 |
| **GitAnalyzer（Git 分析）** | `git log`、`git shortlog`、CI/CD 配置 | 提交历史、贡献者、活动时间线 |

**Reporter（报告生成器）** 将所有结果合并为自包含的 HTML 报告，包含可折叠区域、行内图表和优先排序的改进建议。

## 架构概览

```
POST /api/analyze
       │
       ▼
   Orchestrator（异步编排）
       │
       ├──▶ git clone（30秒超时）
       │
       ├──▶ StaticAnalyzer ──┐
       ├──▶ RepoAnalyzer   ──┼── 并行（asyncio.gather）
       └──▶ GitAnalyzer    ──┘
              │
              ▼
          Reporter（报告生成）
              │
              ▼
       GET /api/report/{job_id}
```

三个分析器互相独立 — 任何一个失败都不会阻碍其他分析器。Reporter 优雅处理缺失结果，部分结果在流水线运行期间可通过 `GET /api/status/{job_id}` 获取。

## 快速开始

### 环境要求

- Python 3.11+
- Git 已安装并位于 PATH
- 一个 OpenAI 兼容的 API Key（或其他提供 `/v1/chat/completions` 的厂商）

### 1. 配置

```bash
cd repolens

# 从模板创建 .env 文件
cp .env.example .env
# 编辑 .env 填入你的 LLM_API_KEY
```

### 2. 安装依赖

```bash
cd backend
pip install -r requirements.txt
```

开发工具可选安装（lint/测试）：

```bash
pip install -r requirements.txt pytest pytest-asyncio ruff
```

### 3. 启动后端

```bash
python -m uvicorn repolens.main:app --host 0.0.0.0 --port 8770 --reload
```

### 4. 启动前端（可选）

```bash
cd frontend
pnpm install
pnpm dev
# 访问 http://localhost:5173，已配置 API 代理到后端
```

### 5. 提交分析请求

```bash
# 分析 GitHub 仓库
curl -X POST http://localhost:8770/api/analyze \
  -H "Content-Type: application/json" \
  -d '{"repo_url": "https://github.com/psf/requests"}'

# 返回：{"job_id": "abc123...", "status": "queued"}
```

### 6. 轮询进度

```bash
curl http://localhost:8770/api/status/abc123
# 返回：{"status": "analyzing", "progress_pct": 45, "stage_label": "正在分析代码...", ...}
```

### 7. 获取报告

```bash
# JSON 格式报告
curl http://localhost:8770/api/report/abc123

# 自包含 HTML 报告
curl http://localhost:8770/api/report/abc123/html
```

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/analyze` | 提交仓库分析请求 |
| `GET` | `/api/status/{job_id}` | 轮询进度与部分结果 |
| `GET` | `/api/report/{job_id}` | 获取完成报告（JSON） |
| `GET` | `/api/report/{job_id}/html` | 获取完成报告（HTML） |
| `GET` | `/api/history` | 列出最近的分析任务 |
| `GET` | `/api/health` | 健康检查 |

## 报告内容

HTML 报告包含以下内容：

- **健康评分** — 0-100 综合评分，含 4 个维度细分（代码质量、仓库清晰度、社区活跃、工程实践）
- **改进建议** — 跨三个分析器的优先排序建议，包含交叉分析洞察（如"高频变更与高风险文件重叠"）
- **代码质量** — 可折叠文件风险表（按 HIGH/MEDIUM/LOW 排序）、高复杂度函数列表
- **仓库洞察** — 使用模式、核心模块、LLM 推断风险、README 质量评分
- **Git 活动** — 提交统计、行内 SVG 时间线图表（12 周趋势）、贡献者表格、活跃文件

## 项目结构

```
repolens/
├── backend/
│   ├── repolens/              # Python 包
│   │   ├── main.py            # FastAPI 应用与路由
│   │   ├── config.py          # 环境变量配置
│   │   ├── schemas.py         # Pydantic 数据模型（API 契约）
│   │   ├── db.py              # SQLite 持久化层
│   │   ├── orchestrator.py    # 流水线编排器
│   │   ├── reporter.py        # HTML 报告生成器
│   │   ├── cloner.py          # Git 克隆/清理工具
│   │   ├── llm_service.py     # OpenAI 兼容 LLM 客户端
│   │   └── analyzers/
│   │       ├── static_analyzer.py  # Pylint + Radon
│   │       ├── repo_analyzer.py    # README + 目录树 + LLM
│   │       └── git_analyzer.py     # Git 活动 + CI/CD
│   ├── requirements.txt
│   └── pyproject.toml
├── frontend/                  # React + TypeScript 界面
│   ├── src/
│   │   ├── components/        # UI 组件
│   │   ├── hooks/             # 自定义 React Hook
│   │   ├── store/             # Zustand 状态管理
│   │   ├── types/             # TypeScript 类型定义
│   │   └── lib/               # API 客户端、工具函数
│   ├── package.json
│   └── vite.config.ts
├── tests/                     # 集成测试
├── scripts/                   # 开发辅助脚本
├── samples/                   # 测试样例
├── ARCHITECTURE.md            # 详细架构文档
└── README.md
```

## 设计原则

- **清晰优先于复杂** — 单文件分析器、扁平包结构、无依赖注入框架
- **优雅降级** — 每个分析器的失败都不会导致整体崩溃；部分结果始终可用
- **自包含输出** — HTML 报告零外部依赖（无 CDN、无 JS 框架）
- **跨平台兼容** — 子进程通过 `subprocess.run` + `asyncio.to_thread` 执行，兼容 Windows/Linux/macOS
- **可配置超时** — 分析器级和流水线级超时防止失控任务

## 配置说明

所有设置通过环境变量配置（参见 `.env.example`）：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `LLM_BASE_URL` | `https://api.openai.com/v1` | OpenAI 兼容 API 地址 |
| `LLM_API_KEY` | （必填） | LLM 厂商的 API Key |
| `LLM_MODEL` | `gpt-4o-mini` | 模型名称 |
| `HOST` | `0.0.0.0` | 服务器绑定地址 |
| `PORT` | `8770` | 服务器端口 |
| `DB_PATH` | `data/repolens.db` | SQLite 数据库路径 |
| `TMP_DIR` | （自动检测系统临时目录） | 仓库克隆临时目录。可选，留空自动适配系统。Linux/Mac → `/tmp/repolens`，Windows → `%TEMP%\repolens` |

## 测试

```bash
# 从项目根目录运行集成测试
PYTHONPATH=backend python -m pytest tests/ -v

# 或直接运行集成测试脚本
PYTHONPATH=backend python tests/test_integration.py
```

## 许可证

MIT — 详见 [LICENSE](LICENSE)。
