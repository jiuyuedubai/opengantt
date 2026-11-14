"""轻量启动迁移：为已存在的旧表补充新增列（SQLite/PostgreSQL 通用 ALTER）。

仅处理"加列"这类安全演进；新表由 Base.metadata.create_all 自动创建。
"""

import logging

from sqlalchemy import inspect, text

from app.database import SessionLocal, engine

logger = logging.getLogger("opengantt.migrate")

# 表名 -> {列名: DDL 片段}
_ADDED_COLUMNS: dict[str, dict[str, str]] = {
    "projects": {
        "owner_id": "INTEGER",
        "department_id": "INTEGER",
        "priority": "VARCHAR(10) DEFAULT 'medium'",
    },
    "tasks": {
        "assignee_id": "INTEGER",
        "status": "VARCHAR(20) DEFAULT 'not_started'",
    },
    "users": {
        "last_login_at": "DATETIME",
        "wecom_mobile": "VARCHAR(20) DEFAULT ''",
        "work_status": "VARCHAR(10) DEFAULT 'working'",
        "work_status_until": "DATETIME",
    },
    "daily_task_assignees": {
        # 每日任务说明按人独立：旧共享说明（daily_tasks.note）在加列当刻复制给每个负责人
        "note": "VARCHAR(500) DEFAULT ''",
    },
    "daily_notes": {
        "extras": "VARCHAR(2000) DEFAULT ''",
    },
}

# 常用查询索引（幂等）
_CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project_id)",
    "CREATE INDEX IF NOT EXISTS idx_tasks_assignee ON tasks(assignee_id)",
    "CREATE INDEX IF NOT EXISTS idx_progress_logs_user ON progress_logs(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_progress_logs_date ON progress_logs(log_date)",
    "CREATE INDEX IF NOT EXISTS idx_task_notes_user_date ON task_notes(user_id, log_date)",
    "CREATE INDEX IF NOT EXISTS idx_task_status_logs_task ON task_status_logs(task_id)",
]


