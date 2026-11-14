# OpenGantt 项目知识文档（AI 协作版）

> **用途**：供后续 AI 协作会话一次性载入的项目事实基线，避免上下文过长与幻觉。
> **更新约定**：每次代码变更后，在「§8 变更记录」追加一行；结构/约定变化时同步更新对应章节。
> **信息来源**：代码本身 + 工作日志（`.workbuddy/memory/`）。本文只记录已验证事实，不含推测。

---

## 1. 项目概述

| 项 | 内容 |
|---|---|
| 项目名 | **OpenGantt**——100% 免费可商用的甘特图项目进度管理平台（自研，替代 StarGantt） |
| 技术栈 | 后端 FastAPI + SQLAlchemy 2 + SQLite（可切 PostgreSQL）；前端 Vue 3 + Vite + frappe-gantt 1.2.2 + echarts |
| 部署形态 | 生产：192.168.1.100（Ubuntu 24.04.4，用户 `deploy`），Nginx(80)→静态 dist + 反代 127.0.0.1:8000→uvicorn systemd（服务名 `opengantt`，运行用户 www-data）。生产数据真身：`/opt/opengantt/backend/data/` |
| 本地开发 | Mac 仅开发预览；后端 `./.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000`（在 backend/ 下）；前端改动先 `cd frontend && npm run build` |
| 用户约定 | 零付费依赖；甘特图**纯展示**（勿恢复拖拽）；前端风格"禅道风" |

**核心功能**：登录认证（JWT httpOnly Cookie）、项目/任务/多负责人甘特管理、任务多状态流转（含阻塞原因）、文档中心（上传/树形浏览/日期筛选/多选删除）、每日工作日志（五段式模板）与周报汇总、每日任务、绩效考核（模板库→生成→评分→存档）、跨部门文档授权、企微群推送（工作简报/任务提醒）、操作审计。

---

## 2. 目录结构

```
stargantt/
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI 入口（挂路由、静态托管、启动种子）
│   │   ├── config.py          # Settings（全部环境变量，见 §5）
│   │   ├── database.py        # SessionLocal（autoflush=False）、引擎
│   │   ├── models.py          # 18 个 ORM 模型（见 §3.2）
│   │   ├── schemas.py         # Pydantic 请求/响应模型（TaskOut 含 blocked_reason）
│   │   ├── security.py        # JWT 签发/校验、密码哈希
│   │   ├── errors.py          # 类型化错误（ValidationError/PermissionDeniedError…）
│   │   ├── migrate.py         # 轻量迁移（create_all + ALTER 补列）
│   │   ├── seed.py            # 种子数据（部门/演示项目/账号）
│   │   ├── performance.py     # 绩效：指标聚合 _compute_metrics / 摘要生成 / 模板存取
│   │   ├── wecom.py           # 企微：工作简报（AI 摘要+降级）/任务提醒（部门白名单）
│   │   ├── backup.py          # 数据备份
│   │   ├── holidays.py        # 中国法定节假日（chinese-calendar）
│   │   ├── static_files.py    # SERVE_FRONTEND 时托管 frontend/dist
│   │   └── api/               # 路由层（控制器，不含业务逻辑）
│   │       ├── auth.py(4)  users.py  departments.py(1)  projects.py(5)
│   │       ├── tasks.py(10+，含 remind)  documents.py(8，含多选删除)
│   │       ├── daily_tasks.py(4)  reports.py(6)  doc_access.py(5)
│   │       ├── performance.py(8)  admin.py(15)  audit.py(2)  stats.py search.py
│   ├── services.py            # 服务层（全部业务逻辑，约 2500 行，90+ 函数）
│   ├── data/                  # SQLite + uploads/（生产真身；rsync 必须排除！）
│   └── requirements.txt       # fastapi/uvicorn/SQLAlchemy/PyJWT/python-multipart/chinese-calendar
├── frontend/
│   ├── src/
│   │   ├── main.js            # 路径路由：/ →App.vue，/admin →AdminApp.vue，/dashboard →DashboardApp.vue
│   │   ├── App.vue            # 主应用（约 2900 行）：登录/主页/部门页/项目甘特/文档中心/日志弹窗
│   │   ├── AdminApp.vue       # 管理后台（账号/部门/日志/投入度/审计/备份/绩效考核/文档权限）
│   │   ├── DashboardApp.vue   # 驾驶舱（echarts）
│   │   ├── api/client.js      # 唯一 API 封装（60+ 方法；注意 admin 子对象结构，见 §6）
│   │   └── components/        # LoginView / TaskTable / GanttChart / DocumentsPanel
│   │                          # / ProgressLogs / ToastHost
│   └── dist/                  # 构建产物（FastAPI 托管；部署=更新此目录）
├── tools/perf_ai_score.py     # WorkBuddy 桥接评分工具（fetch/write）
├── deploy/  DEPLOY.md  docker-compose.yml  Dockerfile   # 部署方案（裸机 systemd 已实测；Docker 未实测）
└── docs/                      # 文档（含本文）
```

