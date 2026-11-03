"""服务层：业务规则（依赖环检测、权限矩阵、多行事务），不依赖 HTTP 对象。

权限模型：
- admin       全部项目
- supervisor  本部门所有项目
- employee    仅自己负责的项目（owner_id == 本人）
"""

import secrets
import datetime as dt
import logging
from pathlib import Path

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.config import settings
from app.errors import DependencyCycleError, NotFoundError, PermissionDeniedError, ValidationError
from app.models import (
    AuditLog,
    DailyNote,
    DailyReport,
    DailyTask,
    DailyTaskAssignee,
    Department,
    Document,
    ProgressLog,
    Project,
    Task,
    TaskAssignee,
    TaskNote,
    TaskStatusLog,
    User,
    UserDepartment,
)
from app.schemas import DailyTaskCreate, DailyTaskUpdate, ProjectCreate, ProjectUpdate, TaskCreate, TaskUpdate

ROLE_LABELS = {"admin": "管理员", "supervisor": "部门主管", "employee": "普通员工"}
PRIORITY_LABELS = {"high": "高", "medium": "中", "low": "低"}
WORK_STATUS_LABELS = {"working": "在岗", "leave": "请假", "vacation": "休假", "trip": "出差"}

logger = logging.getLogger("opengantt.services")

# 任务状态常量（与 schemas.TASK_STATUSES 一致）
STATUS_LABELS = {
    "not_started": "未开始",
    "in_progress": "进行中",
    "blocked": "阻塞",
    "paused": "暂停",
    "done": "已完成",
    "cancelled": "已取消",
}
RISK_LABELS = {"ok": "正常", "watch": "关注", "stall": "停滞"}

# 停滞判定阈值（工作日按自然日简化，如需调整改这里）
STALL_DAYS = 3          # 进度连续 N 天无变化 → 停滞
OVERDUE_STALL_DAYS = 3  # 逾期超过 N 天 → 停滞
NOTE_GAP_DAYS = 3       # 连续 N 天未填写说明 → 关注
PLAN_DEV_THRESHOLD = -20  # 实际落后期望进度（百分点）→ 关注


def _today_str() -> str:
    return dt.date.today().isoformat()


# ---------- 通用 ----------


def _parse_deps(dependencies: str) -> list[int]:
    return [int(x) for x in dependencies.split(",") if x.strip()]


def _validate_date_order(start: str, end: str) -> None:
    from datetime import date as _date

    if _date.fromisoformat(start) > _date.fromisoformat(end):
        raise ValidationError("开始日期不能晚于结束日期")


def _assert_no_cycle(db: Session, project_id: int, task_id: int, new_deps_by_id: dict[int, list[int]]) -> None:
    """DFS 检测依赖环：new_deps_by_id 为本次变更后受影响任务的依赖表。"""
    visited: set[int] = set()
    stack = list(new_deps_by_id.get(task_id, []))
    while stack:
        current = stack.pop()
        if current == task_id:
            raise DependencyCycleError(f"依赖关系形成环：任务 {task_id} 不能直接或间接依赖自己")
        if current in visited:
            continue
        visited.add(current)
        dep_task = db.get(Task, current)
        if dep_task is None:
            continue
        deps = new_deps_by_id.get(current)
        if deps is None:
            deps = _parse_deps(dep_task.dependencies)
        stack.extend(deps)


def get_project(db: Session, project_id: int) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise NotFoundError(f"项目 {project_id} 不存在")
    return project


def _resolve_task(db: Session, project_id: int, task_id: int) -> Task:
    task = db.get(Task, task_id)
    if task is None or task.project_id != project_id:
        raise NotFoundError(f"任务 {task_id} 不存在")
    return task


# ---------- 权限 ----------


def _user_dept_ids(db: Session, user: User) -> set[int]:
    """用户所属的全部部门 ID（主部门 + 多部门关联）。"""
    ids = set(
        db.execute(
            select(UserDepartment.department_id).where(UserDepartment.user_id == user.id)
        ).scalars()
    )
    if user.department_id is not None:
        ids.add(user.department_id)
    return ids


def _user_dept_names(db: Session, user: User) -> list[str]:
    """全部所属部门名（主部门在前）。"""
    names: list[str] = []
    if user.department is not None:
        names.append(user.department.name)
    for d in db.execute(
        select(Department)
        .join(UserDepartment, UserDepartment.department_id == Department.id)
        .where(UserDepartment.user_id == user.id, Department.id != user.department_id)
        .order_by(Department.id)
    ).scalars():
        names.append(d.name)
    return names


def _visible_project_ids(db: Session, user: User) -> set[int] | None:
    """员工可见的项目 ID 集合（本人负责的项目 + 名下任务关联的项目）；
    主管/管理员返回 None = 全局可见。"""
    if user.role in ("admin", "supervisor"):
        return None
    ids = set(
        db.execute(select(Project.id).where(Project.owner_id == user.id)).scalars()
    )
    task_ids = set(
        db.execute(select(TaskAssignee.task_id).where(TaskAssignee.user_id == user.id)).scalars()
    )
    if task_ids:
        ids.update(
            db.execute(select(Task.project_id).where(Task.id.in_(task_ids))).scalars()
        )
    return ids


def can_view_project(db: Session, user: User, project: Project) -> bool:
    """查看权限：主管/管理员全局可见；员工仅可见与自己关联（负责或名下有任务）的项目。"""
    ids = _visible_project_ids(db, user)
    return ids is None or project.id in ids


def ensure_can_view_project(db: Session, user: User, project: Project) -> None:
    if not can_view_project(db, user, project):
        # 用 404 而非 403，避免向无权用户暴露项目存在性
        raise NotFoundError("项目不存在")


def can_edit_project(db: Session, user: User, project: Project) -> bool:
    """编辑权限：管理员全部；所属（任一）部门成员可编辑本部门项目；项目负责人可编辑自己的项目。"""
    if user.role == "admin":
        return True
    if project.department_id is not None and project.department_id in _user_dept_ids(db, user):
        return True
    return project.owner_id == user.id


def ensure_can_edit_project(db: Session, user: User, project: Project) -> None:
    ensure_can_view_project(db, user, project)
    if not can_edit_project(db, user, project):
        raise PermissionDeniedError("您没有修改该项目的权限（仅限本部门成员编辑本部门项目，或项目负责人）")


def can_edit_task(db: Session, user: User, task: Task, project: Project) -> bool:
    """任务级权限：项目可编辑者可改全部任务；任务负责人可改自己名下的任务（跨部门亦然）。"""
    if can_edit_project(db, user, project):
        return True
    return (
        db.execute(
            select(TaskAssignee.id).where(
                TaskAssignee.task_id == task.id, TaskAssignee.user_id == user.id
            )
        ).scalar_one_or_none()
        is not None
    )


def ensure_can_edit_task(db: Session, user: User, task: Task, project: Project) -> None:
    if not can_edit_task(db, user, task, project):
        raise PermissionDeniedError(
            "您没有修改该任务的权限（限本部门成员、项目负责人或任务负责人）"
        )


# ---------- 项目 ----------


def _project_out(db: Session, project: Project, user: User, task_count: int | None = None) -> dict:
    owner = project.owner
    department = project.department
    owner_name = (owner.display_name or owner.username) if owner is not None else ""
    return {
        "id": project.id,
        "name": project.name,
        "description": project.description,
        "priority": project.priority or "medium",
        "priority_label": PRIORITY_LABELS.get(project.priority or "medium", "中"),
        "task_count": task_count if task_count is not None else len(project.tasks),
        "owner_id": project.owner_id,
        "owner_name": owner_name,
        "department_id": project.department_id,
        "department_name": department.name if department is not None else "",
        "can_edit": can_edit_project(db, user, project),
    }


def list_projects(db: Session, user: User) -> list[dict]:
    counts = dict(
        db.execute(select(Task.project_id, func.count(Task.id)).group_by(Task.project_id)).all()
    )
    visible = _visible_project_ids(db, user)
    projects = db.execute(select(Project).order_by(Project.id)).scalars().all()
    if visible is not None:
        projects = [p for p in projects if p.id in visible]
    return [_project_out(db, p, user, counts.get(p.id, 0)) for p in projects]


def create_project(db: Session, user: User, payload: ProjectCreate) -> dict:
    if user.role == "admin":
        department_id = payload.department_id or user.department_id
        owner_id = payload.owner_id or user.id
    else:
        # 员工/主管：可在自己所属的任一部门创建项目（多部门用户不再被锁死在主部门）；
        # 未指定时默认主部门；负责人为本人
        if payload.department_id:
            if payload.department_id not in _user_dept_ids(db, user):
                raise PermissionDeniedError("只能在自己所属的部门下创建项目")
            department_id = payload.department_id
        else:
            department_id = user.department_id
        owner_id = user.id
    project = Project(
        name=payload.name,
        description=payload.description,
        priority=payload.priority,
        owner_id=owner_id,
        department_id=department_id,
    )
    db.add(project)
    db.commit()
    return _project_out(db, project, user, 0)


