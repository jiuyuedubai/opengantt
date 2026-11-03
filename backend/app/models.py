"""SQLAlchemy ORM 模型：项目、任务、用户、部门、进度文档。"""

import datetime as dt

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, utc_now


class Department(Base):
    __tablename__ = "departments"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(60), nullable=False, unique=True)
    description: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utc_now)

    users: Mapped[list["User"]] = relationship(back_populates="department")


class User(Base):
    """账号由管理员在后台统一创建并下发给员工。"""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(60), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(200), nullable=False)
    display_name: Mapped[str] = mapped_column(String(60), default="")
    # admin=管理员 / supervisor=部门主管 / employee=普通员工
    role: Mapped[str] = mapped_column(String(20), default="employee", nullable=False)
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"), nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    last_login_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    # 企业微信手机号：群机器人 @提醒 用（mentioned_mobile_list），管理员在后台维护
    wecom_mobile: Mapped[str] = mapped_column(String(20), default="")
    # 工作状态：working=在岗 / leave=请假 / vacation=休假 / trip=出差；简报统计仅计在岗
    work_status: Mapped[str] = mapped_column(String(10), default="working", nullable=False)
    # 预计结束时间（仅非在岗状态有效）：到时由后台线程自动恢复为在岗
    work_status_until: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utc_now)

    department: Mapped[Department | None] = relationship(back_populates="users")