---

## 3. 核心模块与关键逻辑

### 3.1 后端分层约定
- 严格三层：`api/`（解析请求→调服务→格式化响应）→ `services.py`（业务规则/编排/事务）→ `models.py`。
- 错误统一：`{"error": {code, message}}` 或 FastAPI 默认 `{"detail"}`；类型化错误类在 `errors.py`。
- 数据库变更走 `migrate.py` 自动迁移（create_all + ALTER 补列），无需手工 SQL。

### 3.2 数据模型（models.py，18 个）
`Department, User, UserDepartment(多部门关联), Project, Task, TaskAssignee(任务多负责人), ProgressLog(每日进度快照), TaskNote(按人独立的任务说明), TaskStatusLog(状态流转审计，含阻塞原因), DailyTask, DailyTaskAssignee, DailyNote(补充事项 extras), DailyReport(归档), Document(uuid 落盘 data/uploads), AuditLog, DocAccessGrant(跨部门授权), PerformanceTemplate, PerformanceResult`
- 关键唯一约束：`task_notes(task_id,user_id,log_date)`；文档 `original_name` 上传时加前缀 `部门-姓名-日期/`。

### 3.3 认证与权限（后端强制）
- 登录 → httpOnly Cookie(JWT)；`JWT_SECRET` 未设置时自动生成到 `data/.jwt_secret`。
- 角色权限：`admin` 全部；`supervisor` 本部门项目；`employee` **仅可见/可编辑自己负责的项目**（`_visible_project_ids`：负责 + 名下有任务，**不含本部门项目**）。
- 项目编辑权 `can_edit_project`：admin 或**所属部门成员**（用 `user_departments` 表，非 `users.department_id`）或项目负责人。
- 任务编辑权 `can_edit_task`：项目可编辑者或任务负责人；任务负责人不可删任务。
- 建号说明：admin API 建用户会同时写入 `users.department_id` 与 `user_departments`（多部门）；但员工可见性规则仍使新建员工在无负责项目时看不到任何项目（预期行为）。

### 3.4 文档中心
- 上传：`/api/projects/{id}/documents`，≤20MB/文件，支持 zip（自动解压保留目录结构）与文件夹（webkitedirectory）；文件名加分组前缀 `部门-姓名-日期/`；`session autoflush=False`，新增 ORM 对象后需显式 `db.flush()`。
- 树：`documentTree`（部门→成员→文档），文档节点含 `uploaded_at`（带 Z 的 UTC）与 `can_delete`。
- 删除：单份 `DELETE /api/documents/{id}`；**多选** `POST /api/documents/bulk-delete-ids {ids≤500}`（逐份校验 can_delete）；管理员另有按人/日期批量删除（`/api/admin/documents/bulk-*`）。
- 前端：日期筛选 + 全选（**无日期筛选时全选禁用**，防全库清空）+ 删除所选（>20 份二次确认）。

