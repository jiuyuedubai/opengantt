"""管理员后台路由：员工账号、部门与系统统计。所有端点仅限 admin 角色。"""

import datetime as dt

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.backup import create_backup, delete_backups, list_backups, restore_backup
from app.database import get_db
from app.errors import NotFoundError, ValidationError
from app.models import Department, Document, Project, User, UserDepartment
from app.schemas import (
    AdminUserCreate,
    AdminUserUpdate,
    DepartmentCreate,
    DepartmentUpdate,
    ResetPasswordIn,
)
from app.security import client_ip, hash_password, require_roles
from app.services import WORK_STATUS_LABELS, _user_dept_ids, _user_dept_names, admin_stats, record_audit
from app.wecom import push_daily_digest

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[])
_ADMIN_ONLY = Depends(require_roles("admin"))
router.dependencies = [_ADMIN_ONLY]


def _apply_user_departments(db: Session, user: User, department_ids: list[int]) -> None:
    """整体替换用户的多部门关联；主部门（users.department_id）取第一个。"""
    ids = [i for i in dict.fromkeys(department_ids or []) if i]
    for d_id in ids:
        if db.get(Department, d_id) is None:
            raise ValidationError(f"所选部门 {d_id} 不存在")
    for r in db.execute(
        select(UserDepartment).where(UserDepartment.user_id == user.id)
    ).scalars():
        db.delete(r)
    db.flush()
    for d_id in ids:
        db.add(UserDepartment(user_id=user.id, department_id=d_id))
    user.department_id = ids[0] if ids else None


def _user_out(db: Session, user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name or user.username,
        "role": user.role,
        "department_id": user.department_id,
        "department_name": user.department.name if user.department else "",
        "departments": _user_dept_names(db, user),
        # 全部所属部门 ID（与 auth._user_out 对齐）：前端账号列表按部门筛选依赖此字段
        "department_ids": sorted(_user_dept_ids(db, user)),
        "is_active": user.is_active,
        "wecom_mobile": user.wecom_mobile or "",
        "work_status": user.work_status or "working",
        "work_status_label": WORK_STATUS_LABELS.get(user.work_status or "working", "在岗"),
        "work_status_until": user.work_status_until.isoformat(timespec="seconds") if user.work_status_until else None,
    }


# ---------- 员工账号 ----------


@router.get("/users", response_model=list[dict], summary="账号列表")
def list_users(db: Session = Depends(get_db)):
    users = db.execute(select(User).order_by(User.id)).scalars().all()
    return [_user_out(db, u) for u in users]


@router.post("/users", response_model=dict, status_code=201, summary="创建账号")
def create_user(
    payload: AdminUserCreate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_roles("admin")),
):
    exists = db.execute(select(User).where(User.username == payload.username)).scalar_one_or_none()
    if exists:
        raise ValidationError(f"用户名 {payload.username} 已存在")
    # 多部门：department_ids 优先；兼容旧的单 department_id 字段
    dept_ids = payload.department_ids or ([payload.department_id] if payload.department_id else [])
    for d_id in dept_ids:
        if db.get(Department, d_id) is None:
            raise ValidationError("所选部门不存在")
    user = User(
        username=payload.username,
        password_hash=hash_password(payload.password),
        display_name=payload.display_name or payload.username,
        role=payload.role,
        department_id=dept_ids[0] if dept_ids else None,
        wecom_mobile=(payload.wecom_mobile or "").strip(),
    )
    db.add(user)
    db.flush()
    for d_id in dept_ids:
        db.add(UserDepartment(user_id=user.id, department_id=d_id))
    db.commit()
    record_audit(
        db, admin, "create_user",
        object_type="user", object_id=user.id, object_name=user.display_name or user.username,
        detail=f"账号 {user.username}；角色 {user.role}",
        ip=client_ip(request),
    )
    return _user_out(db, user)


