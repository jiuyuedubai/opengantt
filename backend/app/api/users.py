"""用户列表路由：供任务负责人下拉选择（仅返回最小信息，需登录）。"""

import datetime as dt

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import ValidationError
from app.models import User
from app.schemas import WorkStatusIn
from app.security import client_ip, get_current_user
from app.services import WORK_STATUS_LABELS, _user_dept_ids, record_audit

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("", response_model=list[dict], summary="用户列表（负责人选择用，最小信息）")
def list_users(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    users = db.execute(
        select(User).where(User.is_active).order_by(User.department_id, User.id)
    ).scalars().all()
    return [
        {
            "id": u.id,
            "username": u.username,
            "display_name": u.display_name or u.username,
            "department_id": u.department_id,
            # 全部所属部门（含多部门）：负责人选择的部门范围过滤依据
            "department_ids": sorted(_user_dept_ids(db, u)),
            "work_status": u.work_status or "working",
            "work_status_until": u.work_status_until.isoformat(timespec="seconds") if u.work_status_until else None,
        }
        for u in users
    ]


@router.patch("/me/work-status", response_model=dict, summary="设置自己的工作状态（在岗/请假/休假/出差）")
def set_my_work_status(
    payload: WorkStatusIn,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    old = WORK_STATUS_LABELS.get(user.work_status or "working", "在岗")
    # 预计结束时间：仅在非在岗状态下有效；恢复为在岗时自动清除
    until_dt: dt.datetime | None = None
    if payload.work_status != "working":
        until_raw = (payload.work_status_until or "").strip()
        if until_raw:
            try:
                until_dt = dt.datetime.fromisoformat(until_raw)
            except ValueError:
                raise ValidationError("预计结束时间格式不正确")
            if until_dt <= dt.datetime.now():
                raise ValidationError("预计结束时间必须晚于当前时间")
    user.work_status = payload.work_status
    user.work_status_until = until_dt
    db.commit()
    new = WORK_STATUS_LABELS.get(payload.work_status, payload.work_status)
    detail = f"{old} → {new}"
    if until_dt:
        detail += f"（预计 {until_dt:%m-%d %H:%M} 自动恢复在岗）"
    record_audit(
        db, user, "set_work_status",
        object_type="user", object_id=user.id, object_name=user.username,
        detail=detail,
        ip=client_ip(request),
    )
    return {
        "work_status": payload.work_status,
        "work_status_label": new,
        "work_status_until": until_dt.isoformat(timespec="seconds") if until_dt else None,
    }