def update_project(db: Session, user: User, project_id: int, payload: ProjectUpdate) -> dict:
    project = get_project(db, project_id)
    ensure_can_edit_project(db, user, project)
    if payload.name is not None:
        project.name = payload.name
    if payload.description is not None:
        project.description = payload.description
    if payload.priority is not None:
        project.priority = payload.priority
    if user.role == "admin":
        if payload.owner_id is not None:
            project.owner_id = payload.owner_id
        if payload.department_id is not None:
            project.department_id = payload.department_id
        # expire_on_commit=False：改部门/负责人后显式刷新，避免返回缓存的旧关联
        db.refresh(project)
    db.commit()
    return _project_out(db, project, user)


def restore_due_work_status(db: Session, now: dt.datetime | None = None) -> list[str]:
    """把预计结束时间已到的请假/休假/出差状态自动恢复为在岗（幂等，可重复调用）。

    返回被恢复的用户显示名列表；无到期人员时返回空列表。
    由后台线程每分钟调用；也用于测试与手动触发。
    """
    now = now or dt.datetime.now()
    rows = db.execute(
        select(User).where(
            User.is_active,
            User.work_status != "working",
            User.work_status_until.is_not(None),
            User.work_status_until <= now,
        )
    ).scalars().all()
    restored: list[str] = []
    for u in rows:
        old = WORK_STATUS_LABELS.get(u.work_status or "working", u.work_status)
        u.work_status = "working"
        u.work_status_until = None
        restored.append(u.display_name or u.username)
        record_audit(
            db, None, "work_status_auto_restore",
            object_type="user", object_id=u.id, object_name=u.display_name or u.username,
            detail=f"{old}结束（预计恢复时间已到），自动恢复为在岗",
        )
    if restored:
        db.commit()
        logger.info("工作状态自动恢复：%d 人（%s）", len(restored), "、".join(restored))
    return restored


def migrate_project(db: Session, user: User, project_id: int, target_department_id: int) -> dict:
    """项目迁移：将项目整体迁移到目标部门。

    权限规则：
    - 管理员：任意项目 → 任意部门；
    - 主管：有编辑权的项目（本部门项目或自己创建的）→ 任意部门；
    - 普通员工：仅自己创建的项目（owner_id == 本人）→ 本人所属的部门。

    数据关联：任务、任务负责人、进度日志、文档均挂在项目 ID 下，随项目整体迁移，
    无需任何变更；创建人（owner）保持不变。可见性影响：迁移后原部门中与该项目
    无关联（非负责人、名下无任务、非多部门归属）的成员将不再可见该项目。
    """
    project = get_project(db, project_id)
    ensure_can_view_project(db, user, project)
    dept = db.get(Department, target_department_id)
    if dept is None:
        raise NotFoundError("目标部门不存在")
    if dept.id == project.department_id:
        raise ValidationError("项目已属于该部门，无需迁移")

    if user.role == "admin":
        pass  # 任意项目 → 任意部门
    elif user.role == "supervisor":
        if not can_edit_project(db, user, project):
            raise PermissionDeniedError("您没有迁移该项目的权限（仅限本部门项目或自己创建的项目）")
    else:  # employee
        if project.owner_id != user.id:
            raise PermissionDeniedError("普通员工只能迁移自己创建的项目")
        if target_department_id not in _user_dept_ids(db, user):
            raise PermissionDeniedError("只能将项目迁移到自己所属的部门")

    old_name = project.department.name if project.department else "未设置部门"
    project.department_id = target_department_id
    db.commit()
    db.refresh(project)  # expire_on_commit=False：显式刷新，确保返回新部门而非缓存
    logger.info(
        "项目迁移：%s（#%d）由 %s 迁移到 %s，操作人 %s",
        project.name, project.id, old_name, dept.name, user.username,
    )
    return _project_out(db, project, user)


def delete_project(db: Session, user: User, project_id: int) -> None:
    project = get_project(db, project_id)
    if user.role != "admin" and project.owner_id != user.id:
        raise PermissionDeniedError("只有管理员或项目负责人可以删除项目")
    db.delete(project)
    db.commit()


# ---------- 任务 ----------


def list_tasks(db: Session, project_id: int) -> list[Task]:
    get_project(db, project_id)
    return list(
        db.execute(
            select(Task).where(Task.project_id == project_id).order_by(Task.position, Task.id)
        ).scalars()
    )


def next_position(db: Session, project_id: int) -> int:
    result = db.execute(
        select(func.max(Task.position)).where(Task.project_id == project_id)
    ).scalar()
    return (result + 1) if result is not None else 0


def _validate_dependencies(db: Session, project_id: int, dependencies: str, exclude_id: int | None = None) -> None:
    for dep_id in _parse_deps(dependencies):
        if dep_id == exclude_id:
            raise ValidationError("任务不能依赖自己")
        dep_task = db.get(Task, dep_id)
        if dep_task is None or dep_task.project_id != project_id:
            raise ValidationError(f"依赖的任务 {dep_id} 不存在或不属于当前项目")


def _ensure_assignee_dept_scope(db: Session, operator: User, assignee_ids: list[int] | None) -> None:
    """负责人选择分级权限（后端强制）：
    - 普通用户（employee）：只能选择本部门（自己所属任一部门）成员担任负责人；
    - 主管（supervisor）/管理员（admin）：不限部门，可跨部门指派。
    """
    if operator is None or operator.role != "employee" or not assignee_ids:
        return
    my_depts = _user_dept_ids(db, operator)
    if not my_depts:
        return  # 未分配部门的员工不做限制（避免无法指派任何人的死锁）
    for uid in dict.fromkeys(assignee_ids or []):
        if not uid:
            continue
        target = db.get(User, uid)
        if target is None:
            raise ValidationError(f"负责人账号 {uid} 不存在")
        if not (_user_dept_ids(db, target) & my_depts):
            display = target.display_name or target.username
            raise ValidationError(f"普通用户只能选择本部门成员担任负责人（{display} 不在你所属的部门内）")


def _apply_assignees(db: Session, task: Task, assignee_ids: list[int] | None, operator: User | None = None) -> None:
    """整体替换任务负责人集合（多选）：
    - 校验账号存在；写入 task_assignees 关联
    - tasks.assignee 同步为全部负责人姓名（顿号拼接，供展示/导出/搜索）
    - tasks.assignee_id 保留为首负责人（主负责人，历史兼容字段）
    - 空列表 = 清除全部负责人
    """
    ids = [i for i in dict.fromkeys(assignee_ids or []) if i]
    _ensure_assignee_dept_scope(db, operator, ids)
    cur_assignees = (
        db.execute(select(TaskAssignee).where(TaskAssignee.task_id == task.id)).scalars().all()
    )
    for row in cur_assignees:
        db.delete(row)
    db.flush()  # 先刷库删除旧行，避免 UNIQUE(task_id,user_id) 与新插入冲突
    names: list[str] = []
    for uid in ids:
        target = db.get(User, uid)
        if target is None:
            raise ValidationError(f"负责人账号 {uid} 不存在")
        db.add(TaskAssignee(task_id=task.id, user_id=uid))
        names.append(target.display_name or target.username)
    task.assignee = "、".join(names)
    task.assignee_id = ids[0] if ids else None


def create_task(db: Session, user: User, project_id: int, payload: TaskCreate) -> Task:
    project = get_project(db, project_id)
    ensure_can_edit_project(db, user, project)
    _validate_date_order(payload.start_date, payload.end_date)
    _validate_dependencies(db, project_id, payload.dependencies)
    task = Task(
        project_id=project_id,
        name=payload.name,
        start_date=payload.start_date,
        end_date=payload.end_date,
        progress=payload.progress,
        dependencies=payload.dependencies,
        status=payload.status,
        position=next_position(db, project_id),
    )
    db.add(task)
    db.flush()  # 取得 task.id，负责人关联表需要
    if payload.assignee_ids:
        _apply_assignees(db, task, payload.assignee_ids, operator=user)
    db.commit()
    return task


def apply_task_update(
    db: Session,
    task: Task,
    change: TaskUpdate,
    pending_deps: dict[int, list[int]],
    operator: User | None = None,
) -> None:
    if change.dependencies is not None:
        _validate_dependencies(db, task.project_id, change.dependencies, exclude_id=task.id)
        task.dependencies = change.dependencies
        pending_deps[task.id] = _parse_deps(change.dependencies)
    if change.name is not None:
        task.name = change.name
    if change.start_date is not None:
        task.start_date = change.start_date
    if change.end_date is not None:
        task.end_date = change.end_date
    if change.progress is not None:
        task.progress = change.progress
    if change.assignee_ids is not None:
        # 整体替换负责人集合（多选）；空列表 = 清除全部
        _apply_assignees(db, task, change.assignee_ids, operator=operator)
    if change.position is not None:
        task.position = change.position