@router.patch("/users/{user_id}", response_model=dict, summary="更新账号（姓名/角色/部门/启用停用）")
def update_user(
    user_id: int,
    payload: AdminUserUpdate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_roles("admin")),
):
    user = db.get(User, user_id)
    if user is None:
        raise NotFoundError("账号不存在")
    if payload.department_id is not None and db.get(Department, payload.department_id) is None:
        raise ValidationError("所选部门不存在")
    changed: list[str] = []
    if payload.display_name is not None:
        user.display_name = payload.display_name
        changed.append("姓名")
    if payload.role is not None:
        user.role = payload.role
        changed.append("角色")
    if payload.department_ids is not None:
        _apply_user_departments(db, user, payload.department_ids)
        changed.append("部门")
    elif payload.department_id is not None:
        # 兼容旧的单部门参数：并入现有关联并以之为第一部门
        current = [
            r.department_id
            for r in db.execute(
                select(UserDepartment).where(UserDepartment.user_id == user.id)
            ).scalars()
        ]
        _apply_user_departments(db, user, [payload.department_id] + [x for x in current if x != payload.department_id])
        changed.append("部门")
    if payload.wecom_mobile is not None:
        user.wecom_mobile = payload.wecom_mobile.strip()
        changed.append("企微手机号")
    if payload.work_status is not None:
        user.work_status = payload.work_status
        changed.append("工作状态")
    if payload.work_status_until is not None:
        raw = (payload.work_status_until or "").strip()
        if payload.work_status == "working" or not raw:
            user.work_status_until = None
        else:
            try:
                until_dt = dt.datetime.fromisoformat(raw)
            except ValueError:
                raise ValidationError("预计结束时间格式不正确")
            if until_dt <= dt.datetime.now():
                raise ValidationError("预计结束时间必须晚于当前时间")
            user.work_status_until = until_dt
            changed.append("预计恢复时间")
    if payload.is_active is not None:
        if user.id == admin.id and not payload.is_active:
            raise ValidationError("不能停用自己的账号")
        user.is_active = payload.is_active
        changed.append("启用" if payload.is_active else "停用")
    db.commit()
    record_audit(
        db, admin, "update_user",
        object_type="user", object_id=user.id, object_name=user.display_name or user.username,
        detail=f"账号 {user.username}；修改：" + ("、".join(changed) or "—"),
        ip=client_ip(request),
    )
    return _user_out(db, user)


@router.post("/users/{user_id}/reset-password", summary="重置密码")
def reset_password(
    user_id: int,
    payload: ResetPasswordIn,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_roles("admin")),
):
    user = db.get(User, user_id)
    if user is None:
        raise NotFoundError("账号不存在")
    user.password_hash = hash_password(payload.new_password)
    db.commit()
    record_audit(
        db, admin, "reset_password",
        object_type="user", object_id=user.id, object_name=user.display_name or user.username,
        detail=f"重置账号 {user.username} 的登录密码",
        ip=client_ip(request),
    )
    return {"ok": True}


@router.delete("/users/{user_id}", status_code=204, summary="删除账号")
def delete_user(user_id: int, request: Request, db: Session = Depends(get_db), admin: User = Depends(require_roles("admin"))):
    user = db.get(User, user_id)
    if user is None:
        raise NotFoundError("账号不存在")
    owned = db.execute(
        select(func.count(Project.id)).where(Project.owner_id == user_id)
    ).scalar()
    if owned:
        raise ValidationError(f"该账号负责 {owned} 个项目，请先移交项目再删除")
    username, display = user.username, user.display_name or user.username
    db.execute(
        Document.__table__.update().where(Document.uploader_id == user_id).values(uploader_id=None)
    )
    db.delete(user)
    db.commit()
    record_audit(
        db, admin, "delete_user",
        object_type="user", object_id=user_id, object_name=display,
        detail=f"删除账号 {username}",
        ip=client_ip(request),
    )


# ---------- 部门 ----------


def _dept_out(db: Session, dept: Department) -> dict:
    user_count = db.execute(
        select(func.count(User.id)).where(User.department_id == dept.id)
    ).scalar() or 0
    project_count = db.execute(
        select(func.count(Project.id)).where(Project.department_id == dept.id)
    ).scalar() or 0
    return {
        "id": dept.id,
        "name": dept.name,
        "description": dept.description,
        "user_count": user_count,
        "project_count": project_count,
    }


@router.get("/departments", response_model=list[dict], summary="部门列表")
def list_departments(db: Session = Depends(get_db)):
    depts = db.execute(select(Department).order_by(Department.id)).scalars().all()
    return [_dept_out(db, d) for d in depts]


@router.post("/departments", response_model=dict, status_code=201, summary="新建部门")
def create_department(
    payload: DepartmentCreate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_roles("admin")),
):
    exists = db.execute(select(Department).where(Department.name == payload.name)).scalar_one_or_none()
    if exists:
        raise ValidationError(f"部门 {payload.name} 已存在")
    dept = Department(name=payload.name, description=payload.description)
    db.add(dept)
    db.commit()
    record_audit(
        db, admin, "create_department",
        object_type="department", object_id=dept.id, object_name=dept.name,
        ip=client_ip(request),
    )
    return _dept_out(db, dept)


@router.patch("/departments/{dept_id}", response_model=dict, summary="更新部门")
def update_department(
    dept_id: int,
    payload: DepartmentUpdate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_roles("admin")),
):
    dept = db.get(Department, dept_id)
    if dept is None:
        raise NotFoundError("部门不存在")
    if payload.name is not None:
        dup = db.execute(
            select(Department).where(Department.name == payload.name, Department.id != dept_id)
        ).scalar_one_or_none()
        if dup:
            raise ValidationError(f"部门 {payload.name} 已存在")
        dept.name = payload.name
    if payload.description is not None:
        dept.description = payload.description
    db.commit()
    changed = [k for k, v in payload.model_dump().items() if v is not None]
    record_audit(
        db, admin, "update_department",
        object_type="department", object_id=dept_id, object_name=dept.name,
        detail="修改：" + ("、".join(changed) or "—"),
        ip=client_ip(request),
    )
    return _dept_out(db, dept)


