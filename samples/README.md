# RepoLens 测试示例

用于验证 RepoLens 功能的推荐测试仓库，覆盖三种分析策略模式。

> 文件数使用 `RepositoryProfiler` 逻辑实测（排除 .git/node_modules/venv 等目录）。

## 推荐测试仓库

| 仓库 | 文件数 | 策略模式 | 用途 |
|------|--------|---------|------|
| [pallets/flask](https://github.com/pallets/flask) | ~80 | **full** (≤500) | 小仓库快速冒烟测试，克隆快，全量 pylint + radon |
| [sqlalchemy/sqlalchemy](https://github.com/sqlalchemy/sqlalchemy) | ~670 | **focused** (501–1000) | 中型仓库，验证 focused 策略标签（排除测试文件 pylint） |
| [tiangolo/fastapi](https://github.com/tiangolo/fastapi) | ~1120 | **fast** (>1000) | 大型仓库，验证 fast 策略标签（仅 radon，跳过 pylint） |

## 策略覆盖验证

| 模式 | 代表仓库 | 文件数 | 置信度 | 行为 |
|------|---------|--------|--------|------|
| full | pallets/flask | ~80 | 100% | 完整 pylint + radon |
| focused | sqlalchemy/sqlalchemy | ~670 | 75% | 非测试文件 pylint + 全量 radon |
| fast | tiangolo/fastapi | ~1120 | 50% | 仅 radon cc，跳过 pylint |

> 💡 **Phase 8 新变化**：不再跳过任何 Agent。FastAPI 大仓库仍会执行 StaticAgent，
> 但仅运行 radon 圈复杂度扫描（fast 模式）。前端和 HTML 报告均会展示策略标签。

## 使用方式

### 前端界面

在 RepoLens 输入框粘贴仓库 URL，点击"开始分析"。

### API 调用

```bash
# 分析远程仓库
curl -X POST http://localhost:8770/api/analyze \
  -H "Content-Type: application/json" \
  -d '{"repo_url": "https://github.com/pallets/flask"}'

# 分析本地仓库
curl -X POST http://localhost:8770/api/analyze \
  -H "Content-Type: application/json" \
  -d '{"repo_url": "/path/to/local/project"}'

# 查看结果
curl http://localhost:8770/api/report/{job_id}
```

## 预期结果

| 仓库 | 策略 | 预期耗时 | 健康评分范围 |
|------|------|---------|-------------|
| pallets/flask | full | < 60s | 65–85 |
| sqlalchemy/sqlalchemy | focused | < 120s | 60–80 |
| tiangolo/fastapi | fast | < 180s | 55–75 |

> ⚠️ FastAPI (fast 模式) 健康评分偏低是正常的——code_quality 维度 B (pylint) 不贡献分数，
> 只靠维度 A (复杂度密度) 得 max 20/40。HTML 报告会显示 "Fast Analysis · Confidence: 50%"。

## 验证脚本

```bash
# 实测仓库文件数（使用与 RepositoryProfiler 一致的逻辑）
python scripts/verify_samples.py
```
