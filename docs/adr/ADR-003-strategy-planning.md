# ADR-003: Strategy-Based Planning

- **状态**：已采纳
- **日期**：2026-06-01
- **版本**：v2.6+

## 背景

Phase 7 (DynamicPlanner) 采用 **skip-task 模式**：

```
file_count > 1000 → 跳过 static_analysis
!has_readme     → 跳过 repo_analysis
```

### 设计缺陷

1. **评分不完整**：跳过的 Agent 贡献 0 分，`health_score` 失真
2. **报告信息缺失**：用户看不到被跳过维度的数据
3. **Planner 价值贬低**："智能编排"退化为"关掉 Agent"

## 决策

**从 Skip-Based 升级为 Strategy-Based**：

```
v2.5: skip static_analysis         → StaticAgent 不执行
v2.6: strategy.static = "fast"     → StaticAgent 执行但仅 radon
```

所有 Agent 永远执行。Planner 决定的是**执行深度**而非**执行与否**。

### AnalysisStrategy

| 模式 | 范围 | 置信度 | 行为 |
|------|------|--------|------|
| full | ≤ 500 文件 | 100% | 完整 pylint + radon |
| focused | 501-1000 文件 | 75% | 非测试文件 pylint + 全量 radon |
| fast | > 1000 文件 | 50% | 仅 radon cc |

repo / git 始终 full。

## 方案对比

| 维度 | Skip-Based (v2.5) | Strategy-Based (v2.6) |
|------|-------------------|----------------------|
| Score 完整性 | 缺项，失真 | 完整，置信度标注 |
| 用户感知 | "为什么没有代码质量分数？" | "代码质量用 fast 模式分析，置信度 50%" |
| Planner 定位 | 开关 | 智能调速器 |
| 扩展性 | 新增模式 = 新增 skip 规则 | 新增模式 = 新增 strategy 值 |

## 后果

- **优点**：Score 完整、报告信息齐全、Planner 价值提升
- **缺点**：fast 模式下 pylint 未执行，code_quality 维度降 20 分
- **缓解**：通过前端标签（"Strategy: fast"）+ HTML 置信度标注，用户明确知情

## Phase 8.1 命名优化

`sampled` → `focused`：当前实现是排除测试文件聚焦生产代码，而非随机采样。更名如实描述行为。
