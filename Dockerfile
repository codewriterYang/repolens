# RepoLens — AI 驱动的仓库分析平台
# 基于 Python 3.11-slim，内置 git + pylint + radon

FROM python:3.11-slim

LABEL org.opencontainers.image.title="RepoLens"
LABEL org.opencontainers.image.description="AI 驱动的 GitHub 仓库分析平台"
LABEL org.opencontainers.image.version="2.0.0"

# 构建时代理（apt-get / pip install 走代理）
ENV HTTP_PROXY=http://host.docker.internal:7897
ENV HTTPS_PROXY=http://host.docker.internal:7897
ENV NO_PROXY=localhost,127.0.0.1

# 系统依赖：git（克隆仓库）+ pylint/radon（Python 环境内置）
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先复制依赖文件，利用 Docker 层缓存加速重建
COPY backend/pyproject.toml ./
RUN pip install --no-cache-dir -e .

# 复制后端源码
COPY backend/repolens/ ./repolens/

# 数据目录
RUN mkdir -p /app/data

EXPOSE 8770

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8770/api/health').raise_for_status()" || exit 1

CMD ["python", "-m", "uvicorn", "repolens.main:app", "--host", "0.0.0.0", "--port", "8770"]
