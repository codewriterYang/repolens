# RepoLens 测试

## 测试文件

| 文件 | 类型 | 说明 |
|------|------|------|
| `conftest.py` | pytest 配置 | 添加 `backend/` 到 Python 路径 |
| `test_integration.py` | 集成测试（12 用例） | Schema 序列化、Reporter HTML、数据库操作、错误场景、API 路由 |
| `test_agent_architecture.py` | Agent 架构测试（55 用例） | SharedMemory、Context、Planner、AgentRegistry、PlannerAgent、ReportAgent |
| `verify_data.py` | 数据对账工具 | 对比 Git 基准数据与 RepoLens 分析器输出 |

## 运行全部测试

```bash
# Windows PowerShell
$env:PYTHONPATH = "backend"; python -m pytest tests/ -v

# macOS / Linux
PYTHONPATH=backend python -m pytest tests/ -v
```

## 运行单个测试文件

```bash
# Agent 架构测试
$env:PYTHONPATH = "backend"; python -m pytest tests/test_agent_architecture.py -v

# 集成测试
$env:PYTHONPATH = "backend"; python tests/test_integration.py
```

## 运行数据对账

```bash
# 先克隆一个仓库
git clone --single-branch https://github.com/psf/requests C:/Temp/requests

# 运行对账（Windows）
$env:PYTHONPATH = "backend"; python tests/verify_data.py C:/Temp/requests

# macOS / Linux
PYTHONPATH=backend python tests/verify_data.py /tmp/requests
```