def run_migrations() -> None:
    inspector = inspect(engine)
    with engine.begin() as conn:
        for table, columns in _ADDED_COLUMNS.items():
            if not inspector.has_table(table):
                continue
            existing = {col["name"] for col in inspector.get_columns(table)}
            for col_name, col_ddl in columns.items():
                if col_name in existing:
                    continue
                try:
                    logger.info("迁移：为 %s 增加列 %s", table, col_name)
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_ddl}"))
                except Exception as exc:  # noqa: BLE001 — 多 worker 并发启动会重复执行同一迁移
                    msg = str(exc).lower()
                    if "duplicate column" in msg or "already exists" in msg:
                        logger.warning("迁移：列 %s.%s 已由并发进程创建，跳过", table, col_name)
                        continue
                    raise
                # 列创建当刻执行一次性数据回填（Inspector 有缓存，不能依赖其后置检查）
                if table == "tasks" and col_name == "status":
                    backfilled = conn.execute(
                        text(
                            """
                            UPDATE tasks SET status = CASE
                                WHEN progress >= 100 THEN 'done'
                                WHEN progress > 0 THEN 'in_progress'
                                ELSE 'not_started'
                            END
                            WHERE (status IS NULL OR status = 'not_started') AND progress > 0
                            """
                        )
                    )
                    if backfilled.rowcount:
                        logger.info("迁移：按进度回填 %d 条任务状态", backfilled.rowcount)
                if table == "daily_task_assignees" and col_name == "note":
                    backfilled = conn.execute(
                        text(
                            """
                            UPDATE daily_task_assignees
                            SET note = (SELECT d.note FROM daily_tasks d WHERE d.id = daily_task_id)
                            WHERE (note IS NULL OR note = '')
                              AND (SELECT d.note FROM daily_tasks d WHERE d.id = daily_task_id) != ''
                            """
                        )
                    )
                    if backfilled.rowcount:
                        logger.info("迁移：回填 %d 条每日任务共享说明到各负责人", backfilled.rowcount)

        # 任务进度说明回填：旧 progress_logs.note（每天每任务一条、仅最后记录人的内容）
        # 导入按人独立的 task_notes（仅在表为空时执行一次；并发冲突视为对方已完成）
        if (
            inspector.has_table("task_notes")
            and inspector.has_table("progress_logs")
            and conn.execute(text("SELECT COUNT(*) FROM task_notes")).scalar() == 0
        ):
            try:
                backfilled = conn.execute(
                    text(
                        """
                        INSERT OR IGNORE INTO task_notes (task_id, user_id, log_date, note, updated_at)
                        SELECT p.task_id,
                               COALESCE(p.user_id, t.assignee_id),
                               p.log_date,
                               p.note,
                           datetime('now')
                        FROM progress_logs p
                        LEFT JOIN tasks t ON t.id = p.task_id
                        WHERE p.note != ''
                          AND COALESCE(p.user_id, t.assignee_id) IS NOT NULL
                        """
                    )
                )
                if backfilled.rowcount:
                    logger.info("迁移：回填 %d 条任务进度说明到 task_notes", backfilled.rowcount)
            except Exception as exc:  # noqa: BLE001 — 多 worker 并发回填
                msg = str(exc).lower()
                if "unique" in msg or "duplicate" in msg or "locked" in msg:
                    logger.warning("迁移：task_notes 回填并发冲突，跳过")
                else:
                    raise

        # 常用查询索引（幂等，CREATE INDEX IF NOT EXISTS）
        for idx_sql in _CREATE_INDEXES:
            conn.execute(text(idx_sql))

        # 历史数据回填：按负责人姓名/用户名匹配账号，补充 tasks.assignee_id
        if inspector.has_table("tasks") and inspector.has_table("users"):
            users_exist = conn.execute(text("SELECT COUNT(*) FROM users")).scalar()
            if users_exist:
                matched = conn.execute(
                    text(
                        """
                        UPDATE tasks SET assignee_id = (
                            SELECT u.id FROM users u
                            WHERE u.display_name = tasks.assignee OR u.username = tasks.assignee
                            LIMIT 1
                        )
                        WHERE assignee_id IS NULL AND assignee != ''
                        """
                    )
                )
                if matched.rowcount:
                    logger.info("迁移：为 %d 条历史任务回填负责人账号", matched.rowcount)

        # 多负责人表回填：存量任务的单一负责人导入 task_assignees（仅在表为空时执行一次）
        if (
            inspector.has_table("task_assignees")
            and inspector.has_table("tasks")
            and conn.execute(text("SELECT COUNT(*) FROM task_assignees")).scalar() == 0
        ):
            backfilled = conn.execute(
                text(
                    """
                    INSERT INTO task_assignees (task_id, user_id, created_at)
                    SELECT id, assignee_id, datetime('now')
                    FROM tasks
                    WHERE assignee_id IS NOT NULL
                    """
                )
            )
            if backfilled.rowcount:
                logger.info("迁移：回填 %d 条任务负责人到 task_assignees", backfilled.rowcount)

        # 每日任务负责人回填：旧版个人任务的归属人导入 daily_task_assignees（仅在表为空时执行一次）；
        # 当日已完成状态（last_done_date=今天）随迁移保留到关联行
        if (
            inspector.has_table("daily_task_assignees")
            and inspector.has_table("daily_tasks")
            and conn.execute(text("SELECT COUNT(*) FROM daily_task_assignees")).scalar() == 0
        ):
            backfilled = conn.execute(
                text(
                    """
                    INSERT INTO daily_task_assignees (daily_task_id, user_id, done_date)
                    SELECT id, user_id,
                           CASE WHEN last_done_date = date('now', 'localtime') THEN last_done_date ELSE '' END
                    FROM daily_tasks
                    WHERE user_id IS NOT NULL
                    """
                )
            )
            if backfilled.rowcount:
                logger.info("迁移：回填 %d 条每日任务负责人到 daily_task_assignees", backfilled.rowcount)

        # 一人多部门回填：主部门导入 user_departments（仅在表为空时执行一次）
        if (
            inspector.has_table("user_departments")
            and inspector.has_table("users")
            and conn.execute(text("SELECT COUNT(*) FROM user_departments")).scalar() == 0
        ):
            backfilled = conn.execute(
                text(
                    """
                    INSERT INTO user_departments (user_id, department_id)
                    SELECT id, department_id FROM users
                    WHERE department_id IS NOT NULL
                    """
                )
            )
            if backfilled.rowcount:
                logger.info("迁移：回填 %d 条用户部门到 user_departments", backfilled.rowcount)


def cleanup_orphan_rows() -> dict:
    """清理历史遗留的孤立子记录（DATA-001）：任务删除后未级联清理的关联行。

    幂等：无孤立行时为空操作。在启动迁移阶段执行一次。
    """
    with SessionLocal() as db:
        counts = {}
        for table in ("progress_logs", "task_assignees", "task_status_logs", "task_notes"):
            res = db.execute(
                text(
                    f"DELETE FROM {table} WHERE task_id NOT IN (SELECT id FROM tasks)"  # noqa: S608
                )
            )
            if res.rowcount:
                counts[table] = res.rowcount
        db.commit()
        if counts:
            logger.warning("已清理孤立子记录：%s", counts)
        return counts
