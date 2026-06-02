# RepoLens — AI 驱动的仓库分析平台
# 基于 Python 3.11-slim，内置 git + pylint + radon
# 使用国内镜像源，无需代理

FROM docker.m.daocloud.io/library/python:3.11-slim

LABEL org.opencontainers.image.title="RepoLens"
LABEL org.opencontainers.image.description="AI 驱动的 GitHub 仓库分析平台"
LABEL org.opencontainers.image.version="2.0.0"

# apt 国内镜像源（USTC）
RUN sed -i 's|deb.debian.org|mirrors.ustc.edu.cn|g' /etc/apt/sources.list.d/debian.sources

# pip 国内镜像源（清华）
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple

# 系统依赖：git（克隆仓库）
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
