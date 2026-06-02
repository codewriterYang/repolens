# RepoLens Frontend — React + Vite + Nginx
# 多阶段构建：先打包，再用 Nginx 托管

# Stage 1: Node.js 构建
FROM docker.m.daocloud.io/library/node:20-alpine AS build

# npm 国内镜像源（淘宝）
RUN npm config set registry https://registry.npmmirror.com

WORKDIR /app

# 先复制依赖文件，利用层缓存
COPY package.json ./
RUN npm install

# 复制前端源码并构建
COPY . .
RUN npm run build

# Stage 2: Nginx 托管
FROM docker.m.daocloud.io/library/nginx:alpine

# 复制构建产物
COPY --from=build /app/dist /usr/share/nginx/html

# 复制 Nginx 配置
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD wget -qO- http://localhost:80/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
