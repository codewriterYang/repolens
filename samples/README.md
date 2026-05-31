# RepoLens 测试示例

用于验证 RepoLens 功能的推荐测试仓库。

## 推荐测试仓库

| 仓库 | 大小 | 用途 |
|------|------|------|
| [psf/requests](https://github.com/psf/requests) | 小（~200 文件） | 快速冒烟测试，克隆快，全面验证所有分析器 |
| [pallets/flask](https://github.com/pallets/flask) | 小（~150 文件） | 经典 Web 框架，测试 pylint 评分 |
| [encode/httpx](https://github.com/encode/httpx) | 中（~300 文件） | 现代 HTTP 库，验证 Git 活动分析 |
| [tiangolo/fastapi](https://github.com/tiangolo/fastapi) | 大（~1100 文件） | 大型仓库，验证超时和性能表现 |
| [pytest-dev/pytest](https://github.com/pytest-dev/pytest) | 大（~600 文件） | 测试框架，高提交量，验证贡献者统计 |

## 使用方式

### 前端界面

在 RepoLens 输入框粘贴仓库 URL，点击"开始分析"。

### API 调用

```bash
# 分析远程仓库
curl -X POST http://localhost:8770/api/analyze \
  -H "Content-Type: application/json" \
  -d '{"repo_url": "https://github.com/psf/requests"}'

# 分析本地仓库
curl -X POST http://localhost:8770/api/analyze \
  -H "Content-Type: application/json" \
  -d '{"repo_url": "/path/to/local/project"}'

# 查看结果
curl http://localhost:8770/api/report/{job_id}
```

## 预期结果

| 仓库 | 预期耗时 | Pylint 评分 | 健康评分范围 |
|------|---------|------------|-------------|
| psf/requests | < 60s | 7.0–9.0 | 60–80 |
| pallets/flask | < 60s | 8.0–9.5 | 65–85 |
| tiangolo/fastapi | < 300s | 7.5–9.0 | 65–80 |
| pytest-dev/pytest | < 180s | 8.0–9.5 | 70–85 |