### 3.5 工作日志 / 日报 / 周报
- 日报六段式：一(完成) 二(进行中) 三(阻塞) 四(关键决策 decisions) 五(补充事项 extras) 六(次日待办)。
- **已取消任务的状态同步**（2026-11-09）：`generate_daily_report` 对 cancelled 任务在**取消日及之后**的日志中整体跳过（不进"进行中/阻塞/次日待办"），取消日之前的历史日期保留原状；任务取消时自动触发 `_refresh_archived_reports_for_task` 重算受影响日期的**已归档日报**（`_apply_status_change` 挂钩，refresh 内先 `db.flush()`——session autoflush=False 下 pending 的状态日志需显式可见）。注意日报 GET 端点返回**纯文本**（非 JSON）。
- **周报**（`generate_weekly_report`）：
  - 概览合并完成项；阻塞项**按任务聚合去重**（最新原因 + 首末日 + 累计天数），明细中长原因折叠为引用；
  - 下周计划**只取最近一次有记录工作日的次日待办**（按任务名再去重）——避免同任务多天重复与进度矛盾。

### 3.6 绩效考核
- 模板库：每员工一份（`performance_templates`），前端展示区按选中员工过滤联动。
- 生成：`POST /api/admin/performance/generate` → `_compute_metrics`（任务总数/完成/逾期——**逾期以今天为基准**，非周期末）+ 文档扫描 + 摘要。
- **WorkBuddy 桥接评分**：`tools/perf_ai_score.py fetch <period>` → 拉报告到 `/tmp/perf_ai_bundle/` → 会话内评分写 `scores.json` → `write <period>` 回写生产。凭证：生产管理员 caoguihao。

### 3.7 企微推送（wecom.py）
- 工作简报：17:30 自动归档时推送（AI 摘要，失败降级模板）；`WECOM_DEPT_WEBHOOKS` 按部门映射。
- **任务提醒**（`send_task_remind`）：单一提醒 Webhook → **部门白名单过滤**：`REMIND_ENABLED_DEPARTMENTS = {"商务运营部"}`，白名单外直接跳过并返回原因（其他部门 Webhook 未配置，避免误入商务群）。接入新部门 → 白名单加部门名。
- 推送是旁路行为：任何失败只记日志，不影响主业务。

### 3.8 前端要点
- 单页三入口（main.js 按 pathname 分发）；**构建版本标识**：`console.log("[OpenGantt] frontend build <UTC时间>")`（vite define 注入 `__BUILD_TIME__`）——排查新旧页面问题先看此 log。
- 文档中心布局：标题行（标题+权限按钮）→ 独立工具条（日期筛选组 | 批量删除组）→ 上传面板 → 树。
- 甘特图：frappe-gantt 纯展示（readonly 恒真）；自定义中文表头；自绘今天标线（勿依赖库的 get_closest_date，月/周视图失效）。
- 修改项目负责人的入口在**项目信息区的负责人名字**（点击弹窗，仅 admin 可见），非顶部工具栏。

---

## 3.9 自动化测试（TEST-001）

- 运行：`cd backend && python -m pytest tests/ -W ignore`；覆盖率：`--cov=app --cov-report=term`（当前 TOTAL ≈58%）。
- **隔离原则**：conftest 在导入 app 前写环境变量（临时 SQLite + 临时 UPLOAD_DIR + SEED_DEMO_DATA），**绝不触碰真实数据**。
- **会话结构**：`client`（未登录，触发建表/种子）→ `admin/supervisor/employee`（各自独立 TestClient 实例登录，**不可共享 client**——cookie 互踩是本套件最初的大坑）。
- CI：`.github/workflows/ci.yml`（pytest + 前端构建）；项目尚无 Git 仓库，接入托管平台后即生效。

---

## 4. 技术要点与约定

