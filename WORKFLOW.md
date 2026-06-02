# RepoLens 工作流程详解

以下从用户输入 GitHub URL 到最终输出 HTML 报告，逐步说明整个流水线的工作方式。

## 总体流程

```
GitHub URL（用户输入）
    │
    ▼
┌─────────────────────────┐
│ 1. 仓库克隆             │   git clone --single-branch → 系统临时目录
│    RepoCloner           │   （完整历史，非浅克隆）
└─────────────────────────┘
    │
    ▼
┌───────────────────────────────────────────────────┐
│ 2. 策略规划（Phase 5）                              │
│    PlannerAgent → DynamicPlanner                   │
│      ├─ RepositoryProfiler（统计 .py 文件数）        │
│      └─ PlanningRules（决定 full/focused/fast 策略） │
└───────────────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────────────────────────┐
│ 3. 并行分析（asyncio.gather）                                     │
│                                                                   │
│  ┌───────────────────┐ ┌───────────────────┐ ┌───────────────────┐
│  │ StaticAgent       │ │ RepoAgent         │ │ GitAgent          │
│  │（代码质量）       │ │（仓库意图）       │ │（Git活动）        │
│  │                   │ │                   │ │                   │
│  │ 评估对象：        │ │ 评估对象：        │ │ 评估对象：        │
│  │ · Python源文件    │ │ · README内容      │ │ · Git提交历史     │
│  │ · 函数圈复杂度    │ │ · 目录结构        │ │ · 贡献者活动      │
│  │ · Lint问题分布    │ │ · 项目元数据      │ │ · CI/CD配置       │
│  │                   │ │                   │ │                   │
│  │ 策略影响：        │ │                   │ │                   │
│  │ · full → 全量扫描  │ │                   │ │                   │
│  │ · focused → 排除    │ │                   │ │                   │
│  │   测试文件         │ │                   │ │                   │
│  │ · fast → 仅 radon  │ │                   │ │                   │
│  └───────────────────┘ └───────────────────┘ └───────────────────┘
│           │                     │                     │
│           ▼                     ▼                     ▼
│    StaticResult            RepoResult            GitResult
└──────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────┐
│ 3. 报告生成             │   健康评分 + 改进建议 + HTML报告
│    Reporter             │
└─────────────────────────┘
    │
    ▼
┌─────────────────────────┐
│ 4. 前端渲染             │   iframe 沙箱渲染 HTML
│    ReportViewer         │
└─────────────────────────┘
```

## 阶段一：仓库克隆 — RepoCloner

- **工具**：`git clone --single-branch <URL> <临时目录>`（通过 `subprocess.run` 在线程中执行）
- **特点**：不使用 `--depth` 浅克隆，保证 GitAnalyzer 能读到完整提交历史
- **存储位置**：系统临时目录下 `repolens/repo_{job_id前12位}`
- **超时**：300 秒（`clone_timeout_seconds`，可在 `.env` 中自定义）
- **清理**：流水线结束后自动删除（`finally` 块中调用 `cleanup()`）
- **支持本地路径**：如果输入不是 HTTP(S) URL，则作为本地目录路径直接使用（不做克隆和清理）

## 阶段二：策略规划 — PlannerAgent

克隆完成后，PlannerAgent 先分析仓库特征，再决定每个 Agent 的执行策略：

1. **RepositoryProfiler** — 扫描仓库，统计 `.py` 文件数、检测 README/CI/Docker 等特征
2. **PlanningRules** — 基于文件数选择策略：`full` / `focused` / `fast`
3. 策略结果写入 **SharedMemory**，供后续 Agent 读取

| 文件数 | 策略 | StaticAgent 行为 |
|--------|------|------------------|
| ≤ 500 | `full` | 完整 pylint + radon |
| 501–1000 | `focused` | 排除测试文件后跑 pylint + 全量 radon |
| > 1000 | `fast` | 跳过 pylint，仅 radon cc |

## 阶段三：三大 Agent 并行执行

三个 Agent（各封装一个 Analyzer）通过 Orchestrator → AgentRegistry → `asyncio.gather` 同时启动，各自有独立超时，单个失败不影响整体。

### 3.1 StaticAnalyzer — 代码质量分析

**评估对象**：仓库中所有 `.py` 源文件

**使用工具及作用**：

