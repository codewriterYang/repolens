# ADR-001: Multi-Agent Architecture

- **状态**：已采纳
- **日期**：2026-06-01
- **版本**：v2.0+

## 背景

MVP 阶段，分析流程是硬编码的串行调用：

```python
static_result = StaticAnalyzer().run(repo_path)
repo_result = RepoAnalyzer().run(repo_path)
git_result = GitAnalyzer().run(repo_path)
report = Reporter().render(...)
```

后续引入 Context/Memory/Planner/Report 后，需要统一调度、状态共享、策略编排能力。

## 决策

采用 **Multi-Agent Architecture**：

```
所有分析器通过 BaseAgent 接口统一包装
  → AgentRegistry 注册和查找
  → RepositoryContext 统一传参
  → SharedMemory 共享中间结果
  → PlannerAgent 编排分析计划
```

## 方案对比

| 维度 | 传统流程 | Multi-Agent |
|------|---------|------------|
| 扩展性 | 每次新增分析器需改 Orchestrator | 注册即用，零耦合 |
| 状态共享 | 无，通过返回值传递 | SharedMemory 并发安全 |
| 策略编排 | 硬编码 | Planner 动态决定 |
| 测试性 | 端到端耦合 | Agent 独立测试 |
| 复杂度 | 低 | 中 |

## 后果

- **优点**：Agent 可热插拔，策略可动态调整，测试覆盖更完善
- **缺点**：架构抽象增加约 300 行代码，新成员上手需理解 BaseAgent/Memory/Context 三层
- **缓解**：通过 `docs/architecture/` 文档和 55 个单元测试降低认知负担
