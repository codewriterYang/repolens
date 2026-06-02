# Docker 部署指南

本文档涵盖 RepoLens 的 Docker 部署、运维和排错指南。

## 快速启动

```bash
# 1. 配置 API Key
cp .env.example .env
# 编辑 .env，填入 LLM_API_KEY

# 2. 一键启动全栈（后端 + 前端）
docker compose up -d
```

## 访问地址

| 服务 | 地址 | 用途 |
|------|------|------|
| **前端 UI** | http://localhost:5173 | 网页界面，输入仓库链接即可分析 |
| **API 文档** | http://localhost:8770/docs | Swagger，直接调用接口 |
| **健康检查** | http://localhost:8770/api/health | 确认后端存活 |

## 常用命令速查

### 启动 / 停止 / 重启

```bash
docker compose up -d          # 启动所有服务（后台运行）
docker compose down           # 停止并删除容器（不删数据）
docker compose down -v        # 停止 + 删除数据卷（⚠️ 数据丢失）
docker compose restart        # 重启所有服务
```

### 构建镜像

修改代码后需要重新构建镜像：

```bash
docker compose build              # 增量构建（利用缓存，推荐）
docker compose build --no-cache   # 彻底重建（清除缓存，较慢）
docker compose build backend      # 仅重建后端镜像
docker compose build frontend     # 仅重建前端镜像
```

```bash
# 清理构建缓存（磁盘空间不足时使用）
docker builder prune -f
```

### 查看状态

```bash
docker compose ps             # 查看运行中的容器
docker compose ps -a          # 查看所有容器（包括已停止的）
docker images                 # 查看镜像及大小
```

### 查看日志

```bash
docker compose logs backend      # 后端日志
docker compose logs frontend     # 前端日志
docker compose logs -f           # 实时跟踪所有日志（Ctrl+C 退出）
docker compose logs --tail=50    # 查看最近 50 行日志
```

### 进入容器调试

```bash
docker exec -it repolens-backend sh    # 进入后端容器
docker exec -it repolens-frontend sh   # 进入前端容器
```

## 数据持久化

`docker-compose.yml` 中配置了卷挂载，将容器内的 SQLite 数据库持久化到宿主机：

```yaml
volumes:
  - ./data:/app/data
```

- **`data/` 目录**：SQLite 数据库 (`repolens.db`) 和相关文件存储在宿主机 `./data/` 目录
- `docker compose down` **不会删除** `data/` 目录，历史分析记录会保留
- 如需完全清理，手动删除 `data/` 目录或执行 `docker compose down -v`

## 环境变量

所有配置通过 `.env` 文件传入容器，详见 `.env.example`：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `LLM_BASE_URL` | `https://api.openai.com/v1` | OpenAI 兼容 API 地址 |
| `LLM_API_KEY` | （必填） | LLM 厂商的 API Key |
| `LLM_MODEL` | `gpt-4o-mini` | 模型名称 |
| `HOST` | `0.0.0.0` | 服务器绑定地址 |
| `PORT` | `8770` | 服务器端口 |
| `DB_PATH` | `data/repolens.db` | SQLite 数据库路径 |
| `TMP_DIR` | 系统临时目录 | 仓库克隆临时目录 |
| `PIPELINE_TIMEOUT_SECONDS` | `600` | 流水线总超时（秒） |
| `CLONE_TIMEOUT_SECONDS` | `300` | 克隆超时（秒） |

修改 `.env` 后需重启容器：

```bash
docker compose restart
```

## 常见问题

### 端口被占用

```bash
# 检查端口占用 (Windows)
netstat -ano | findstr :8770
netstat -ano | findstr :5173

# 检查端口占用 (Linux/Mac)
lsof -i :8770
lsof -i :5173
```

修改 `docker-compose.yml` 中 `ports` 映射，例如：
```yaml
ports:
  - "8771:8770"  # 将宿主机端口改为 8771
```

### 后端无法启动

```bash
# 查看后端日志定位原因
docker compose logs backend

# 常见原因：
# 1. .env 文件不存在或 LLM_API_KEY 未配置
# 2. 端口 8770 被占用
# 3. 网络问题导致镜像拉取失败
```

### 前端无法访问后端 API

前端通过 Nginx 反向代理 `/api/*` 到后端容器。确保：

- 后端容器正常运行：`docker compose ps backend`
- 前端 Nginx 代理配置引用后端容器名 `backend`（已在 `nginx.conf` 中配置）

### 磁盘空间不足

```bash
# 清理未使用的 Docker 资源
docker system prune -a

# 仅清理构建缓存
docker builder prune -f

# 仅清理已停止的容器和悬空镜像
docker container prune -f
docker image prune -f
```