class UserDepartment(Base):
    """用户 ↔ 部门 多对多关联（一人多部门）。

    users.department_id 保留为"主部门"（首个部门，兼容既有逻辑）；
    完整归属关系以本表为准：权限判定、文档可见性、部门概览计数均查此表。
    """

    __tablename__ = "user_departments"
    __table_args__ = (UniqueConstraint("user_id", "department_id", name="uq_user_department"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id", ondelete="CASCADE"), nullable=False)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(String(500), default="")
    # 项目优先级：high/medium/low（通知与项目列表展示标识）
    priority: Mapped[str] = mapped_column(String(10), default="medium", nullable=False)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utc_now)

    owner: Mapped[User | None] = relationship()
    department: Mapped[Department | None] = relationship()
    tasks: Mapped[list["Task"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="Task.position",
    )
    documents: Mapped[list["Document"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        UniqueConstraint("project_id", "position", name="uq_task_project_position"),
        CheckConstraint("progress >= 0 AND progress <= 100", name="ck_task_progress"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    start_date: Mapped[str] = mapped_column(String(10), nullable=False)
    end_date: Mapped[str] = mapped_column(String(10), nullable=False)
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    dependencies: Mapped[str] = mapped_column(String(500), default="")
    assignee: Mapped[str] = mapped_column(String(60), default="")
    # 任务负责人（关联账号）：被分配人可修改本任务
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    # 显式状态：未开始/进行中/阻塞/暂停/已完成/已取消（与进度解耦，阻塞可发生在任意进度）
    status: Mapped[str] = mapped_column(String(20), default="not_started", nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utc_now)

    project: Mapped[Project] = relationship(back_populates="tasks")


class ProgressLog(Base):
    """任务进度每日快照：每天每任务一条（自动保存 + 人工说明覆盖）。"""

    __tablename__ = "progress_logs"
    __table_args__ = (UniqueConstraint("task_id", "log_date", name="uq_progress_task_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    log_date: Mapped[str] = mapped_column(String(10), nullable=False)  # YYYY-MM-DD
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    note: Mapped[str] = mapped_column(String(500), default="")
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utc_now)

    task: Mapped[Task] = relationship()
    user: Mapped[User | None] = relationship()


class DailyTask(Base):
    """每日任务：持久化的周期任务，日期恒为当天；可分配给多名成员（各自动完成状态独立）。"""

    __tablename__ = "daily_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    # 创建人（旧版数据该列即"归属人"，迁移时已自动导入负责人关联表）
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    note: Mapped[str] = mapped_column(String(500), default="")
    # 已废弃：完成状态迁移至 daily_task_assignees.done_date；保留列以兼容历史库回填
    last_done_date: Mapped[str] = mapped_column(String(10), default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utc_now)

    user: Mapped[User] = relationship()


class DailyTaskAssignee(Base):
    """每日任务 ↔ 成员 多对多关联；done_date 记录该成员最近完成日（跨天自动回到未完成）。"""

    __tablename__ = "daily_task_assignees"
    __table_args__ = (UniqueConstraint("daily_task_id", "user_id", name="uq_daily_task_assignee"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    daily_task_id: Mapped[int] = mapped_column(ForeignKey("daily_tasks.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    done_date: Mapped[str] = mapped_column(String(10), default="")
    # 内容进度说明按人独立：每个负责人各自填写，互不影响、互不可见他人内容
    note: Mapped[str] = mapped_column(String(500), default="")

    user: Mapped[User] = relationship()


class DailyNote(Base):
    """每日工作日志的人工补充：关键决策等（每用户每天一条）。"""

    __tablename__ = "daily_notes"
    __table_args__ = (UniqueConstraint("user_id", "log_date", name="uq_daily_note_user_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    log_date: Mapped[str] = mapped_column(String(10), nullable=False)
    decisions: Mapped[str] = mapped_column(String(1000), default="")
    # 补充条目（临时事项）：每行一条，随当日日志归档展示
    extras: Mapped[str] = mapped_column(String(2000), default="")
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utc_now)

    user: Mapped[User] = relationship()


class TaskNote(Base):
    """任务进度说明（按人独立）：每任务每人每天一条，互不影响、互不可见他人内容。

    ProgressLog 仍承担"任务当日进度快照"职责（每天每任务一条、共享进度%），
    说明内容以本表为准——多负责人各自填写不会互相覆盖。
    """

    __tablename__ = "task_notes"
    __table_args__ = (UniqueConstraint("task_id", "user_id", "log_date", name="uq_task_note_person_day"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    log_date: Mapped[str] = mapped_column(String(10), nullable=False)  # YYYY-MM-DD
    note: Mapped[str] = mapped_column(String(500), default="")
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)

    task: Mapped[Task] = relationship()
    user: Mapped[User] = relationship()


class DailyReport(Base):
    """每日 17:30 自动归档的工作日志（每用户每天一份，覆盖更新）。"""

    __tablename__ = "daily_reports"
    __table_args__ = (UniqueConstraint("user_id", "log_date", name="uq_daily_report_user_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    log_date: Mapped[str] = mapped_column(String(10), nullable=False)
    markdown: Mapped[str] = mapped_column(Text, nullable=False)
    saved_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utc_now)

    user: Mapped[User] = relationship()


class TaskStatusLog(Base):
    """任务状态变更审计：谁、何时、从什么状态改到什么状态。"""

    __tablename__ = "task_status_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    from_status: Mapped[str] = mapped_column(String(20), default="")
    to_status: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utc_now)

    task: Mapped[Task] = relationship()
    user: Mapped[User | None] = relationship()


class TaskAssignee(Base):
    """任务负责人多对多关联：一个任务可指派多名负责人。

    tasks.assignee 列保留为显示快照（全部负责人姓名拼接），
    tasks.assignee_id 保留为首负责人（历史兼容字段）。
    """

    __tablename__ = "task_assignees"
    __table_args__ = (UniqueConstraint("task_id", "user_id", name="uq_task_assignee"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utc_now)


class Document(Base):
    """项目进度文档：上传后以 uuid 落盘，下载时还原原始文件名。"""

    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    uploader_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_name: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), default="")
    note: Mapped[str] = mapped_column(String(200), default="")
    uploaded_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utc_now)

    project: Mapped[Project] = relationship(back_populates="documents")
    uploader: Mapped[User | None] = relationship()


class AuditLog(Base):
    """系统操作审计日志：谁（操作人快照）、何时、对什么对象做了什么、来自哪个 IP。

    username 冗余快照：账号被删除后（user_id 置空）日志仍可读、可检索。
    """

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    username: Mapped[str] = mapped_column(String(60), default="", index=True)
    action: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    object_type: Mapped[str] = mapped_column(String(30), default="")
    object_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    object_name: Mapped[str] = mapped_column(String(200), default="")
    detail: Mapped[str] = mapped_column(String(500), default="")
    ip: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utc_now, index=True)

    user: Mapped[User | None] = relationship()
