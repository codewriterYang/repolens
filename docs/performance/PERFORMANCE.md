# RepoLens 性能基准

> ⚠️ 以下数据为 **Baseline Measurement Template**，实际数值取决于硬件和网络环境。

## 测试环境

| 项目 | 规格 |
|------|------|
| CPU | 待填写 |
| RAM | 待填写 |
| 网络 | 待填写 |
| Python | 3.13 |
| 操作系统 | Windows 11 |

## 小仓库（full 策略）

**代表**：pallets/flask（~80 .py 文件）

| 阶段 | 预期耗时 | 实际耗时 |
|------|---------|---------|
| Clone | < 10s | — |
| Planner | < 1s | — |
| StaticAnalysis | < 60s | — |
| RepoAnalysis | < 30s | — |
| GitAnalysis | < 10s | — |
| Report | < 1s | — |
| **总计** | **< 120s** | — |

## 中仓库（focused 策略）

**代表**：sqlalchemy/sqlalchemy（~670 .py 文件）

| 阶段 | 预期耗时 | 实际耗时 |
|------|---------|---------|
| Clone | < 20s | — |
| Planner | < 1s | — |
| StaticAnalysis | < 120s | — |
| RepoAnalysis | < 30s | — |
| GitAnalysis | < 20s | — |
| Report | < 2s | — |
| **总计** | **< 200s** | — |

## 大仓库（fast 策略）

**代表**：tiangolo/fastapi（~1120 .py 文件）

| 阶段 | 预期耗时 | 实际耗时 |
|------|---------|---------|
| Clone | < 30s | — |
| Planner | < 2s | — |
| StaticAnalysis | < 60s | — |
| RepoAnalysis | < 30s | — |
| GitAnalysis | < 30s | — |
| Report | < 2s | — |
| **总计** | **< 180s** | — |

> fast 模式下 StaticAnalysis 仅运行 radon cc（~60s），比 full 模式 pylint + radon（~300s）节省约 80% 时间。

## 策略性能对比

| 模式 | StaticAnalysis 耗时 | 节省比例 |
|------|-------------------|---------|
| full | pylint + radon (~300s) | 基准 |
| focused | 排除测试文件 (~200s) | ~33% |
| fast | 仅 radon (~60s) | ~80% |

## 填写说明

1. 准备三个级别仓库的干净克隆
2. 运行分析，从日志提取各阶段耗时
3. 填入对应表格的"实际耗时"列
4. 更新测试环境规格
