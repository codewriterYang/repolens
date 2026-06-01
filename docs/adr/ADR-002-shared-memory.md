# ADR-002: SharedMemory Layer

- **状态**：已采纳
- **日期**：2026-06-01
- **版本**：v2.2+

## 背景

Phase 5 引入 PlannerAgent 后，需要一种方式将分析计划传递给三个分析 Agent。直接通过函数传参需要 Orchestrator 感知所有 Agent 的接口变化，破坏解耦。

## 决策

采用 **SharedMemory**（线程安全的 KV 存储）：

```python
memory = SharedMemory()
memory.set("analysis_plan", plan)   # Planner 写入
memory.set("static_result", result)  # Static 写入
plan = memory.get("analysis_plan")   # Analyzer 读取
```

使用 `threading.RLock` 保证并发安全（asyncio.gather 并行执行时多 Agent 同时读写）。

## 替代方案

| 方案 | 优点 | 缺点 |
|------|------|------|
| 函数参数 | 显式依赖 | 每次新增 Agent 需改调用方，破坏解耦 |
| 全局变量 | 简单 | 不可测试，并发不安全 |
| Redis/消息队列 | 可跨进程 | 过度设计，增加运维成本 |
| SharedMemory | 解耦 + 安全 + 零依赖 | 进程内限制 |

## 后果

- **优点**：Agent 之间零直接引用，Memory 成为唯一交互点
- **缺点**：无类型安全（`memory.get()` 返回 `Any`）
- **缓解**：全局使用 Pydantic 模型写入，约定 Key 命名规范

## Key 命名规范

| 前缀 | 用途 | 示例 |
|------|------|------|
| `*_result` | Agent 产出 | `static_result`, `repo_result` |
| `analysis_plan` | Planner 计划 | `analysis_plan` |
| `report_result` | ReportAgent 输出 | `report_result` |
