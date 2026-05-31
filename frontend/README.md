# RepoLens 前端

React + TypeScript 单页应用，提供仓库分析的可视化界面。

## 技术栈

- **React 18** · TypeScript
- **Vite** — 开发构建工具
- **Tailwind CSS** — 原子化样式
- **Zustand** — 轻量状态管理
- **Axios** — HTTP 请求
- **Lucide React** — 图标库
- **shadcn/ui** — 组件基座（Card 等）

## 快速开始

```bash
cd frontend

# 1. 安装依赖
pnpm install

# 2. 启动开发服务器
pnpm dev
```

前端运行在 `http://localhost:5173`，已配置 API 代理到后端 `http://localhost:8770`。

> 请先启动后端服务，参见 [后端 README](../backend/README.md)。

## 项目结构

```
frontend/src/
├── App.tsx                  # 应用入口，布局与主逻辑
├── main.tsx                 # React 挂载点
├── index.css                # 全局样式 + Tailwind 指令
│
├── components/
│   ├── RepoInput.tsx        # 仓库 URL 输入表单
│   ├── ProgressPanel.tsx    # 分析进度展示
│   ├── ReportViewer.tsx     # HTML 报告渲染（iframe 沙箱）
│   ├── HistoryList.tsx      # 历史分析记录列表
│   └── ui/                  # shadcn/ui 基座组件
│       └── card.tsx
│
├── hooks/
│   └── useAnalysisJob.ts    # 分析任务管理 Hook（提交 + 轮询）
│
├── store/
│   └── analysisStore.ts     # Zustand 全局状态
│
├── lib/
│   └── api.ts               # Axios HTTP 客户端
│
├── types/
│   └── contracts.ts         # TypeScript 类型定义
│
└── test/
    └── setup.ts             # 测试环境配置
```

## 组件说明

| 组件 | 功能 |
|------|------|
| `RepoInput` | 输入 GitHub URL 或本地路径，提交分析请求 |
| `ProgressPanel` | 展示分析进度（百分比 + 阶段标签） |
| `ReportViewer` | 通过 `<iframe>` 沙箱渲染自包含 HTML 报告 |
| `HistoryList` | 展示历史分析记录，点击可加载历史报告 |

## 状态管理

使用 Zustand 管理全局分析状态：

```
analysisStore
├── jobId           # 当前任务 ID
├── status          # 任务状态：queued → running → completed
├── progressPct     # 进度百分比
├── stageLabel      # 当前阶段描述
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

开发模式下 Vite 自动将 `/api` 请求代理到后端：

```ts
// vite.config.ts
proxy: {
  '/api': {
    target: 'http://127.0.0.1:8770',
    changeOrigin: true,
  },
}
```

无需额外配置，前后端同源访问。

## 更多文档

- [项目总览](../README.md)
- [工作流程详解](../WORKFLOW.md)
- [系统架构](../ARCHITECTURE.md)