| 工具（子进程） | 命令 | 检测内容 | 产出 |
|--------------|------|---------|------|
| pylint（JSON模式） | `pylint --recursive=y --output-format=json <repo_path>` | 逐行lint问题（error/warning/convention等） | 按文件分组的lint消息 |
| pylint（文本模式） | `pylint --recursive=y --score=y --output-format=text <repo_path>` | 文件级评分（0.0-10.0） | 每个文件的pylint评分 |
| radon | `radon cc --json --min=B .` | 函数圈复杂度（Cyclomatic Complexity） | 每个函数的CC值和等级（A-F） |

**执行方式**：三个子进程并行 → 结果在内存中合并

**风险分级规则**：

| 风险等级 | 判断依据 |
|---------|---------|
| 🔴 HIGH | 圈复杂度 ≥ 20（D级及以上）或 存在 error/fatal 级别lint |
| 🟡 MEDIUM | 圈复杂度 ≥ 10（C级）或 存在 warning 级别lint |
| 🟢 LOW | 其余情况 |

**最终产出（`StaticResult`）**：
- `total_files_scanned` — 扫描的 Python 文件总数
- `pylint_score` — 平均 pylint 评分
- `high_complexity_functions` — 高/中风险函数详情（文件、行号、复杂度值、风险等级）
- `file_heatmap` — 每文件逐行风险热力图
- `file_risk_summary` — 每文件风险摘要（lint问题数、最大复杂度、综合风险等级），按 HIGH → MEDIUM → LOW 排序

### 3.2 RepoAnalyzer — 仓库意图分析

**评估对象**：README 内容、目录结构、项目元数据（通过 LLM 理解项目是什么、怎么组织的）

**分析流程（两阶段）**：

**阶段 A：并行加载输入（无 LLM，纯文件 I/O）**：
1. 读取 README.md 前 8000 字符
2. 构建 3 层深度的目录树（仅包含 .py/.md/.yml 等关键文件，排除 node_modules/.git/__pycache__ 等）
3. 提取项目元数据：是否有 pyproject.toml/setup.py、是否有 tests/ 目录、是否有 docs/ 目录、依赖列表

**阶段 B：LLM 推理**（当 LLM 可用时）：
- 把 README + 目录树 + 元数据发给 LLM
- LLM 以结构化 JSON 返回四个维度的分析：
  - `usage_patterns` — 使用模式（如"Web 应用"、"命令行工具"、"代码库/SDK"）
  - `core_modules` — 核心模块目录名（2-5 个）
  - `summary` — 一句话项目摘要（≤ 200 字符）
  - `inferred_risks` — 从结构推断的风险（如"无测试目录 → 维护风险"）
- 使用低温度（0.3）保证输出一致性
- 结果按 `sha256(repo_url + README哈希 + 目录树哈希)` 缓存到 SQLite，避免重复分析同一仓库时重复调用 LLM

**阶段 C：启发式回退**（LLM 不可用或超时时自动启用）：
- README 第一行作为摘要
- 顶级目录作为核心模块
- 关键词匹配识别使用模式（含 "api" → "提供 API 服务"，含 "cli" → "命令行工具" 等）
- 元数据信号推断风险：

| 条件 | 风险 |
|------|------|
| 无 tests/ 目录 | 🔴 维护风险：缺少自动化测试覆盖 |
| 无 pyproject.toml/setup.py | 🟡 依赖风险：依赖管理可能不规范 |
| README < 500字符 且无 docs/ | 🟡 文档风险：文档可能不完善 |
| 有打包配置但未声明依赖 | 🟢 架构风险：可能为简单脚本 |

**README 质量评分**（无 LLM，纯启发式，0-100）：

| 维度 | 满分 | 评分依据 |
|------|------|---------|
| 长度 | 25 分 | 越长越好，递减效应：≥3000→25, ≥1500→20, ≥500→15 |
| 结构 | 25 分 | 有标题 +10, 有代码块 +8, 有列表 +4, 有表格 +3 |
| 徽章 | 15 分 | shields.io 徽章：≥5→15, ≥2→10, ≥1→5 |
| 安装说明 | 15 分 | 含 pip install/poetry install/git clone 等关键词 → +15 |
| 使用示例 | 20 分 | 含 usage/example/quickstart 等 + 代码块 → +20, 仅关键词 → +10 |