| 项 | 约定 |
|---|---|
| 环境变量 | 见 `config.py`：`DATABASE_URL / JWT_SECRET / SERVE_FRONTEND / FRONTEND_DIST / SEED_DEMO_DATA / UPLOAD_DIR / MAX_UPLOAD_MB / WECOM_WEBHOOK_URL / WECOM_DEPT_WEBHOOKS / WECOM_REMIND_WEBHOOK_URL / WECOM_PLATFORM_URL / LLM_API_KEY / LLM_BASE_URL / LLM_MODEL` |
| 部署四步 | ① `cd frontend && npm run build` ② rsync 同步（**必须 `--exclude backend/data`**，服务器数据是最新真身！）③ requirements 变化时 pip install ④ `sudo systemctl restart opengantt` + curl /api/health |
| 生产验证 | 每次部署后：health + **grep 产物关键符号**（如 `grep -c "bulkDeleteDocIds" dist/assets/*.js`）确认新代码真的在线上 |
| 密钥 | 只来自环境变量；个人 LLM key 已停用，LLM 调用走 WorkBuddy 云端免密钥通道 |
| 审计 | 敏感操作（登录/删除/提醒/批量操作）一律 `record_audit` |
| 时区 | DB 存 UTC（isoformat+Z）；前端转本地显示；周报/日报日期匹配用本地时区 |

---

## 5. AI 协作高频陷阱（前车之鉴，务必先读）

1. **client.js 的 `admin: {` 子对象陷阱**：api 对象里 `admin: {`（231 行）子对象吞并了其后所有"看似顶层"的方法（备份/批量删除/绩效等 28 个都在 `api.admin` 下）。给 App.vue 主应用加方法时**必须加在顶层区**（231 行之前，如 deleteDocument 旁）；给 AdminApp 加则放 admin 内。**加完用 node import 验证归属**：`node --input-type=module -e "import('./src/api/client.js').then(m=>console.log(typeof m.api.xxx))"`。
2. **Pydantic 响应剥离**：给路由响应加新字段，**必须同步加到 schemas.py 的对应 Out 模型**（TaskOut/UserOut 等），否则字段被剥离（此坑已踩两次：me 端点、blocked_reason）。
3. **部署必须重启 uvicorn**：后端 py 文件替换后不 `systemctl restart opengantt` 不生效；**部署后必须 grep 产物验证关键符号存在**，不能只看 health。
4. **macOS grep BRE 假阴性**：`grep "a\|b"` 在 macOS 不支持交替（漏匹配）——用 `grep -E "a|b"`。本坑曾两次干扰排查。
5. **文档名带分组前缀**：`部门-姓名-日期/xxx`——按原文件名过滤测试数据时用 `contains`，不要 `startswith`。
6. **后台任务 cwd**：沙箱后台任务 cwd=workspace 根——uvicorn 启动需 `--app-dir backend`（或绝对路径+`cd`）；nohup 方式会被回收，保持运行用 run_in_background。
7. **状态日志时间戳**：全部走 `utc_now`；测试脚本手写 `datetime.now()`（本地时间）会污染 created_at 排序。
8. **员工可见性**：employee 只见"负责 + 名下有任务"的项目——新建员工看不到任何项目属预期行为（非 bug）。
9. **E2E 测试账号**：生产密码已全部改掉（内置 zhangsan/wangwu 登录失败）；用 caoguihao 登录后建**临时账号自验自删**；uid 提取禁用 `grep 首个 id`，删除前必须断言 username（10-28 曾误删 admin）。
10. **frappe-gantt 1.2.2**：CSS 不在 exports（已落 `src/assets/frappe-gantt.css`）；`view_modes` 会覆盖为首页项；库的今日标线在月/周视图失效——用自研 findTodayX。

---

## 6. 运维速查

- 服务管理：`sudo systemctl restart|status opengantt`；health：`curl http://192.168.1.100/api/health`
- 数据备份：服务器 `sudo tar czf ~/og-backup-$(date +%F).tgz -C /opt/opengantt/backend data`
- 干净数据重置：删 `backend/data/` 后重启（自动重新种子；生产慎用！）
- NAS 扩容规划：只迁 `data/uploads`（NFS/SMB 挂载），**SQLite 必须留本地盘**（NFS 锁不可靠）

---

## 7. 变更记录

