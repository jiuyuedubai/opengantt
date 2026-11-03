# OpenGantt · 免费开源甘特图项目进度管理平台

一个 **100% 免费、可商用、可私有部署** 的项目进度管理工具。前端采用 MIT 协议的
[Frappe Gantt](https://github.com/frappe/gantt) 甘特图引擎，后端为 FastAPI + SQLAlchemy，
数据 100% 存在你自己的数据库中，**不依赖任何付费服务或第三方 API**。

## 功能特性

### 页面导航
- **主页**：按部门分块的导航页，展示各部门人数 / 项目数 / 任务数统计，点击进入部门页
- **部门页**（`/dept/<id>`）：每个部门独立页面，列出该部门所有项目，点选项目即进入详情（任务表格 + 甘特图 + 进度文档）
- **管理员后台**（`/admin`）：独立入口，账号 / 部门 / 统计管理

### 项目与甘特图
- **甘特图可视化**：日 / 周 / 月 / 年四种视图一键切换，周末底纹高亮，今日标线
- **纯展示模式**：甘特图不支持拖拽（防误触），"回到今天"按钮快速定位当前日期
- **进度跟踪**：通过任务表格的行内编辑调整进度，实时同步到甘特图
- **任务依赖**：支持 FS 依赖（前置完成 → 后续开始），依赖环自动拦截
- **任务表格**：左侧表格行内编辑任务名称、日期、负责人、依赖（唯一的修改入口）
- **多项目**：按部门组织，显示负责人与权限标记（可编辑 / 只读）
- **CSV 导出**：带 BOM 的 UTF-8 编码，Excel 打开中文不乱码
- **开箱即用**：首次启动自动写入演示项目

### 账号与权限
- **账号密码登录**：账号由管理员在后台统一创建并下发；会话使用 HttpOnly Cookie（JWT），不落 localStorage
- **三种角色**：管理员（全部权限）/ 部门主管（可修改本部门所有项目）/ 普通员工（仅可添加和修改自己负责的项目）
- **任务负责人**：任务的"负责人"从账号列表中选择，被分配人即使无项目编辑权也可修改该任务（不可删除）；历史数据按姓名自动回填
- **部门管理**：内置人事行政部、财务部、总经办、商务运营部、销售部、项管中心六个部门，支持增删改
- **项目归属**：项目自动归属创建人所在部门、负责人为创建人；管理员可指定

### 任务状态与停滞追踪
- **显式状态**：未开始 / 进行中 / 🔴阻塞 / 暂停 / 已完成 / 已取消，与进度解耦；转阻塞强制填写原因
- **风险分级**：🟢 正常 / 🟡 关注（逾期、落后计划 ≥20%、连续 3 天未填说明）/ 🔴 停滞（进度 ≥3 天无变化、逾期 ≥3 天、阻塞）
- **状态变更审计**：谁、何时、从什么状态改到什么状态、原因，全程留痕
- **快捷过滤**：部门页一键切换 全部 / 我的任务 / 本周到期 / 已逾期 / 停滞

### 驾驶舱与投入度分析（主管/管理员）
- **驾驶舱**（`/dashboard`，ECharts）：部门进度总览、任务状态分布、项目进度趋势（实际 vs 期望）、员工投入度排行、活跃热力图、逾期/停滞清单
- **投入度分析**（管理后台）：近 7/14/30 天更新次数、说明填写率、平均停滞天数、最后活跃/登录，🚩 标记名下有任务但零更新的员工
- **全局搜索**：顶栏 Ctrl+K，任务 / 项目 / 人员一键直达

### 进度文档
- **上传 / 查看 / 下载**：项目进度文档（周报、验收单等）随项目归档，可加备注
- 文件以 uuid 落盘在数据目录，下载还原原始文件名；默认限 20 MB
- 上传时间按 UTC 存储并携带时区标记，前端自动转换为本地时区显示

### 管理员后台（/admin）
- **员工账号管理**：创建、改角色/部门、重置密码、停用/启用、删除
- **部门管理**：新建、改名、删除（有账号/项目时禁止删除）
- **系统概览**：账号 / 项目 / 任务 / 文档总量与分部门统计
- **操作日志（审计）**：自动记录登录（含失败尝试）、项目/任务/文档增删改、账号与部门管理、
  密码变更等关键操作的操作人、类型、时间、对象、详情与来源 IP；支持按操作人、
  操作类型、时间范围筛选与分页查询（仅管理员可见；删除/重置密码等敏感操作红色标识）

## 技术栈与许可（全部免费商用）

| 层 | 组件 | 许可 |
|----|------|------|
| 甘特图引擎 | [frappe-gantt](https://github.com/frappe/gantt) 1.2.2 | MIT |
| 前端框架 | Vue 3.5 + Vite 7 | MIT |
| 后端框架 | FastAPI 0.143 + Uvicorn | MIT / BSD |
| ORM | SQLAlchemy 2.1 | MIT |
| 认证 | PyJWT 2.15 + PBKDF2（标准库） | MIT / PSF |
| 文件上传 | python-multipart 0.0.32 | Apache-2.0 |
| 数据库 | SQLite（默认）/ PostgreSQL（可选） | 公有领域 / PostgreSQL License |
| 部署 | Docker / Nginx / systemd（可选） | Apache-2.0 / BSD-2 |

## 内置账号（首次启动自动创建）

| 账号 | 密码 | 角色 | 部门 |
|------|------|------|------|
| admin | admin123 | 管理员 | — |
| zhangsan | 123456 | 部门主管 | 项管中心 |
| lisi | 123456 | 普通员工 | 商务运营部 |
| wangwu | 123456 | 普通员工 | 项管中心 |

> ⚠️ 生产部署后请立即登录并修改默认密码（管理员可在后台重置任意账号密码）。

## 快速开始（本地）

前置要求：Node.js ≥ 18（本机已验证 v22）、Python ≥ 3.11（本机已验证 3.13）

```bash
# 1. 后端
cd backend
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
./.venv/bin/uvicorn app.main:app --port 8000

# 2. 前端（另开一个终端）
cd frontend
npm install
npm run dev          # 开发模式，访问 http://127.0.0.1:5173
```

生产模式（单端口一体化）：

```bash
cd frontend && npm install && npm run build   # 产出 dist/
cd ../backend && ./.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
# 浏览器访问 http://127.0.0.1:8000 → 使用内置账号登录
```

> Linux 服务器部署（Docker 与裸机两种方案）见 **[DEPLOY.md](./DEPLOY.md)**。

## 项目结构

```
stargantt/
├── backend/                 # FastAPI 后端
│   ├── app/
│   │   ├── __init__.py      # create_app：CORS、路由、静态托管
│   │   ├── config.py        # 环境变量集中校验（快速失败）
│   │   ├── errors.py        # 类型化错误 + 全局异常处理
│   │   ├── database.py      # 引擎/会话工厂
│   │   ├── models.py        # Project / Task ORM 模型
│   │   ├── schemas.py       # Pydantic 输入校验
│   │   ├── services.py      # 业务逻辑（依赖环检测、事务）
│   │   ├── seed.py          # 演示数据
│   │   ├── static_files.py  # SPA 静态托管 + 回退
│   │   ├── main.py          # 启动入口
│   │   └── api/             # 路由层（控制器）
│   ├── requirements.txt
│   └── .env.example
├── frontend/                # Vue 3 + frappe-gantt
│   └── src/
│       ├── App.vue          # 主界面
│       ├── api/client.js    # 类型化 fetch 封装
│       └── components/
│           ├── GanttChart.vue   # 甘特图封装（拖拽事件→持久化）
│           ├── TaskTable.vue    # 任务表格（行内编辑）
│           └── ToastHost.vue    # 错误提示
├── deploy/                  # 服务器部署配套（nginx / systemd）
├── Dockerfile               # 两阶段构建（Node 构建 → Python 托管）
├── docker-compose.yml       # 一键编排（含可选 PostgreSQL）
└── DEPLOY.md                # 完整部署手册
```

## API 概览

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/auth/login` | 账号密码登录（种 HttpOnly Cookie） |
| GET | `/api/auth/me` | 当前登录用户 |
| POST | `/api/auth/logout` | 退出登录 |
| POST | `/api/auth/change-password` | 修改自己密码 |
| GET / POST | `/api/projects` | 项目列表（含 can_edit 权限标记）/ 新建 |
| PATCH / DELETE | `/api/projects/{id}` | 更新 / 删除（按角色鉴权） |
| GET / POST | `/api/projects/{id}/tasks` | 任务列表 / 新建 |
| PATCH | `/api/projects/{id}/tasks/bulk` | 批量原子更新（拖拽批量保存） |
| PATCH / DELETE | `/api/projects/{id}/tasks/{tid}` | 单任务更新 / 删除 |
| POST / GET | `/api/projects/{id}/documents` | 上传 / 列出进度文档 |
| GET | `/api/documents/{id}/download` | 下载文档 |
| * | `/api/admin/*` | 管理员后台（账号/部门/统计，仅 admin 角色） |
| GET | `/api/audit-logs` | 操作审计日志分页查询（操作人/动作/时间范围筛选，仅 admin） |
| GET | `/api/audit-logs/actions` | 操作类型字典（筛选下拉） |
| GET | `/api/health` | 健康检查 |

错误统一返回规范化结构：`{"error": {"code": "..."}}` 或 `{"detail": "..."}`，绝不暴露堆栈。
启动后可访问 `http://127.0.0.1:8000/docs` 查看交互式 API 文档。

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DATABASE_URL` | `sqlite:///backend/data/opengantt.db` | 数据库连接，可切换 PostgreSQL |
| `JWT_SECRET` | 自动生成并持久化到 `data/.jwt_secret` | JWT 签名密钥，生产建议显式设置 |
| `TOKEN_EXPIRE_DAYS` | `7` | 登录会话有效期（天） |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | `admin` / `admin123` | 内置管理员初始账号（仅首次种子） |
| `MAX_UPLOAD_MB` | `20` | 进度文档上传大小限制 |
| `CORS_ORIGINS` | `http://localhost:5173,...` | 允许的跨域来源，生产同源无需修改 |
| `SERVE_FRONTEND` | `true` | 后端是否托管前端构建产物 |
| `FRONTEND_DIST` | `../frontend/dist` | 前端构建产物目录 |
| `SEED_DEMO_DATA` | `true` | 首次启动写入部门/账号/演示项目 |

完整说明见 `backend/.env.example`。

## 数据与备份

所有业务数据存储在 `backend/data/` 目录：
- `opengantt.db`：SQLite 数据库（项目/任务/账号/部门/文档索引）
- `uploads/`：上传的项目进度文档
- `.jwt_secret`：JWT 签名密钥（自动生成）

备份只需复制整个 `data/` 目录；PostgreSQL 模式下使用 `pg_dump` 常规备份。

## 许可

本项目代码以 MIT 协议发布。所依赖的第三方组件均为宽松许可（见上表），
可自由用于个人与商业场景。
