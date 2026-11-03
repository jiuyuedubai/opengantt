# OpenGantt 生产镜像：两阶段构建
# 阶段 1：Node 构建前端静态产物
# 阶段 2：Python 精简镜像托管 FastAPI + 前端产物（单容器一体化部署）
#
# 构建：docker build -t opengantt .
# 运行：docker run -d -p 8000:8000 -v opengantt-data:/app/backend/data opengantt

FROM node:22-alpine AS frontend-builder

WORKDIR /build
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build


FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SERVE_FRONTEND=true \
    FRONTEND_DIST=/app/frontend/dist

WORKDIR /app

COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ ./backend/
COPY --from=frontend-builder /build/dist/ ./frontend/dist/

# SQLite 数据文件目录（挂载卷即可持久化）
RUN mkdir -p /app/backend/data

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/health')" || exit 1

WORKDIR /app/backend
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
