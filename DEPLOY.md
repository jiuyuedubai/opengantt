# OpenGantt 部署手册

本文覆盖两种环境：**本地开发/体验** 与 **Linux 服务器生产部署**。
两种方案全部基于免费开源组件，无任何付费依赖。

---

## 一、本地部署（已在本机验证通过 ✅）

### 环境要求

| 依赖 | 版本要求 | 说明 |
|------|----------|------|
| Node.js | ≥ 18 | 前端构建 |
| npm | ≥ 9 | 随 Node 附带 |
| Python | ≥ 3.11 | 后端运行（推荐 3.12+） |
| git | 任意 | 拉取代码（可选） |

### 步骤 1：安装后端依赖

```bash
cd backend
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
```

### 步骤 2：启动后端

```bash
./.venv/bin/uvicorn app.main:app --port 8000
# 验证：curl http://127.0.0.1:8000/api/health  →  {"status":"ok",...}
```

首次启动会自动建表并写入演示项目。

### 步骤 3A：开发模式前端（热更新，改代码即时生效）

```bash
cd frontend
npm install
npm run dev
# 访问 http://127.0.0.1:5173（/api 自动代理到 8000 端口）
```

### 步骤 3B：生产模式前端（一体化，单端口）

```bash
cd frontend
npm install
npm run build          # 产出 dist/（约 130KB JS，gzip 后 45KB）
cd ../backend
./.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
# 访问 http://127.0.0.1:8000 —— 前端页面与 API 同端口
```

> 关键机制：后端启动时若检测到 `frontend/dist/index.html` 存在，
> 自动挂载静态托管与 SPA 回退路由。**先 build 后启动后端**即可。

---

## 二、Linux 服务器部署

### 方案 A：Docker Compose（推荐，最简单）

前置：服务器已安装 Docker Engine ≥ 24 与 docker compose 插件
（`curl -fsSL https://get.docker.com | sh` 可一键安装，免费）。

```bash
# 1. 上传代码（或 git clone）到服务器，例如 /opt/opengantt
scp -r ./stargantt user@server:/opt/opengantt
ssh user@server

# 2. 构建并启动（后台运行）
cd /opt/opengantt
docker compose up -d --build

# 3. 验证
curl http://127.0.0.1:8000/api/health
# 浏览器访问 http://<服务器IP>:8000
```

数据持久化：SQLite 文件存放在命名卷 `opengantt-data` 中，
`docker compose down` 不会丢失数据。

**可选切换 PostgreSQL**（长期运行/多人使用建议）：
编辑 `docker-compose.yml`，取消 `db` 服务与 `DATABASE_URL` 注释后重新 `up -d --build`。

**域名 + HTTPS**：在前置 Nginx/Caddy 中将域名反代到 `127.0.0.1:8000`，
或直接把 compose 的端口映射改为 `80:8000` 后用 certbot 申请免费证书。

### 方案 B：裸机部署（uvicorn + systemd + nginx）

不依赖 Docker，适合已有 Python 运维体系的场景。以下以 `/opt/opengantt` 为部署目录、
Ubuntu/Debian 为例（CentOS 将 `apt` 换成 `dnf` 即可）。

```bash
# 1. 系统依赖
sudo apt update && sudo apt install -y python3.12 python3.12-venv nginx

# 2. 上传代码并安装
sudo mkdir -p /opt/opengantt && sudo chown $USER /opt/opengantt
# （scp 上传或 git clone 到 /opt/opengantt）
cd /opt/opengantt/backend
python3.12 -m venv .venv
./.venv/bin/pip install -r requirements.txt

# 3. 构建前端（需要 node 18+，可用 nvm 安装）
cd /opt/opengantt/frontend
npm install && npm run build

# 4. 配置 systemd 常驻服务
sudo cp /opt/opengantt/deploy/opengantt.service /etc/systemd/system/
# 检查文件内 User/路径是否与实际一致
sudo systemctl daemon-reload
sudo systemctl enable --now opengantt
sudo systemctl status opengantt        # 确认 active (running)
curl http://127.0.0.1:8000/api/health  # 本地验证

# 5. 配置 Nginx 对外服务（静态直出 + API 反代）
sudo cp /opt/opengantt/deploy/nginx.conf /etc/nginx/conf.d/opengantt.conf
# 编辑 server_name 为你的域名或服务器 IP
sudo nginx -t && sudo systemctl reload nginx

# 6. 免费开启 HTTPS（Let's Encrypt）
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d gantt.example.com
```

至此访问 `https://gantt.example.com` 即可使用。

**裸机模式要点**：
- `SERVE_FRONTEND` 保持 `true` 时，uvicorn 自己也能完整对外服务（8000 端口直出页面），
  Nginx 仅作为可选的加速与 HTTPS 入口；最小化部署可跳过第 5 步。
- 生产建议设置环境变量 `SEED_DEMO_DATA=false`（service 文件已预设）。

---

## 三、升级与备份

| 操作 | SQLite | PostgreSQL |
|------|--------|------------|
| 备份 | 停服后复制 `backend/data/opengantt.db`（或 `sqlite3 .backup`） | `pg_dump opengantt > backup.sql` |
| 恢复 | 用备份文件替换原文件后重启 | `psql opengantt < backup.sql` |
| 升级代码 | `git pull` → `pip install -r requirements.txt` → `npm run build` → 重启服务 | 同左 |

Docker 模式升级：`git pull && docker compose up -d --build`，数据在卷中不受影响。

## 四、常见问题

**Q：启动后页面空白 / 404？**
A：`SERVE_FRONTEND=true` 要求后端启动前 `frontend/dist/` 已存在。重新 `npm run build` 后重启服务。

**Q：跨域报错（CORS）？**
A：前后端分离部署时，把前端域名加入 `CORS_ORIGINS` 环境变量（逗号分隔，不要用 `*`）。同源部署（一体化/nginx 反代）不会有此问题。

**Q：如何迁移到 PostgreSQL？**
A：安装官方免费驱动：`./.venv/bin/pip install "psycopg[binary]"`（PostgreSQL License，免费），
然后设置 `DATABASE_URL=postgresql+psycopg://user:pass@host:5432/opengantt` 并重启。
建表自动完成（`create_all`）。Docker 模式取消 compose 中 db 服务的注释即可。

**Q：端口 8000 被占用？**
A：uvicorn 换端口 `--port 8010`；Nginx 反代同步修改 `proxy_pass`。

**Q：多人同时编辑会冲突吗？**
A：单机 SQLite 适合中小团队（并发写入以 WAL 语义排队）；高并发场景切换 PostgreSQL。

**Q：默认账号安全吗？**
A：内置 admin/admin123 与演示账号仅用于快速体验。生产部署后请立即：
1. 用 admin 登录 `http://<服务器>/admin`，为每位员工创建独立账号并下发；
2. 重置或停用演示账号（zhangsan/lisi/wangwu）；
3. 在环境变量中显式设置 `JWT_SECRET`（避免依赖自动生成的本地密钥文件）。

**Q：上传的文档存在哪里？**
A：`backend/data/uploads/`（数据库只存索引与原始文件名）。Docker 部署时该目录在
`opengantt-data` 数据卷内；大小限制由 `MAX_UPLOAD_MB` 控制（默认 20MB）。

**Q：权限是如何划分的？**
A：管理员=全部项目；部门主管=本部门所有项目的修改权；普通员工=仅自己负责的项目
（新建项目自动归属本人+本部门）。删除项目限管理员或项目负责人。以上均在后端强制校验，
前端仅做对应的界面隐藏。