def _apply_status_change(db: Session, user: User, task: Task, old_status: str, change: TaskUpdate) -> None:
    """状态流转：blocked 必须填原因；每次变更写入审计日志。"""
    new_status = change.status
    if new_status not in ("not_started", "in_progress", "blocked", "paused", "done", "cancelled"):
        raise ValidationError(f"未知状态：{new_status}")
    if new_status == "blocked" and not (change.status_reason or change.note):
        raise ValidationError("转为阻塞状态必须填写原因（状态原因或进度说明）")
    task.status = new_status
    db.add(
        TaskStatusLog(
            task_id=task.id,
            user_id=user.id,
            from_status=old_status,
            to_status=new_status,
            reason=(change.status_reason or change.note or "")[:500],
        )
    )


def update_task(db: Session, user: User, project_id: int, task_id: int, payload: TaskUpdate) -> Task:
    project = get_project(db, project_id)
    task = _resolve_task(db, project_id, task_id)
    ensure_can_view_project(db, user, project)
    ensure_can_edit_task(db, user, task, project)
    _validate_date_order(payload.start_date or task.start_date, payload.end_date or task.end_date)
    old_status = task.status
    pending: dict[int, list[int]] = {}
    apply_task_update(db, task, payload, pending, operator=user)
    if payload.status is not None and payload.status != old_status:
        _apply_status_change(db, user, task, old_status, payload)
    if payload.dependencies is not None:
        _assert_no_cycle(db, project_id, task_id, pending)
    db.flush()
    # 进度或说明变更 → 自动记录当日进度快照（每天每任务一条，人工说明优先保留）
    if payload.progress is not None or payload.note is not None:
        journal_progress(db, user, task, note=payload.note)
    db.commit()
    return task


def bulk_update_tasks(db: Session, user: User, project_id: int, changes: dict[int, TaskUpdate]) -> list[Task]:
    """批量更新：单事务原子写入，逐任务鉴权（负责人只能改自己的任务），统一做环检测。"""
    project = get_project(db, project_id)
    tasks = {tid: _resolve_task(db, project_id, tid) for tid in changes}
    for task_id, task in tasks.items():
        ensure_can_edit_task(db, user, task, project)
    pending: dict[int, list[int]] = {}
    for task_id, change in changes.items():
        start = change.start_date or tasks[task_id].start_date
        end = change.end_date or tasks[task_id].end_date
        _validate_date_order(start, end)
        apply_task_update(db, tasks[task_id], change, pending, operator=user)
    for task_id in changes:
        _assert_no_cycle(db, project_id, task_id, pending)
    db.flush()
    for task_id, change in changes.items():
        task = tasks[task_id]
        if change.status is not None and change.status != task.status:
            _apply_status_change(db, user, task, task.status, change)
        if change.progress is not None or change.note is not None:
            journal_progress(db, user, task, note=change.note)
    db.commit()
    return list(tasks.values())


def delete_task(db: Session, user: User, project_id: int, task_id: int) -> None:
    project = get_project(db, project_id)
    ensure_can_edit_project(db, user, project)
    task = _resolve_task(db, project_id, task_id)
    db.delete(task)
    db.commit()


# ---------- 进度文档 ----------


# 文档部门可见性专项授权：源部门 → 可查看其文档的部门（按部门名配置，改名需同步此处）
DOC_DEPT_GRANTS = {"商务运营部": ["项管中心"]}


def _doc_visible_dept_ids(db: Session, user: User) -> set[int] | None:
    """可查看文档的部门 ID 集合；管理员返回 None = 全部部门。
    规则：普通用户（含主管）可见其所属（任一）部门 + 专项授权部门
    （如商务运营部可看项管中心）。"""
    if user.role == "admin":
        return None
    allowed = _user_dept_ids(db, user)
    dept_names = {d.name for d in db.execute(
        select(Department)
        .join(UserDepartment, UserDepartment.department_id == Department.id)
        .where(UserDepartment.user_id == user.id)
    ).scalars()}
    if user.department is not None and user.department.name:
        dept_names.add(user.department.name)
    for src, targets in DOC_DEPT_GRANTS.items():
        if src in dept_names:
            for name in targets:
                d = db.execute(
                    select(Department).where(Department.name == name)
                ).scalar_one_or_none()
                if d is not None:
                    allowed.add(d.id)
    return allowed


def _can_view_document(db: Session, user: User, doc: Document) -> bool:
    allowed = _doc_visible_dept_ids(db, user)
    if allowed is None:
        return True
    project = db.get(Project, doc.project_id)
    if project is None:
        return False
    # 未分部门项目的文档（department_id 为空按 -1 处理）仅管理员可见
    return (project.department_id if project.department_id is not None else -1) in allowed


def list_documents(db: Session, user: User, project_id: int) -> list[dict]:
    project = get_project(db, project_id)
    ensure_can_view_project(db, user, project)
    allowed = _doc_visible_dept_ids(db, user)
    if allowed is not None and (project.department_id or -1) not in allowed:
        # 文档按部门可见：非授权部门的项目文档一律不可见（返回空列表）
        return []
    docs = db.execute(
        select(Document).where(Document.project_id == project_id).order_by(Document.id.desc())
    ).scalars().all()
    return [
        {
            "id": d.id,
            "project_id": d.project_id,
            "original_name": d.original_name,
            "size": d.size,
            "content_type": d.content_type,
            "note": d.note,
            # 存储为 UTC；显式携带 Z 后缀，前端 new Date 解析后自动转为本地时区
            "uploaded_at": d.uploaded_at.isoformat(timespec="seconds") + "Z",
            "uploader_name": (d.uploader.display_name or d.uploader.username) if d.uploader else "",
        }
        for d in docs
    ]


def save_document(db: Session, user: User, project_id: int, original_name: str, content: bytes, content_type: str, note: str) -> Document:
    project = get_project(db, project_id)
    ensure_can_edit_project(db, user, project)
    max_bytes = settings.MAX_UPLOAD_MB * 1024 * 1024
    if len(content) > max_bytes:
        raise ValidationError(f"文件超过大小限制（最大 {settings.MAX_UPLOAD_MB} MB）")
    stored_name = f"{secrets.token_hex(12)}{Path(original_name).suffix[:20]}" if Path(original_name).suffix else secrets.token_hex(16)
    path = settings.UPLOAD_DIR / stored_name
    path.write_bytes(content)
    doc = Document(
        project_id=project_id,
        uploader_id=user.id,
        original_name=original_name[:255],
        stored_name=stored_name,
        size=len(content),
        content_type=(content_type or "")[:120],
        note=note[:200],
    )
    db.add(doc)
    db.commit()
    return doc


def get_document_file(db: Session, document_id: int) -> Document:
    doc = db.get(Document, document_id)
    if doc is None:
        raise NotFoundError("文档不存在或已被删除")
    return doc


def delete_document(db: Session, user: User, document_id: int) -> None:
    doc = db.get(Document, document_id)
    if doc is None:
        raise NotFoundError("文档不存在或已被删除")
    project = get_project(db, doc.project_id)
    if not (user.role == "admin" or doc.uploader_id == user.id or can_edit_project(db, user, project)):
        raise PermissionDeniedError("没有删除该文档的权限")
    path = settings.UPLOAD_DIR / doc.stored_name
    if path.is_file():
        path.unlink(missing_ok=True)
    db.delete(doc)
    db.commit()


# ---------- 每日任务（周期清单，日期恒为当天；可分配多名成员） ----------


def _daily_task_item(task: DailyTask, user: User, today: str, rows: list[DailyTaskAssignee]) -> dict:
    assignees = [
        {
            "user_id": r.user_id,
            "name": (r.user.display_name or r.user.username) if r.user else f"用户#{r.user_id}",
            "done_today": (r.done_date or "") == today,
            "is_me": r.user_id == user.id,
        }
        # 说明按人独立（r.note 仅自己可见），不在负责人列表中下发他人内容
        for r in rows
    ]
    mine = next((a for a in rows if a.user_id == user.id), None)
    is_creator = user.id == task.user_id
    return {
        "id": task.id,
        "name": task.name,
        # "说明"= 本人自己的内容进度说明（互不可见他人内容）
        "note": (mine.note or "") if mine else "",
        "date": today,
        "created_by_name": (task.user.display_name or task.user.username) if task.user else "",
        # 负责人与创建人同等管理权（编辑内容/负责人/删除）
        "can_manage": is_creator or user.role == "admin" or mine is not None,
        "can_delete": is_creator or user.role == "admin" or mine is not None,
        "assignees": assignees,
        "done_today": bool(assignees and any(a["is_me"] and a["done_today"] for a in assignees)),
    }