> 格式：日期 | 改动 | 涉及文件 | 原因/背景。详细过程见 `.workbuddy/memory/<日期>.md`。

| 日期 | 改动 | 涉及文件 | 原因 |
|------|------|----------|------|
| 10-15 | StarGantt 调研，OpenGantt 项目从零搭建 | 全部初始文件 | 替代 StarGantt，零付费可商用 |
| 10-16 | 认证/权限/文档/管理后台大版本上线 | backend/app/**、frontend/src/** | 平台基础能力 |
| 10-16 | 甘特图纯展示改造 + 主页/部门页 | GanttChart.vue、App.vue | 用户嫌拖拽误触 |
| 10-19 | 滚轮缩放修复、进度说明/每日快照、工作日志、禅道风美化 | TaskTable.vue、App.vue | 日常使用体验 |
| 10-19 | 管理员日志导出、17:30 自动归档 | reports、wecom 前身 | 管理需求 |
| 10-20 | P0+P1 改进全量、驾驶舱（echarts） | DashboardApp.vue 等 | 阶段打磨 |
| 10-27 | 操作审计日志功能 | AuditLog、api/audit.py | 追责与合规 |
| 10-28 | 多负责人上线修复轮；说明按人独立（task_notes/daily note） | services.py、models.py | 协作语义修正 |
| 10-29 | 服务器部署完成（Nginx+systemd 上线） | deploy/、DEPLOY.md | 生产化 |
| 10-30 | 企微工作简报推送上线（AI 摘要+降级）、推送按钮修复 | wecom.py、config.py | 每日自动播报 |
| 11-02 | 部署咨询/装机指南（U 盘安装 Ubuntu 24.04.4） | docs | 新目标机准备 |
| 11-04 | 文档跨部门授权（DocAccessGrant）+ 绩效考核入口 | doc_access.py、AdminApp.vue | 跨部门协作需求 |
| 11-04 | 上传改造：zip 自动解压 + 文件夹上传 + 文档扫描入考核 | services.py、App.vue | 批量归档场景 |
| 11-04 | 停用个人智谱 key；WorkBuddy 桥接评分（perf_ai_score.py） | tools/、performance.py | 密钥安全 |
| 11-04 | zip 上传全链路修复（nginx 413 → client_max_body_size 0） | deploy/nginx conf | 321MB 大包上传失败 |
| 11-04 | 上传分组前缀（部门-姓名-日期/）+ 50 上限等三问题修复 | services.py、App.vue | 文件归属与限制 |
| 11-04 | 按人/日期批量删除文档（管理员） | documents.py、services.py | 磁盘清理需求 |
| 11-04 | 改项目负责人入口优化（点名字弹窗，移除顶部下拉） | App.vue | 交互不明显 |
| 11-04 | 文档上传无反应真根因修复（下拉未自动选中导致按钮恒禁用） | App.vue | 用户无法上传 |
| 11-04 | 文档中心日期筛选（纯前端过滤） | App.vue | 按天查看需求 |
| 11-04 | 何花考核分析完整闭环（生成→拉取→评分→写回） | tools/perf_ai_score.py | 绩效考核落地 |
| 11-04 | 阻塞原因查看/修改（TaskOut.blocked_reason + blocked→blocked 修订） | services.py、schemas.py、TaskTable.vue | 填写后不可查看修改 |
| 11-04 | 周报阻塞项按任务合并去重 | services.py | 重复 5 次冗长 |
| 11-05 | 员工新建任务默认负责人=本人（前端默认勾选 + 后端兜底） | App.vue、services.py | 减少漏选负责人 |
| 11-05 | 逾期判断修正（以今天为基准，非周期末） | performance.py | 月初生成误判逾期 |
| 11-06 | 绩效模板展示区与人员选择联动（perfTplForSelected） | AdminApp.vue | 切换人员不更新 |
| 11-06 | 文档多选删除（bulk-delete-ids 端点 + 树内勾选） | documents.py、services.py、App.vue、client.js | 批量清理需求 |
| 11-06 | 全选安全：无日期筛选禁用全选；>20 份二次确认 | App.vue | 防全库误删 |
| 11-06 | 报错真根因：client.js admin 子对象吞并方法 → bulkDeleteDocIds 移到顶层 | client.js | `not a function` 报错 |
| 11-06 | 文档中心布局美化（标题/工具条/树行重排） | App.vue | 视觉与对齐 |
| 11-06 | 构建版本标识（__BUILD_TIME__ + console log） | main.js、vite.config.js | 排查新旧页面 |
| 11-06 | 周报"下周计划"只取最近记录日次日待办 + 按任务名去重 | services.py | 重复且进度矛盾 |
| 11-09 | 任务提醒部门白名单（仅商务运营部，其余拦截并提示） | wecom.py | 其他部门 Webhook 未配置，误入商务群 |
| 11-09 | 任务取消后日志同步：cancelled 任务在取消日及之后的日报中不再出现（实时+归档刷新 `_refresh_archived_reports_for_task`） | services.py | 取消后日报仍显示阻塞/进行中记录 |
| 11-10 | 归档刷新通用化：**所有状态变更**（转阻塞/解除/完成等）都刷新变更日（今天）起的归档日报（含全部负责人当天组合）；取消保留回溯语义 | services.py | 转阻塞后日志没有同步更新 |
| 11-13 | **TEST-001 测试体系落地**：后端 pytest 套件（7 个测试文件 / 37 用例：权限矩阵+越权 404、任务 CRUD 与状态流转、依赖环、文档上传/zip 路径穿越、日报周报去重、管理员保护、备份恢复演练、调度租约、绩效周期过滤）+ pytest.ini + requirements-dev.txt + CI 配置（.github/workflows/ci.yml：pytest+前端构建）；测试期发现并修复：①备份恢复后未清 SQLAlchemy 连接池（engine.dispose，兼生产修复）②任务详情端点 blocked_reason 恒空 | tests/、backend/pytest.ini、backend/requirements-dev.txt、.github/workflows/ci.yml、backup.py、api/tasks.py | AI 评估报告 TEST-001（P0）|（依据 AI_PROJECT_ASSESSMENT.md）：①AUTH-001 任务详情越权→无权统一 404；②AUTH-004 最后管理员保护（停用/降级/删除三处拦截）；③DATA-001 SQLite 外键强制（PRAGMA）+ 孤立数据启动清理（生产清 27/19/19/18 条）；④DATA-002 删除原子性（先 DB 后文件、项目级联清文件、孤立文件启动清理）；⑤JOB-001 每日调度租约锁（job_runs 表，多 Worker 只执行一次）+ TIME-001 调度时区显式 Asia/Shanghai；⑥SEC-001 登录限速 5 次/5 分钟 + COOKIE_SECURE 配置 + 密码最短 8 位；⑦SEC-002 .dockerignore + Dockerfile 非 root；⑧FUNC-001 绩效文档扫描按周期过滤；⑨DOC-001 README/DEPLOY/知识文档与实现对齐 | tasks.py、admin.py、database.py、migrate.py、services.py、models.py、main.py、schemas.py、config.py、security.py、auth.py、performance.py、.dockerignore、Dockerfile、README.md、DEPLOY.md | AI 项目评估报告 P0 整改 |

---

## 8. 待办 / 已知未决

- ~~admin 建用户不写 `user_departments`~~（已核实为过时信息：create_user 现行代码同时写入两处，2026-11-13 修正本文档）——保留的待决事项：员工可见性是否扩展到"本部门项目"（需业务方拍板，见 AUTH-002/003）。
- **NAS 接入**：硬盘扩容规划中——只迁 `data/uploads`，等 NFS/SMB 共享就绪后按既定清单迁移（见对话记录）。
- **其他部门任务提醒**：白名单已关闭；各部门 Webhook 就绪后在 `REMIND_ENABLED_DEPARTMENTS` 中启用。
- Docker 部署方案未实测（本机 Docker 不可用；服务器裸机 systemd 已稳定运行）。