@router.delete("/departments/{dept_id}", status_code=204, summary="删除部门")
def delete_department(
    dept_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_roles("admin")),
):
    dept = db.get(Department, dept_id)
    if dept is None:
        raise NotFoundError("部门不存在")
    users = db.execute(
        select(func.count(func.distinct(User.id)))
        .select_from(User)
        .outerjoin(UserDepartment, UserDepartment.user_id == User.id)
        .where(or_(User.department_id == dept_id, UserDepartment.department_id == dept_id))
    ).scalar() or 0
    projects = db.execute(
        select(func.count(Project.id)).where(Project.department_id == dept_id)
    ).scalar() or 0
    if users or projects:
        raise ValidationError(f"部门下仍有 {users} 个账号、{projects} 个项目，请先转移后再删除")
    name = dept.name
    db.delete(dept)
    db.commit()
    record_audit(
        db, admin, "delete_department",
        object_type="department", object_id=dept_id, object_name=name,
        ip=client_ip(request),
    )


# ---------- 系统统计 ----------


@router.get("/stats", summary="系统概览统计")
def stats(user: User = Depends(require_roles("admin")), db: Session = Depends(get_db)):
    return admin_stats(db, user)


# ---------- 企微工作简报 ----------


class WecomPushIn(BaseModel):
    """手动推送参数：date 为空推送今天；force_fallback 预览降级模板效果。"""

    date: str | None = Field(default=None, description="日志日期 YYYY-MM-DD")
    force_fallback: bool = Field(default=False, description="强制使用规则模板（不调 AI）")


@router.post("/wecom/test-push", summary="立即推送工作简报到企微群（测试/补发）")
def wecom_test_push(
    payload: WecomPushIn,
    request: Request,
    admin: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    result = push_daily_digest(db, log_date=payload.date, force_fallback=payload.force_fallback)
    mode_raw = result.get("mode")
    mode = {"ai": "AI 整理", "departments": "按部门推送"}.get(mode_raw, "模板汇总")
    status = "成功" if result.get("ok") else "失败/跳过"
    dept_detail = ""
    if mode_raw == "departments":
        depts = result.get("departments") or {}
        detail = "；".join(f"{k}:{'成功' if v.get('ok') else '失败'}" for k, v in depts.items())
        dept_detail = f"（{detail}）" if detail else ""
    record_audit(
        db, admin, "wecom_push",
        object_type="report", object_name=payload.date or "今天",
        detail=f"手动推送企微简报{status}（{mode}）{dept_detail}",
        ip=client_ip(request),
    )
    return result


# ---------- 数据备份与回退 ----------


class RestoreIn(BaseModel):
    filename: str = Field(min_length=1, description="备份文件名（来自备份历史）")


class BackupDeleteIn(BaseModel):
    filenames: list[str] = Field(min_length=1, max_length=50, description="要删除的备份文件名列表")


@router.get("/backups", response_model=list[dict], summary="备份历史（按版本号倒序）")
def backups_list(admin: User = Depends(require_roles("admin"))):
    return list_backups()


@router.post("/backups", response_model=dict, status_code=201, summary="立即创建一次备份")
def backups_create(request: Request, db: Session = Depends(get_db), admin: User = Depends(require_roles("admin"))):
    try:
        info = create_backup(trigger="manual")
    except FileNotFoundError as exc:
        raise NotFoundError(str(exc))
    except RuntimeError as exc:
        raise ValidationError(str(exc))
    record_audit(
        db, admin, "backup",
        object_type="backup", object_name=info["filename"],
        detail=f"手动备份 v{info['version']}（{info['size'] / 1024:.1f} KB）",
        ip=client_ip(request),
    )
    return info


@router.post("/backups/restore", response_model=dict, summary="回退到指定备份版本")
def backups_restore(
    payload: RestoreIn,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_roles("admin")),
):
    try:
        result = restore_backup(payload.filename)
    except FileNotFoundError as exc:
        raise NotFoundError(str(exc))
    except (ValueError, RuntimeError) as exc:
        raise ValidationError(str(exc))
    record_audit(
        db, admin, "restore",
        object_type="backup", object_name=payload.filename,
        detail=f"数据回退到 v{result['version']}，回退前快照 {result['pre_restore_backup']}",
        ip=client_ip(request),
    )
    return result


@router.post("/backups/delete", response_model=dict, summary="删除备份文件（支持批量）")
def backups_delete(
    payload: BackupDeleteIn,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_roles("admin")),
):
    try:
        result = delete_backups(payload.filenames)
    except ValueError as exc:
        raise ValidationError(str(exc))
    freed_kb = result["freed"] / 1024
    detail = f"删除备份 {len(result['deleted'])} 份，释放 {freed_kb:.1f} KB"
    if result["failed"]:
        detail += f"；失败 {len(result['failed'])} 份"
    record_audit(
        db, admin, "backup_delete",
        object_type="backup", object_name=f"{len(result['deleted'])} 份",
        detail=detail,
        ip=client_ip(request),
    )
    return result