def _task_assignee_rows(db: Session, task_id: int) -> list[DailyTaskAssignee]:
    return list(
        db.execute(
            select(DailyTaskAssignee)
            .where(DailyTaskAssignee.daily_task_id == task_id)
            .order_by(DailyTaskAssignee.id)
        ).scalars()
    )


def _apply_daily_assignees(
    db: Session, task: DailyTask, assignee_ids: list[int], operator: User | None = None
) -> None:
    """整体替换负责人集合（交互与任务清单一致）；沿用保留成员的当日完成状态与本人说明。"""
    _ensure_assignee_dept_scope(db, operator, assignee_ids)
    old = {
        r.user_id: (r.done_date or "", r.note or "")
        for r in db.execute(
            select(DailyTaskAssignee).where(DailyTaskAssignee.daily_task_id == task.id)
        ).scalars()
    }
    for r in _task_assignee_rows(db, task.id):
        db.delete(r)
    db.flush()
    for uid in dict.fromkeys(assignee_ids or []):
        if not uid:
            continue
        if db.get(User, uid) is None:
            raise ValidationError(f"负责人账号 {uid} 不存在")
        prev = old.get(uid, ("", ""))
        db.add(
            DailyTaskAssignee(daily_task_id=task.id, user_id=uid, done_date=prev[0], note=prev[1])
        )
    db.flush()


def list_daily_tasks(db: Session, user: User) -> list[dict]:
    """与我相关的每日任务（我创建的或分配给我的），日期恒为当天。"""
    today = _today_str()
    tasks = db.execute(
        select(DailyTask)
        .outerjoin(DailyTaskAssignee, DailyTaskAssignee.daily_task_id == DailyTask.id)
        .where(or_(DailyTask.user_id == user.id, DailyTaskAssignee.user_id == user.id))
        .order_by(DailyTask.id)
        .distinct()
    ).scalars().all()
    return [_daily_task_item(t, user, today, _task_assignee_rows(db, t.id)) for t in tasks]


def create_daily_task(db: Session, user: User, payload: DailyTaskCreate) -> dict:
    _ensure_assignee_dept_scope(db, user, payload.assignee_ids)  # 分级权限：员工限本部门
    task = DailyTask(user_id=user.id, name=payload.name.strip())
    db.add(task)
    db.flush()  # 先取 id 再写负责人关联
    ids = list(dict.fromkeys([*payload.assignee_ids, user.id]))  # 创建人始终在负责人内
    for uid in ids:
        if uid and db.get(User, uid) is None:
            raise ValidationError(f"负责人账号 {uid} 不存在")
    for uid in ids:
        if uid:
            # 创建时填写的内容进度说明归属创建人本人（说明按人独立）
            db.add(
                DailyTaskAssignee(
                    daily_task_id=task.id,
                    user_id=uid,
                    note=payload.note.strip()[:500] if uid == user.id else "",
                )
            )
    db.commit()
    today = _today_str()
    return _daily_task_item(task, user, today, _task_assignee_rows(db, task.id))


def update_daily_task(db: Session, user: User, task_id: int, payload: DailyTaskUpdate) -> dict:
    task = db.get(DailyTask, task_id)
    if task is None:
        raise NotFoundError("每日任务不存在")
    today = _today_str()
    member_ids = {r.user_id for r in _task_assignee_rows(db, task.id)}
    can_manage = user.id == task.user_id or user.role == "admin" or user.id in member_ids
    if (payload.name is not None or payload.assignee_ids is not None) and not can_manage:
        raise PermissionDeniedError("只有任务负责人或管理员可以修改任务内容与负责人")
    if payload.note is not None:
        # 说明按人独立：只能写本人的说明（负责人各填各的，互不影响、互不可见）
        row = db.execute(
            select(DailyTaskAssignee).where(
                DailyTaskAssignee.daily_task_id == task.id, DailyTaskAssignee.user_id == user.id
            )
        ).scalar_one_or_none()
        if row is None:
            raise ValidationError("仅任务负责人可填写自己的内容进度说明")
        row.note = payload.note.strip()[:500]
    if payload.name is not None:
        task.name = payload.name.strip()
    if payload.assignee_ids is not None:
        _apply_daily_assignees(db, task, payload.assignee_ids, operator=user)
    if payload.done_today is not None:
        # 完成状态按人按天记录：勾选写当天日期，跨天自动回到未完成
        row = db.execute(
            select(DailyTaskAssignee).where(
                DailyTaskAssignee.daily_task_id == task.id, DailyTaskAssignee.user_id == user.id
            )
        ).scalar_one_or_none()
        if payload.done_today:
            if row is None:
                row = DailyTaskAssignee(daily_task_id=task.id, user_id=user.id)
                db.add(row)
            row.done_date = today
        elif row is not None:
            row.done_date = ""
    db.commit()
    return _daily_task_item(task, user, today, _task_assignee_rows(db, task.id))


def delete_daily_task(db: Session, user: User, task_id: int) -> None:
    task = db.get(DailyTask, task_id)
    if task is None:
        raise NotFoundError("每日任务不存在")
    member_ids = {r.user_id for r in _task_assignee_rows(db, task.id)}
    if not (user.id == task.user_id or user.role == "admin" or user.id in member_ids):
        raise PermissionDeniedError("只有任务负责人或管理员可以删除每日任务")
    for r in _task_assignee_rows(db, task.id):
        db.delete(r)
    db.delete(task)
    db.commit()


# ---------- 项目进度文档树（部门 → 员工 → 文档） ----------


def list_document_tree(db: Session, user: User) -> list[dict]:
    """按 部门 → 员工 → 文档 组织进度文档（登录用户可读，删除权限随条目下发）。
    文档按部门可见：普通用户仅本部门 + 专项授权部门；管理员全部。"""
    allowed = _doc_visible_dept_ids(db, user)
    docs = db.execute(
        select(Document, Project)
        .join(Project, Document.project_id == Project.id)
        .order_by(Project.department_id, Document.uploader_id, Document.id.desc())
    ).all()
    by_dept_uploader: dict[int, dict[int, list[dict]]] = {}
    loose: dict[int, list[dict]] = {}  # 上传者已删除的文档归入“历史账号”桶
    for doc, project in docs:
        dept_id = project.department_id if project.department_id is not None else -1
        if allowed is not None and dept_id not in allowed:
            continue
        entry = {
            "id": doc.id,
            "original_name": doc.original_name,
            "size": doc.size,
            "note": doc.note,
            # UTC 存储；带 Z 后缀由前端转本地时区
            "uploaded_at": doc.uploaded_at.isoformat(timespec="seconds") + "Z",
            "project_id": doc.project_id,
            "project_name": project.name,
            "uploader_id": doc.uploader_id,
            "uploader_name": (doc.uploader.display_name or doc.uploader.username) if doc.uploader else "",
            "can_delete": user.role == "admin" or doc.uploader_id == user.id or can_edit_project(db, user, project),
        }
        if doc.uploader_id:
            by_dept_uploader.setdefault(dept_id, {}).setdefault(doc.uploader_id, []).append(entry)
        else:
            loose.setdefault(dept_id, []).append(entry)

    tree: list[dict] = []
    for dept in db.execute(select(Department).order_by(Department.id)).scalars():
        if allowed is not None and dept.id not in allowed:
            continue  # 非授权部门的节点整体隐藏
        uploader_map = by_dept_uploader.get(dept.id, {})
        members: list[dict] = []
        seen: set[int] = set()
        for m in db.execute(
            select(User).where(User.department_id == dept.id, User.is_active).order_by(User.id)
        ).scalars():
            seen.add(m.id)
            members.append({
                "user_id": m.id,
                "name": m.display_name or m.username,
                "documents": uploader_map.get(m.id, []),
            })
        for uid, member_docs in uploader_map.items():
            if uid not in seen:  # 已停用/删除账号仍要能看到其历史文档
                members.append({
                    "user_id": uid,
                    "name": member_docs[0]["uploader_name"] or f"用户#{uid}",
                    "documents": member_docs,
                })
        if loose.get(dept.id):
            members.append({"user_id": None, "name": "历史账号", "documents": loose[dept.id]})
        tree.append({
            "department_id": dept.id,
            "department_name": dept.name,
            "members": members,
        })

    if -1 in by_dept_uploader or -1 in loose:  # 未分部门项目的文档（仅管理员可见）
        members = [
            {"user_id": uid, "name": d[0]["uploader_name"] or f"用户#{uid}", "documents": d}
            for uid, d in by_dept_uploader.get(-1, {}).items()
        ]
        if loose.get(-1):
            members.append({"user_id": None, "name": "历史账号", "documents": loose[-1]})
        tree.append({"department_id": -1, "department_name": "未分部门", "members": members})
    return tree


# ---------- 部门概览（全员可读，用于主页与部门页） ----------


