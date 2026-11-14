"""Pydantic 请求/响应模型：所有输入在边界处校验，绝不信任客户端数据。"""

import datetime as dt

from pydantic import BaseModel, ConfigDict, Field, field_validator


class _DateStrMixin(BaseModel):
    @field_validator("start_date", "end_date", check_fields=False)
    @classmethod
    def _check_date(cls, v: str) -> str:
        try:
            dt.date.fromisoformat(v)
        except ValueError:
            raise ValueError("日期必须为 YYYY-MM-DD 格式")
        return v


TASK_STATUSES = ("not_started", "in_progress", "blocked", "paused", "done", "cancelled")


class TaskCreate(_DateStrMixin):
    name: str = Field(min_length=1, max_length=200)
    start_date: str
    end_date: str
    progress: int = Field(default=0, ge=0, le=100)
    dependencies: str = ""
    assignee_ids: list[int] = Field(
        default_factory=list, description="任务负责人账号 ID 列表（可多选）"
    )
    status: str = Field(default="not_started", description="任务状态")

    @field_validator("status")
    @classmethod
    def _check_status(cls, v: str) -> str:
        if v not in TASK_STATUSES:
            raise ValueError(f"状态必须为 {'/'.join(TASK_STATUSES)}")
        return v

    @field_validator("dependencies")
    @classmethod
    def _check_deps(cls, v: str) -> str:
        ids = [s.strip() for s in v.split(",") if s.strip()]
        for dep in ids:
            if not dep.isdigit():
                raise ValueError("依赖项必须为任务 ID，多个用英文逗号分隔")
        return ",".join(ids)


class TaskUpdate(_DateStrMixin):
    id: int | None = Field(
        default=None,
        description="批量更新时必填；单个更新时以路径参数为准",
    )
    name: str | None = Field(default=None, min_length=1, max_length=200)
    start_date: str | None = None
    end_date: str | None = None
    progress: int | None = Field(default=None, ge=0, le=100)
    dependencies: str | None = None
    assignee_ids: list[int] | None = Field(
        default=None,
        description="任务负责人账号 ID 列表（整体替换）；不传表示不修改，空列表表示清除全部负责人",
    )
    # 进度说明：写入/更新当日进度快照（配合 progress 变更自动记录）
    note: str | None = Field(default=None, max_length=500)
    status: str | None = Field(default=None, description="任务状态；不传表示不修改")
    status_reason: str | None = Field(
        default=None, max_length=500, description="状态变更原因；转为 blocked 时必填"
    )
    position: int | None = Field(default=None, ge=0)


class TaskOut(_DateStrMixin):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    name: str
    start_date: str
    end_date: str
    progress: int
    dependencies: str
    assignee: str
    assignee_ids: list[int] = []
    status: str = "not_started"
    note: str = ""
    blocked_reason: str = Field(default="", description="阻塞原因（仅阻塞状态有值，取最近一次转阻塞记录）")
    risk_level: str = "ok"
    risk_reasons: list[str] = []
    position: int


class TaskBulkUpdate(BaseModel):
    """拖拽/排序后的批量保存：一次请求原子写入多行。

    changes 列表内不允许重复 id，且每个元素必须携带 id。
    """

    changes: list[TaskUpdate] = Field(min_length=1, max_length=500)


# ---------- 项目 ----------


PROJECT_PRIORITIES = ("high", "medium", "low")


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    priority: str = Field(default="medium", pattern=r"^(high|medium|low)$", description="项目优先级")
    # 仅管理员可指定；普通员工/主管创建时自动归属本部门、本人负责
    department_id: int | None = None
    owner_id: int | None = None


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    priority: str | None = Field(default=None, pattern=r"^(high|medium|low)$", description="项目优先级")
    owner_id: int | None = None
    department_id: int | None = None


class ProjectOut(BaseModel):
    id: int
    name: str
    description: str
    priority: str = "medium"
    priority_label: str = "中"
    task_count: int = 0
    owner_id: int | None = None
    owner_name: str = ""
    department_id: int | None = None
    department_name: str = ""
    can_edit: bool = False


# ---------- 认证与账号 ----------


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=60)
    password: str = Field(min_length=1, max_length=128)


class ChangePasswordIn(BaseModel):
    old_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class UserOut(BaseModel):
    id: int
    username: str
    display_name: str
    role: str
    department_id: int | None = None
    department_name: str = ""
    departments: list[str] = Field(default_factory=list, description="全部所属部门名（一人多部门）")
    department_ids: list[int] = Field(default_factory=list, description="全部所属部门 ID（负责人选择的部门范围过滤）")
    is_active: bool
    work_status: str = "working"
    work_status_label: str = "在岗"
    work_status_until: str | None = Field(
        default=None, description="预计结束时间（ISO）；非在岗状态且已设置时返回，到时自动恢复在岗"
    )


WORK_STATUSES = ("working", "leave", "vacation", "trip")


class WorkStatusIn(BaseModel):
    """员工自助设置自己的工作状态。"""

    work_status: str = Field(pattern=r"^(working|leave|vacation|trip)$")
    # 预计结束时间（ISO 格式，可选）：仅非在岗状态有效，到时自动恢复为在岗
    work_status_until: str | None = Field(default=None, max_length=32)


class DailyTaskCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    note: str = Field(default="", max_length=500)
    assignee_ids: list[int] = Field(
        default_factory=list, description="负责人账号 ID 列表（可多选）；为空时仅创建人本人"
    )


class DailyTaskUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    note: str | None = Field(default=None, max_length=500, description="内容进度说明（按人独立：仅写入/更新本人那条）")
    assignee_ids: list[int] | None = Field(
        default=None, description="负责人账号 ID 列表（整体替换）；不传表示不修改"
    )
    done_today: bool | None = Field(default=None, description="勾选/取消自己的今日完成")


class AdminUserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=60, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(default="", max_length=60)
    role: str = Field(pattern=r"^(admin|supervisor|employee)$")
    department_id: int | None = None
    department_ids: list[int] = Field(
        default_factory=list, description="所属部门 ID 列表（一人多部门，可多选）；首个为主部门"
    )
    wecom_mobile: str = Field(default="", max_length=20, description="企业微信手机号（群提醒 @ 用），可空")


class AdminUserUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=60)
    role: str | None = Field(default=None, pattern=r"^(admin|supervisor|employee)$")
    department_id: int | None = None
    department_ids: list[int] | None = Field(
        default=None, description="所属部门 ID 列表（整体替换）；不传表示不修改"
    )
    is_active: bool | None = None
    wecom_mobile: str | None = Field(default=None, max_length=20, description="企业微信手机号；不传表示不修改")
    work_status: str | None = Field(
        default=None, pattern=r"^(working|leave|vacation|trip)$", description="工作状态；不传表示不修改"
    )
    work_status_until: str | None = Field(
        default=None, max_length=32, description="预计结束时间（ISO）；仅非在岗状态有效，到时自动恢复在岗"
    )


class ResetPasswordIn(BaseModel):
    new_password: str = Field(min_length=8, max_length=128)


# ---------- 部门 ----------


class DepartmentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    description: str = Field(default="", max_length=200)


class DepartmentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    description: str | None = Field(default=None, max_length=200)


class DepartmentOut(BaseModel):
    id: int
    name: str
    description: str
    user_count: int = 0
    project_count: int = 0


# ---------- 进度文档 ----------


class DocumentOut(BaseModel):
    id: int
    project_id: int
    original_name: str
    size: int
    content_type: str
    note: str
    uploaded_at: dt.datetime
    uploader_name: str = ""
