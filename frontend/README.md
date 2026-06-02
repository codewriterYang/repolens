# RepoLens 前端

React + TypeScript 单页应用，提供仓库分析的可视化界面。

## 技术栈

- **React 18** · TypeScript
- **Vite** — 开发构建工具
- **Tailwind CSS** — 原子化样式
- **Zustand** — 轻量状态管理
- **Axios** — HTTP 请求
- **shadcn/ui** — 组件基座（Card、Button 等）

## 快速开始

### 本地开发

```bash
cd frontend

# 1. 安装依赖
pnpm install

# 2. 启动开发服务器
pnpm dev
```

前端运行在 `http://localhost:5173`，已配置 Vite 代理到后端 `http://localhost:8770`。

> 请先启动后端服务，参见 [后端 README](../backend/README.md)。

### Docker 部署

前端已容器化，通过 Nginx 反向代理 `/api/` 到后端：

```bash
# 在项目根目录一键启动（含前后端）
docker compose up -d
```

| 组件 | 说明 |
|------|------|
| `Dockerfile` | 多阶段构建：Node 20 Alpine 构建 → Nginx Alpine 托管 |
| `nginx.conf` | Gzip 压缩 + SPA 路由回退 + `/api/` 反向代理到 `backend:8770` |

Docker 访问 `http://localhost:5173`（映射到 Nginx 80 端口）。

```json
frontend/
├── src/
│   ├── App.tsx                  # 应用入口，布局与主逻辑（含历史查看）
│   ├── main.tsx                 # React 挂载点
│   ├── index.css                # 全局样式 + Tailwind 指令
│   │
│   ├── components/
│   │   ├── RepoInput.tsx        # 仓库 URL 输入表单
│   │   ├── ProgressPanel.tsx    # 分析进度展示
│   │   ├── ReportViewer.tsx     # 报告渲染（健康评分 + 统计摘要 + iframe）
│   │   ├── HistoryList.tsx      # 历史分析记录列表
│   │   ├── ui/                  # shadcn/ui 基座组件
│   │   │   ├── button.tsx
│   │   │   ├── card.tsx
│   │   │   └── input.tsx
│   │   └── __tests__/           # 组件测试
│   │       ├── RepoInput.test.tsx
│   │       └── HistoryList.test.tsx
│   │
│   ├── hooks/
│   │   └── useAnalysisJob.ts    # 分析任务管理 Hook（提交 + 轮询）
│   │
│   ├── store/
│   │   └── analysisStore.ts     # Zustand 全局状态
│   │
│   ├── lib/
│   │   ├── api.ts               # Axios HTTP 客户端
│   │   └── utils.ts             # cn() 工具函数（clsx + tailwind-merge）
│   │
│   ├── types/
│   │   └── contracts.ts         # TypeScript 类型定义（与后端 Pydantic 对齐）
│   │
│   └── test/
│       └── setup.ts             # 测试环境配置
│
├── Dockerfile                   # 多阶段构建（Node → Nginx）
├── nginx.conf                   # SPA 路由 + /api/ 反向代理
├── index.html                   # 入口 HTML
├── package.json
├── tsconfig.json
├── vite.config.ts
├── tailwind.config.js
├── postcss.config.js
└── README.md
```

## 组件说明

| 组件 | 功能 |
|------|------|
| `RepoInput` | 输入 GitHub URL 或本地路径，提交分析请求 |
| `ProgressPanel` | 展示分析进度（百分比 + 阶段标签 + Job ID） |
| `ReportViewer` | 展示健康评分摘要卡片、三分析器结果统计、改进建议列表（按优先级分色），并通过 `<iframe>` 沙箱渲染完整 HTML 报告 |
| `HistoryList` | 展示历史分析记录，支持自动轮询刷新、状态颜色标签、点击加载历史报告 |

## 状态管理

使用 Zustand 管理全局分析状态。Store 中定义了简化的 `UiJobStatus`（idle/queued/running/completed/failed），与后端 `contracts.ts` 中的细粒度 `JobStatus`（queued/cloning/analyzing/reporting/...）做区分，`updateProgress` 负责将后端状态映射为前端 UI 状态。

```
analysisStore
├── jobId           # 当前任务 ID
├── status          # UiJobStatus：idle → queued → running → completed/failed
├── progressPct     # 进度百分比
├── stageLabel      # 当前阶段描述
├── partialResults  # 分析器中间结果
├── report          # 完整报告对象（ReportJson）
└── error           # 错误信息
```

## 可用脚本

| 命令 | 说明 |
|------|------|
| `pnpm dev` | 启动开发服务器（含 HMR） |
| `pnpm build` | TypeScript 检查 + 生产构建 |
| `pnpm preview` | 预览生产构建 |
| `pnpm typecheck` | 仅 TypeScript 类型检查 |
| `pnpm lint` | ESLint 代码检查 |
| `pnpm test` | 运行测试 |
| `pnpm test:watch` | 监听模式测试 |

## 代理配置

**开发模式**下 Vite 自动将 `/api` 请求代理到后端：

```ts
// vite.config.ts
proxy: {
  '/api': {
    target: 'http://127.0.0.1:8770',
    changeOrigin: true,
  },
}
```

**生产模式**（Docker）下由 Nginx 反向代理处理（参见 `nginx.conf`）。

## 更多文档

- [项目总览](../README.md)
- [工作流程详解](../WORKFLOW.md)
- [系统架构](../ARCHITECTURE.md)