def list_departments_overview(db: Session, user: User) -> list[dict]:
    """部门列表及统计：账号数 / 项目数 / 任务数（员工仅统计其可见项目）。"""
    visible = _visible_project_ids(db, user)
    result = []
    for d in db.execute(select(Department).order_by(Department.id)).scalars():
        # 一人多部门：主部门或关联部门均计入该部门人数（distinct 防重复）
        user_count = db.execute(
            select(func.count(func.distinct(User.id)))
            .select_from(User)
            .outerjoin(UserDepartment, UserDepartment.user_id == User.id)
            .where(or_(User.department_id == d.id, UserDepartment.department_id == d.id))
        ).scalar() or 0
        if visible is None:
            project_count = db.execute(
                select(func.count(Project.id)).where(Project.department_id == d.id)
            ).scalar() or 0
            task_count = (
                db.execute(
                    select(func.count(Task.id))
                    .select_from(Task)
                    .join(Project, Task.project_id == Project.id)
                    .where(Project.department_id == d.id)
                ).scalar()
                or 0
            )
        else:
            project_count = db.execute(
                select(func.count(Project.id)).where(
                    Project.department_id == d.id, Project.id.in_(visible)
                )
            ).scalar() or 0
            task_count = (
                db.execute(
                    select(func.count(Task.id))
                    .select_from(Task)
                    .join(Project, Task.project_id == Project.id)
                    .where(Project.department_id == d.id, Project.id.in_(visible))
                ).scalar()
                or 0
            )
        result.append(
            {
                "id": d.id,
                "name": d.name,
                "description": d.description,
                "user_count": user_count,
                "project_count": project_count,
                "task_count": task_count,
            }
        )
    return result


# ---------- 进度快照与每日工作日志 ----------


def journal_progress(db: Session, user: User, task: Task, note: str | None = None, log_date: str | None = None) -> ProgressLog:
    """记录/更新某任务在指定日期的进度快照（每天每任务一条）。

    - 已有条目：更新 progress 与记录人；note 仅在显式提供时覆盖
    - 无条目：新建，note 为空表示纯自动保存
    - 进度说明按人独立写入 task_notes（每任务每人每天一条，互不覆盖）；
      progress_logs.note 保留为"最后记录人说明"缓存，供进度记录页/风险计算展示
    """
    day = log_date or _today_str()
    log = db.execute(
        select(ProgressLog).where(ProgressLog.task_id == task.id, ProgressLog.log_date == day)
    ).scalar_one_or_none()
    if log is None:
        log = ProgressLog(task_id=task.id, log_date=day, progress=task.progress, note=note or "", user_id=user.id)
        db.add(log)
    else:
        log.progress = task.progress
        log.user_id = user.id
        if note is not None:
            log.note = note[:500]
    if note is not None:
        row = db.execute(
            select(TaskNote).where(
                TaskNote.task_id == task.id, TaskNote.user_id == user.id, TaskNote.log_date == day
            )
        ).scalar_one_or_none()
        if row is None:
            db.add(TaskNote(task_id=task.id, user_id=user.id, log_date=day, note=note[:500]))
        else:
            row.note = note[:500]
    # autoflush=False 的会话中保证快照/说明立即可见（幂等，调用方随后的 commit 不受影响）
    db.flush()
    return log


def snapshot_all_for_today(db: Session) -> int:
    """每日自动保存：为未完成任务补全当日进度快照（只补缺失行，不覆盖人工说明）。

    已完成/已取消的任务不再生成快照——避免"前几天完成的任务每天重复出现在后续日志"。
    任务当天完成时，其进度更新本身会产生当天记录，当日日志仍能看到它。
    """
    day = _today_str()
    existing = set(
        db.execute(select(ProgressLog.task_id).where(ProgressLog.log_date == day)).scalars()
    )
    count = 0
    for task in db.execute(select(Task)).scalars():
        if task.id in existing:
            continue
        if task.progress >= 100 or (task.status or "") in ("done", "cancelled"):
            continue
        db.add(
            ProgressLog(
                task_id=task.id,
                log_date=day,
                progress=task.progress,
                note="",
                user_id=task.assignee_id,
            )
        )
        count += 1
    if count:
        db.commit()
    return count


def _assignee_ids_by_task(db: Session, project_id: int | None = None) -> dict[int, list[int]]:
    """任务 → 负责人 ID 列表映射（多选）。"""
    stmt = select(TaskAssignee.task_id, TaskAssignee.user_id)
    if project_id:
        stmt = stmt.join(Task, TaskAssignee.task_id == Task.id).where(Task.project_id == project_id)
    out: dict[int, list[int]] = {}
    for tid, uid in db.execute(stmt).all():
        out.setdefault(tid, []).append(uid)
    return out


def list_progress_logs(db: Session, project_id: int, log_date: str | None = None) -> list[dict]:
    """项目进度记录（按日期倒序，可按日过滤）。"""
    stmt = (
        select(ProgressLog, Task, User)
        .join(Task, ProgressLog.task_id == Task.id)
        .outerjoin(User, ProgressLog.user_id == User.id)
        .where(Task.project_id == project_id)
        .order_by(ProgressLog.log_date.desc(), Task.position, ProgressLog.task_id)
    )
    if log_date:
        stmt = stmt.where(ProgressLog.log_date == log_date)
    rows = db.execute(stmt).all()
    return [
        {
            "id": log.id,
            "task_id": task.id,
            "task_name": task.name,
            "log_date": log.log_date,
            "progress": log.progress,
            "note": log.note,
            # 任务负责人（当前分配的人）——与"记录人（操作人）"是两个概念
            "assignee": task.assignee or "未指定",
            "assignee_id": task.assignee_id,
            "user_name": (u.display_name or u.username) if u else "",
            "updated_at": log.updated_at.isoformat(timespec="seconds") + "Z",
        }
        for log, task, u in rows
    ]


def get_daily_decisions(db: Session, user_id: int, log_date: str) -> str:
    note = db.execute(
        select(DailyNote).where(DailyNote.user_id == user_id, DailyNote.log_date == log_date)
    ).scalar_one_or_none()
    return note.decisions if note else ""


def save_daily_decisions(db: Session, user: User, log_date: str, decisions: str) -> None:
    note = db.execute(
        select(DailyNote).where(DailyNote.user_id == user.id, DailyNote.log_date == log_date)
    ).scalar_one_or_none()
    if note is None:
        note = DailyNote(user_id=user.id, log_date=log_date, decisions=decisions[:1000])
        db.add(note)
    else:
        note.decisions = decisions[:1000]
    db.commit()


def get_daily_extras(db: Session, user_id: int, log_date: str) -> str:
    """当日补充条目（临时事项，每行一条）。"""
    note = db.execute(
        select(DailyNote).where(DailyNote.user_id == user_id, DailyNote.log_date == log_date)
    ).scalar_one_or_none()
    return (note.extras if note else "") or ""


def save_daily_extras(db: Session, user: User, log_date: str, extras: str) -> None:
    note = db.execute(
        select(DailyNote).where(DailyNote.user_id == user.id, DailyNote.log_date == log_date)
    ).scalar_one_or_none()
    if note is None:
        note = DailyNote(user_id=user.id, log_date=log_date, extras=extras[:2000])
        db.add(note)
    else:
        note.extras = extras[:2000]
    db.commit()


def _overdue_days(end_date: str, progress: int, log_date: str) -> int:
    """任务逾期天数：截止日已过且未完成；无截止日/已完成/日期非法返回 0。"""
    if progress >= 100 or not end_date:
        return 0
    try:
        end = dt.date.fromisoformat(end_date)
        ref = dt.date.fromisoformat(log_date)
    except ValueError:
        return 0
    return max(0, (ref - end).days)