**最终产出（`RepoResult`）**：
- `usage_patterns` — 2-4 个使用模式
- `core_modules` — 2-5 个核心模块
- `summary` — 项目一句话描述
- `readme_quality_score` — README 质量评分（0-100）
- `inferred_risks` — 2-4 个推断风险（含类别、严重度、描述）

### 3.3 GitAnalyzer — Git 活动分析

**评估对象**：Git 仓库的完整提交历史

**使用工具及作用**：

| Git 命令（子进程） | 作用 | 产出 |
|------------------|------|------|
| `git rev-list --count --no-merges HEAD` | 统计非合并提交总数 | `total_commits` |
| `git shortlog -sne HEAD` | 按提交数统计贡献者 | `top_contributors`（Top 10） |
| `git log --format=%H\|%ae\|%ci --no-merges` | 获取完整提交时间线 | 每周提交趋势、活跃天数 |
| `git log --name-only --format= --no-merges --no-renames` | 统计文件变更频率 | `active_files`（Top 50） |
| 文件系统检查 `.github/workflows/` | 检测 CI/CD 配置 | `ci_cd_config`（bool） |

**执行方式**：5 个子进程并行运行，各自有 60 秒独立超时

**浅克隆保护**：
- 分析前检查 `git rev-parse --is-shallow-repository`
- 若是浅克隆，尝试 `git fetch --unshallow` 补全历史（2 分钟超时）

**时间线计算**（纯本地解析，无 git 子进程）：
- 按 ISO 周聚合提交数 → `activity_over_time`（每周提交趋势）
- 统计有提交的唯一天数 → `active_days`
- 周均提交 = 总提交数 / 时间跨度（周） → `commits_per_week`

**最终产出（`GitResult`）**：
- `total_commits` — 总提交数
- `commits_per_week` — 周均提交数
- `unique_contributors` — 唯一贡献者数
- `active_days` — 有提交活动的天数
- `top_contributors` — Top 10 贡献者（含提交数、邮箱）
- `active_files` — Top 50 高频变更文件（含变更次数）
- `activity_over_time` — 按周分组的提交趋势
- `ci_cd_config` — 是否有 CI/CD 配置

## 阶段四：报告生成 — Reporter

将三个分析器的结果汇总，生成统一的结构化报告。

**健康评分机制（0-100）**：

| 维度 | 满分 | 评分依据 | 来源分析器 |
|------|------|---------|-----------|
| 代码质量 | 40 | 复杂度密度越低分越高（20分）+ pylint评分越高分越高（20分） | StaticAnalyzer |
| 仓库清晰度 | 30 | 有使用模式 +15 + README质量按比例折算（0-15） | RepoAnalyzer |
| 社区活跃 | 20 | 周均提交 ≥7 → +10 / 贡献者 ≥5 → +10 | GitAnalyzer |
| 工程实践 | 10 | 有 CI/CD → +10 | GitAnalyzer |

**改进建议（三级优先级）**：
- 🔴 **优先级 1（严重）**：高风险代码文件、安全风险、高频变更+高风险文件重叠（交叉分析"热点"）
- 🟡 **优先级 2（重要）**：缺少 CI/CD、缺少测试、贡献者少、未识别核心模块
- 🔵 **优先级 3（建议）**：低活跃度、中复杂度函数过多、文档不完善

每条建议包含：优先级、类别（代码质量/项目结构/工程实践/社区健康）、标题和详细说明。

**HTML 报告**：自包含的行内 HTML，含可折叠表格、SVG 每周活动趋势图、评分维度柱状图，零外部 CSS/JS 依赖。

## 评估对象层级总结

```
┌──────────────────────────────────────────────────┐
│  层级              │  评估对象        │  分析器   │
├──────────────────────────────────────────────────┤
│  项目级（What）     │  项目意图/结构   │  Repo     │
│                    │  使用模式/风险   │  Analyzer │
├──────────────────────────────────────────────────┤
│  仓库级（How active）│ 开发活跃度      │  Git      │
│                    │  贡献者结构      │  Analyzer │
│                    │  CI/CD工程实践   │           │
├──────────────────────────────────────────────────┤
│  文件级（File risk）│ 每文件的风险     │  Static   │
│                    │  lint问题数      │  Analyzer │
│                    │  综合风险等级    │           │
├──────────────────────────────────────────────────┤
│  函数级（Function） │ 圈复杂度（CC）   │  Static   │
│                    │  函数风险等级    │  Analyzer │
└──────────────────────────────────────────────────┘
```