def generate_daily_report(db: Session, user: User, log_date: str) -> str:
    """生成纯文本排版的工作日志：一今日完成/二进行中/三阻塞/四决策/五补充事项/六次日待办。"""
    year, month, day = (int(x) for x in log_date.split("-"))
    weekday = "一二三四五六日"[dt.date(year, month, day).weekday()]

    # 当日进度记录：本人更新的 + 本人是负责人（含多负责人）的任务，二者合并
    assigned_ids = select(TaskAssignee.task_id).where(TaskAssignee.user_id == user.id)
    logs = db.execute(
        select(ProgressLog, Task)
        .join(Task, ProgressLog.task_id == Task.id)
        .where(
            ProgressLog.log_date == log_date,
            or_(
                ProgressLog.user_id == user.id,
                Task.id.in_(assigned_ids),
                Task.assignee_id == user.id,  # 兼容未绑定账号的旧单负责人数据
            ),
        )
        .order_by(Task.position)
    ).all()

    done, doing, blocked, todo = [], [], [], []
    # 进度说明按人独立：本日志只展示"我"当天填写的内容进度说明（task_notes）
    my_notes = dict(
        db.execute(
            select(TaskNote.task_id, TaskNote.note).where(
                TaskNote.log_date == log_date, TaskNote.user_id == user.id
            )
        ).all()
    )
    for log, task in logs:
        label = f"{task.name} —— 进度 {log.progress}%"
        # 多行说明压平为单行（以；分隔），避免打断日志的行结构
        note = "；".join(s for s in (my_notes.get(task.id) or "").splitlines() if s.strip())
        if note:
            label += f"（{note}）"
        overdue = _overdue_days(task.end_date, log.progress, log_date)
        if overdue:
            label += f"，已逾期 {overdue} 天（截止 {task.end_date}）"
        if log.progress >= 100:
            done.append(f"✅ {label}")
        else:
            doing.append(f"🔄 {label}")
            todo.append(f"{len(todo) + 1}. {task.name} —— 当前进度 {log.progress}%")
            if overdue or any(k in note for k in ("阻塞", "卡", "等待", "协调")):
                blocked.append(f"⚠️ {label}")

    # 每日任务：当天勾选"今日完成"的自动计入工作日志（无需人工整理）；说明按人独立
    daily_done = db.execute(
        select(DailyTask, DailyTaskAssignee)
        .join(DailyTaskAssignee, DailyTaskAssignee.daily_task_id == DailyTask.id)
        .where(DailyTaskAssignee.user_id == user.id, DailyTaskAssignee.done_date == log_date)
        .order_by(DailyTask.id)
    ).all()
    for t, a in daily_done:
        # 内容进度说明随任务名一并写入日志（与项目任务行的"——"衔接格式一致）；只取本人说明
        note = (a.note or "").strip()
        done.append(f"✅ {t.name}（每日任务）" + (f" —— {note}" if note else ""))

    if not logs and not daily_done:
        doing.append("（当日无任务进度记录）")

    # 一人多部门：头部列出全部所属部门
    dept = "、".join(_user_dept_names(db, user))
    decisions = get_daily_decisions(db, user.id, log_date)
    if decisions:
        decision_lines = [f"· {line.strip()}" for line in decisions.splitlines() if line.strip()]
    else:
        decision_lines = ["（无。可在「我的工作日志」弹窗中填写当日关键决策）"]
    # 补充条目（临时事项）：员工自行填写，每行一条
    extras = get_daily_extras(db, user.id, log_date)
    if extras:
        extra_lines = [f"· {line.strip()}" for line in extras.splitlines() if line.strip()]
    else:
        extra_lines = ["（无。可在「我的工作日志」弹窗中记录当日临时事项）"]
    # 纯文本排版（无 Markdown 符号）：分隔线 + 编号章节，弹窗/导出/复制即读即用
    divider = "──────────────────────────────"
    lines = [
        f"工作日志 · {log_date}（星期{weekday}）",
        divider,
        f"{user.display_name or user.username}（{ROLE_LABELS.get(user.role, '')}{(' · ' + dept) if dept else ''}）· 每日任务进度",
        "（由 OpenGantt 依据任务进度每日快照自动生成）",
        "",
        "一、今日完成",
        *(done or ["（今日无完成任务）"]),
        "",
        "二、进行中",
        *(doing),
        "",
        "三、阻塞 / 需协调",
        *(blocked or ["（无。如有阻塞，请在任务进度说明中注明）"]),
        "",
        "四、关键决策",
        *decision_lines,
        "",
        "五、补充事项",
        *extra_lines,
        "",
        "六、次日待办（按优先级）",
        *(todo or ["1. （无未完成任务）"]),
        "",
        divider,
        f"💡 OpenGantt 自动生成于 {dt.datetime.now().strftime('%Y-%m-%d %H:%M')}，星期{weekday}",
    ]
    return "\n".join(lines)


def save_daily_reports_for_today(db: Session) -> int:
    """每日 17:30 自动归档：补全当日快照 + 为所有启用账号生成并保存当日工作日志。

    幂等：同日重复执行覆盖更新（保存时间刷新）。
    """
    snapshot_all_for_today(db)
    day = _today_str()
    count = 0
    users = db.execute(select(User).where(User.is_active)).scalars()
    for user in users:
        markdown = generate_daily_report(db, user, day)
        existing = db.execute(
            select(DailyReport).where(DailyReport.user_id == user.id, DailyReport.log_date == day)
        ).scalar_one_or_none()
        if existing:
            existing.markdown = markdown
            existing.saved_at = dt.datetime.now(dt.UTC).replace(tzinfo=None)
        else:
            db.add(DailyReport(user_id=user.id, log_date=day, markdown=markdown))
        count += 1
    db.commit()
    return count


def get_auto_save_status(db: Session) -> dict:
    """今日自动归档状态（前端轻提示用）。"""
    day = _today_str()
    latest = db.execute(
        select(func.max(DailyReport.saved_at)).where(DailyReport.log_date == day)
    ).scalar()
    count = db.execute(
        select(func.count(DailyReport.id)).where(DailyReport.log_date == day)
    ).scalar() or 0
    return {
        "date": day,
        "saved": count > 0,
        "saved_count": count,
        "saved_at": latest.isoformat(timespec="seconds") + "Z" if latest else None,
    }


def list_user_report_dates(db: Session, user_id: int) -> list[str]:
    """某用户存在进度快照或人工补充的所有日期（升序）。"""
    dates = set(
        db.execute(
            select(ProgressLog.log_date).where(ProgressLog.user_id == user_id)
        ).scalars()
    )
    dates.update(
        db.execute(
            select(DailyNote.log_date).where(DailyNote.user_id == user_id)
        ).scalars()
    )
    # 进度快照可能记录人为空（自动保存以主负责人记账），补上其名下任务（多选关联）有快照的日期
    dates.update(
        db.execute(
            select(ProgressLog.log_date)
            .join(Task, ProgressLog.task_id == Task.id)
            .where(
                Task.id.in_(
                    select(TaskAssignee.task_id).where(TaskAssignee.user_id == user_id)
                )
            )
        ).scalars()
    )
    return sorted(dates)


def generate_user_history_report(db: Session, user: User) -> str:
    """某用户全部历史工作日志的合并纯文本（最近在前）。"""
    dates = list_user_report_dates(db, user.id)
    header = f"工作日志汇总 · {user.display_name or user.username}"
    if not dates:
        return f"{header}\n\n（暂无任何进度记录）"
    divider = "══════════════════════════════"
    parts = [f"{header}（共 {len(dates)} 天）", ""]
    for day in reversed(dates):
        parts.append(generate_daily_report(db, user, day))
        parts.append("")
        parts.append(divider)
        parts.append("")
    return "\n".join(parts)


def list_tasks_with_note(
    db: Session, project_id: int, log_date: str | None = None, user: User | None = None
) -> list[dict]:
    """任务列表 + 当日进度说明 + 状态 + 停滞风险（每次返回随 17:30 归档机制实时计算）。

    进度说明按人独立（task_notes）：user 传当前登录人时返回其本人说明，互不可见他人内容；
    未传 user（内部统计路径）回退为 progress_logs 的最后记录人说明。
    """
    day = log_date or _today_str()
    if user is not None:
        notes = dict(
            db.execute(
                select(TaskNote.task_id, TaskNote.note).where(
                    TaskNote.log_date == day, TaskNote.user_id == user.id
                )
            ).all()
        )
    else:
        notes = dict(
            db.execute(
                select(ProgressLog.task_id, ProgressLog.note).where(ProgressLog.log_date == day)
            ).all()
        )
    tasks = list_tasks(db, project_id)
    risks = compute_task_risks(db, tasks)
    pairs = _assignee_ids_by_task(db, project_id)
    return [
        {
            "id": t.id,
            "project_id": t.project_id,
            "name": t.name,
            "start_date": t.start_date,
            "end_date": t.end_date,
            "progress": t.progress,
            "dependencies": t.dependencies,
            "assignee": t.assignee,
            "assignee_ids": pairs.get(t.id, []),
            "status": t.status or "not_started",
            "note": notes.get(t.id, ""),
            "risk_level": risks[t.id]["level"],
            "risk_reasons": risks[t.id]["reasons"],
            "position": t.position,
        }
        for t in tasks
    ]


def compute_task_risks(db: Session, tasks: list[Task]) -> dict[int, dict]:
    """停滞/逾期/计划偏差风险分级。

    🔴 停滞：进行中任务进度连续 ≥3 天无变化；逾期 ≥3 天未完成；被标记为阻塞
    🟡 关注：逾期（任意天数）、落后计划 ≥20 个百分点、连续 ≥3 天未填说明
    🟢 正常：其余（已完成/暂停/取消任务不参与判定）
    """
    from collections import defaultdict

    today = dt.date.today()
    risks: dict[int, dict] = {}
    if not tasks:
        return risks
    logs = db.execute(
        select(ProgressLog)
        .where(ProgressLog.task_id.in_([t.id for t in tasks]))
        .order_by(ProgressLog.task_id, ProgressLog.log_date)
    ).scalars().all()
    by_task: dict[int, list] = defaultdict(list)
    for l in logs:
        by_task[l.task_id].append(l)

    for t in tasks:
        status = t.status or "not_started"
        reasons: list[str] = []
        level = "ok"

        if status in ("done", "cancelled", "paused"):
            risks[t.id] = {"level": "ok", "reasons": [], "stall_days": 0, "note_gap": 0}
            continue

        seq = by_task.get(t.id, [])
        # 尾部连续相同进度天数（含今天）：快照每日都有 → 值减 1 即"停滞天数"
        stall_days = 0
        for l in reversed(seq):
            if l.progress == t.progress:
                stall_days += 1
            else:
                break
        stall_days = max(0, stall_days - 1)
        note_gap = 0
        for l in reversed(seq):
            if not (l.note or "").strip():
                note_gap += 1
            else:
                break

        overdue_days = 0
        try:
            end = dt.date.fromisoformat(t.end_date)
            if end < today:
                overdue_days = (today - end).days
        except ValueError:
            pass

        start = dt.date.fromisoformat(t.start_date) if t.start_date else None
        plan_dev = None
        if start and start <= today and t.end_date and start < end:
            span = (dt.date.fromisoformat(t.end_date) - start).days
            expected = (today - start).days / span * 100
            plan_dev = round(t.progress - expected)

        if status == "blocked":
            reasons.append("任务被标记为阻塞")
            level = "stall"
        if status == "in_progress" and t.progress < 100 and stall_days >= STALL_DAYS:
            reasons.append(f"进度已 {stall_days} 天无变化")
            level = "stall"
        if overdue_days >= OVERDUE_STALL_DAYS and t.progress < 100:
            reasons.append(f"已逾期 {overdue_days} 天")
            level = "stall"
        if overdue_days > 0 and t.progress < 100 and level == "ok":
            reasons.append(f"已逾期 {overdue_days} 天")
            level = "watch"
        if plan_dev is not None and plan_dev <= PLAN_DEV_THRESHOLD and t.progress < 100 and level == "ok":
            reasons.append(f"落后计划 {abs(plan_dev)} 个百分点")
            level = "watch"
        if note_gap >= NOTE_GAP_DAYS and t.progress < 100 and level == "ok":
            reasons.append(f"连续 {note_gap} 天未填写进度说明")
            level = "watch"

        risks[t.id] = {"level": level, "reasons": reasons, "stall_days": stall_days, "note_gap": note_gap}
    return risks


# ---------- 统计聚合（驾驶舱 / 投入度分析） ----------


def _risk_map_for_projects(db: Session, project_ids: list[int]) -> dict[int, dict]:
    tasks = db.execute(select(Task).where(Task.project_id.in_(project_ids))).scalars().all()
    return compute_task_risks(db, list(tasks))


def stats_activity_matrix(db: Session, days: int = 14) -> dict:
    """活跃热力图数据：每位启用账号在近 N 天中每日的进度更新次数。"""
    days = max(1, min(days, 31))
    today = dt.date.today()
    dates = [(today - dt.timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]
    since = dates[0]
    logs = db.execute(
        select(ProgressLog)
        .join(Task, ProgressLog.task_id == Task.id)
        .where(ProgressLog.log_date >= since)
    ).scalars().all()
    counts: dict[int, dict[str, int]] = {}
    for l in logs:
        if l.user_id is None:
            continue
        counts.setdefault(l.user_id, {}).setdefault(l.log_date, 0)
        counts[l.user_id][l.log_date] += 1

    users = db.execute(
        select(User).where(User.is_active).order_by(User.department_id, User.id)
    ).scalars().all()
    series = []
    for u in users:
        m = counts.get(u.id, {})
        series.append(
            {
                "user_id": u.id,
                "name": u.display_name or u.username,
                "cells": [{"date": d, "count": m.get(d, 0)} for d in dates],
                "total": sum(m.values()),
            }
        )
    return {"dates": dates, "users": series}


def stats_overview(db: Session) -> dict:
    """驾驶舱总览：部门聚合、状态分布、逾期/停滞清单。仅主管与管理员调用。"""
    projects = db.execute(select(Project)).scalars().all()
    proj_by_id = {p.id: p for p in projects}
    tasks = db.execute(select(Task)).scalars().all()
    users = {u.id: u for u in db.execute(select(User)).scalars()}
    risks = compute_task_risks(db, list(tasks))

    status_distribution = {s: 0 for s in STATUS_LABELS}
    overdue_list: list[dict] = []
    stalled_list: list[dict] = []
    dept_agg: dict[int, dict] = {}

    for t in tasks:
        status = t.status or "not_started"
        status_distribution[status] = status_distribution.get(status, 0) + 1
        risk = risks.get(t.id, {"level": "ok", "reasons": []})
        dept_id = proj_by_id[t.project_id].department_id if t.project_id in proj_by_id else None
        agg = dept_agg.setdefault(dept_id, {"task_count": 0, "progress_sum": 0, "overdue": 0, "stalled": 0})
        agg["task_count"] += 1
        agg["progress_sum"] += t.progress
        if risk["level"] == "stall":
            agg["stalled"] += 1
        mini = {
            "id": t.id,
            "name": t.name,
            "project_id": t.project_id,
            "project_name": proj_by_id[t.project_id].name if t.project_id in proj_by_id else "",
            "progress": t.progress,
            "status": status,
            "assignee": t.assignee or "未指定",
            "end_date": t.end_date,
            "reasons": risk["reasons"],
        }
        try:
            is_overdue = t.end_date < _today_str() and t.progress < 100 and status not in ("done", "cancelled")
        except ValueError:
            is_overdue = False
        if is_overdue:
            agg["overdue"] += 1
            overdue_list.append({**mini, "reasons": ["逾期未完成"]})
        if risk["level"] == "stall":
            stalled_list.append(mini)

    departments_out = []
    for d in db.execute(select(Department).order_by(Department.id)).scalars():
        agg = dept_agg.get(d.id, {"task_count": 0, "progress_sum": 0, "overdue": 0, "stalled": 0})
        departments_out.append(
            {
                "id": d.id,
                "name": d.name,
                "project_count": sum(1 for p in projects if p.department_id == d.id),
                "task_count": agg["task_count"],
                "avg_progress": round(agg["progress_sum"] / agg["task_count"]) if agg["task_count"] else 0,
                "overdue": agg["overdue"],
                "stalled": agg["stalled"],
            }
        )
    unc = dept_agg.get(None, {"task_count": 0, "progress_sum": 0, "overdue": 0, "stalled": 0})
    if unc["task_count"]:
        departments_out.append(
            {
                "id": 0,
                "name": "未分部门",
                "project_count": sum(1 for p in projects if p.department_id is None),
                "task_count": unc["task_count"],
                "avg_progress": round(unc["progress_sum"] / unc["task_count"]),
                "overdue": unc["overdue"],
                "stalled": unc["stalled"],
            }
        )

    return {
        "totals": {
            "project_count": len(projects),
            "task_count": len(tasks),
            "overdue_count": len(overdue_list),
            "stalled_count": len(stalled_list),
        },
        "status_distribution": status_distribution,
        "departments": departments_out,
        "overdue_list": sorted(overdue_list, key=lambda x: x["end_date"])[:20],
        "stalled_list": stalled_list[:20],
    }


def stats_user_activity(db: Session, days: int = 14) -> list[dict]:
    """员工投入度：近 N 天更新次数 / 说明填写率 / 名下任务平均停滞天数 / 最后活跃。仅主管与管理员。"""
    days = max(1, min(days, 90))
    since = (dt.date.today() - dt.timedelta(days=days - 1)).isoformat()
    users = {u.id: u for u in db.execute(select(User).where(User.is_active)).scalars()}
    logs = db.execute(
        select(ProgressLog)
        .join(Task, ProgressLog.task_id == Task.id)
        .where(ProgressLog.log_date >= since)
    ).scalars().all()

    per_user: dict[int, dict] = {}
    for l in logs:
        uid = l.user_id
        if uid is None:
            continue
        m = per_user.setdefault(uid, {"updates": 0, "notes": 0, "dates": set()})
        m["updates"] += 1
        if (l.note or "").strip():
            m["notes"] += 1
        m["dates"].add(l.log_date)

    tasks = db.execute(select(Task)).scalars().all()
    risks = compute_task_risks(db, list(tasks))
    task_by_id = {t.id: t for t in tasks}
    assigned: dict[int, list[Task]] = {}
    for tid, uid in db.execute(select(TaskAssignee.task_id, TaskAssignee.user_id)).all():
        t = task_by_id.get(tid)
        if t is not None:
            assigned.setdefault(uid, []).append(t)

    out = []
    for uid, u in users.items():
        m = per_user.get(uid, {"updates": 0, "notes": 0, "dates": set()})
        my_tasks = assigned.get(uid, [])
        stall_days_list = [risks[t.id]["stall_days"] for t in my_tasks if t.id in risks and (t.status or "") not in ("done", "cancelled")]
        avg_stall = round(sum(stall_days_list) / len(stall_days_list), 1) if stall_days_list else 0
        last_active = max(m["dates"]) if m["dates"] else None
        note_rate = round(m["notes"] / m["updates"] * 100) if m["updates"] else 0
        flag = bool(my_tasks) and m["updates"] == 0
        out.append(
            {
                "user_id": uid,
                "name": u.display_name or u.username,
                "username": u.username,
                "department": u.department.name if u.department else "",
                "task_count": len(my_tasks),
                "updates": m["updates"],
                "note_rate": note_rate,
                "avg_stall_days": avg_stall,
                "last_active": last_active,
                "last_login": u.last_login_at.date().isoformat() if u.last_login_at else None,
                "flag": flag,
            }
        )
    out.sort(key=lambda x: (not x["flag"], -x["updates"]))
    return out


def stats_progress_trend(db: Session, project_id: int | None = None) -> dict:
    """进度趋势：每日实际平均进度（快照）与期望平均进度（日期推算）。

    project_id 为空或 0 时聚合全部项目。
    """
    if project_id:
        get_project(db, project_id)
        tasks = list_tasks(db, project_id)
        logs = db.execute(
            select(ProgressLog)
            .join(Task, ProgressLog.task_id == Task.id)
            .where(Task.project_id == project_id)
            .order_by(ProgressLog.log_date)
        ).scalars().all()
    else:
        tasks = db.execute(select(Task)).scalars().all()
        # JOIN tasks：排除已删除任务的残留快照，避免污染全局趋势均值
        logs = db.execute(
            select(ProgressLog)
            .join(Task, ProgressLog.task_id == Task.id)
            .order_by(ProgressLog.log_date)
        ).scalars().all()

    # 每天每任务最新进度 → 按天求平均
    day_task: dict[str, dict[int, int]] = {}
    for l in logs:
        day_task.setdefault(l.log_date, {})[l.task_id] = l.progress
    trend = []
    for day in sorted(day_task):
        values = day_task[day].values()
        trend.append({"date": day, "actual": round(sum(values) / len(values))})

    # 期望进度：以项目任务最早开始/最晚结束为窗口，取全体任务期望均值
    if tasks:
        starts = [dt.date.fromisoformat(t.start_date) for t in tasks]
        ends = [dt.date.fromisoformat(t.end_date) for t in tasks]
        window_start, window_end = min(starts), max(ends)
        span = max(1, (window_end - window_start).days)
        cur = max(window_start, dt.date.fromisoformat(trend[0]["date"])) if trend else window_start
        end_bound = min(window_end, dt.date.today())
        while cur <= end_bound:
            expected_vals = []
            for t in tasks:
                s, e = dt.date.fromisoformat(t.start_date), dt.date.fromisoformat(t.end_date)
                if s <= cur <= e and e > s:
                    expected_vals.append((cur - s).days / (e - s).days * 100)
            trend_entry = next((x for x in trend if x["date"] == cur.isoformat()), None)
            if trend_entry is not None and expected_vals:
                trend_entry["expected"] = round(sum(expected_vals) / len(expected_vals))
            cur += dt.timedelta(days=1)
    return {"project_id": project_id, "trend": trend}


def search_all(db: Session, q: str, user: User) -> dict:
    """全局搜索：任务 / 项目 / 人员（登录即可用，最多各 8 条；按项目可见性过滤）。"""
    like = f"%{q}%"
    visible = _visible_project_ids(db, user)
    task_cond = [Task.name.like(like) | Task.assignee.like(like)]
    proj_cond = [Project.name.like(like) | Project.description.like(like)]
    if visible is not None:
        task_cond.append(Task.project_id.in_(visible))
        proj_cond.append(Project.id.in_(visible))
    task_rows = db.execute(
        select(Task, Project)
        .join(Project, Task.project_id == Project.id)
        .where(*task_cond)
        .limit(8)
    ).all()
    projects = db.execute(
        select(Project).where(*proj_cond).limit(5)
    ).scalars().all()
    users = db.execute(
        select(User).where(
            User.is_active, User.display_name.like(like) | User.username.like(like)
        ).limit(5)
    ).scalars().all()
    return {
        "tasks": [
            {
                "id": t.id,
                "name": t.name,
                "status": t.status or "not_started",
                "progress": t.progress,
                "project_id": p.id,
                "project_name": p.name,
                "department_id": p.department_id,
                "assignee": t.assignee,
            }
            for t, p in task_rows
        ],
        "projects": [
            {"id": p.id, "name": p.name, "department_id": p.department_id, "task_count": len(p.tasks)}
            for p in projects
        ],
        "users": [
            {"id": u.id, "name": u.display_name or u.username, "username": u.username}
            for u in users
        ],
    }


# ---------- 管理员统计 ----------


def admin_stats(db: Session, user: User) -> dict:
    count = lambda stmt: db.execute(stmt).scalar() or 0  # noqa: E731
    return {
        "user_count": count(select(func.count(User.id))),
        "active_user_count": count(select(func.count(User.id)).where(User.is_active)),
        "department_count": count(select(func.count(Department.id))),
        "project_count": count(select(func.count(Project.id))),
        "task_count": count(select(func.count(Task.id))),
        "document_count": count(select(func.count(Document.id))),
        "by_department": list_departments_overview(db, user),
    }


# ---------- 操作审计日志 ----------

# 动作字典：value 存库，label 供前端展示与筛选下拉
AUDIT_ACTION_LABELS = {
    "login": "登录",
    "login_failed": "登录失败",
    "logout": "退出登录",
    "change_password": "修改密码",
    "create_project": "新建项目",
    "update_project": "修改项目",
    "delete_project": "删除项目",
    "create_task": "新建任务",
    "update_task": "修改任务",
    "bulk_update_tasks": "批量修改任务",
    "delete_task": "删除任务",
    "upload_document": "上传文档",
    "download_document": "下载文档",
    "delete_document": "删除文档",
    "create_user": "创建账号",
    "update_user": "修改账号",
    "reset_password": "重置密码",
    "delete_user": "删除账号",
    "create_department": "新建部门",
    "update_department": "修改部门",
    "delete_department": "删除部门",
    "save_daily_decisions": "保存关键决策",
    "wecom_push": "推送工作简报",
    "task_remind": "发送任务提醒",
    "create_daily_task": "新增每日任务",
    "set_work_status": "设置工作状态",
}

# 危险/敏感动作（前端红色标识）
AUDIT_SENSITIVE_ACTIONS = {
    "delete_project",
    "delete_task",
    "delete_document",
    "delete_user",
    "delete_department",
    "reset_password",
    "login_failed",
}


def record_audit(
    db: Session,
    user: User | None,
    action: str,
    *,
    object_type: str = "",
    object_id: int | None = None,
    object_name: str = "",
    detail: str = "",
    ip: str = "",
    username_override: str | None = None,
) -> None:
    """写入一条审计日志。

    审计失败绝不影响主业务：任何异常仅记录告警并回滚本次写入。
    """
    try:
        db.add(
            AuditLog(
                user_id=user.id if user is not None else None,
                username=username_override or (user.username if user is not None else "anonymous"),
                action=action,
                object_type=object_type,
                object_id=object_id,
                object_name=(object_name or "")[:200],
                detail=(detail or "")[:500],
                ip=(ip or "")[:64],
            )
        )
        db.commit()
    except Exception:  # noqa: BLE001 — 审计是旁路，不允许拖垮主流程
        db.rollback()
        logger.warning("审计日志写入失败（action=%s）", action, exc_info=True)


def list_audit_logs(
    db: Session,
    *,
    user_id: int | None = None,
    action: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """分页查询审计日志（时间倒序），支持操作人/动作/时间范围筛选。"""
    stmt = select(AuditLog)
    if user_id is not None:
        stmt = stmt.where(AuditLog.user_id == user_id)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if start_date:
        stmt = stmt.where(AuditLog.created_at >= dt.datetime.fromisoformat(f"{start_date} 00:00:00"))
    if end_date:
        stmt = stmt.where(AuditLog.created_at <= dt.datetime.fromisoformat(f"{end_date} 23:59:59"))

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar() or 0
    page = max(1, page)
    page_size = max(1, min(100, page_size))
    rows = (
        db.execute(
            stmt.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        .scalars()
        .all()
    )
    return {
        "items": [
            {
                "id": r.id,
                "user_id": r.user_id,
                "username": r.username,
                "operator": (r.user.display_name or r.username) if r.user else r.username,
                "action": r.action,
                "action_label": AUDIT_ACTION_LABELS.get(r.action, r.action),
                "sensitive": r.action in AUDIT_SENSITIVE_ACTIONS,
                "object_type": r.object_type,
                "object_id": r.object_id,
                "object_name": r.object_name,
                "detail": r.detail,
                "ip": r.ip,
                "created_at": r.created_at.isoformat() + "Z" if r.created_at else None,
            }
            for r in rows
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }
