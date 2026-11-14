"""认证路由：账号密码登录（管理员统一开账号）→ httpOnly Cookie 会话。"""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import ValidationError
from app.models import User
from app.schemas import ChangePasswordIn, LoginIn, UserOut
from app.security import (
    clear_auth_cookie,
    client_ip,
    create_token,
    get_current_user,
    hash_password,
    set_auth_cookie,
    verify_password,
)
from app.services import ROLE_LABELS, WORK_STATUS_LABELS, _user_dept_ids, _user_dept_names, record_audit

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _user_out(db: Session, user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name or user.username,
        "role": user.role,
        "role_label": ROLE_LABELS.get(user.role, user.role),
        "department_id": user.department_id,
        "department_name": user.department.name if user.department else "",
        "departments": _user_dept_names(db, user),
        "department_ids": sorted(_user_dept_ids(db, user)),
        "is_active": user.is_active,
        "work_status": user.work_status or "working",
        "work_status_label": WORK_STATUS_LABELS.get(user.work_status or "working", "在岗"),
        "work_status_until": user.work_status_until.isoformat(timespec="seconds") if user.work_status_until else None,
    }


# SEC-001 登录限速：按 用户名+IP 限 5 次/5 分钟（内存实现，重启即清零；多 Worker 各自独立计数）
_LOGIN_ATTEMPTS: dict[str, list[float]] = {}
_LOGIN_LIMIT, _LOGIN_WINDOW = 5, 300.0


def _check_login_rate(key: str) -> None:
    import time as _time

    now = _time.time()
    bucket = [t for t in _LOGIN_ATTEMPTS.get(key, []) if now - t < _LOGIN_WINDOW]
    if len(bucket) >= _LOGIN_LIMIT:
        raise ValidationError("登录尝试过于频繁，请 5 分钟后再试")
    _LOGIN_ATTEMPTS[key] = bucket + [now]


@router.post("/login", response_model=UserOut, summary="账号密码登录")
def login(payload: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    ip = client_ip(request)
    _check_login_rate(f"{payload.username}|{client_ip(request)}")
    user = db.execute(select(User).where(User.username == payload.username)).scalar_one_or_none()
    if user is None or not verify_password(payload.password, user.password_hash):
        # 审计：失败尝试也记录（安全追溯），不泄露密码本身
        record_audit(
            db, None, "login_failed",
            object_type="user", object_name=payload.username,
            detail="用户名或密码错误", ip=ip,
            username_override=payload.username,
        )
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not user.is_active:
        record_audit(
            db, None, "login_failed",
            object_type="user", object_id=user.id, object_name=user.display_name or user.username,
            detail="账号已停用", ip=ip, username_override=user.username,
        )
        raise HTTPException(status_code=403, detail="账号已停用，请联系管理员")
    # 记录最后登录时间（员工投入度指标之一）
    import datetime as _dt

    user.last_login_at = _dt.datetime.now(_dt.UTC).replace(tzinfo=None)
    db.commit()
    record_audit(
        db, user, "login",
        object_type="user", object_id=user.id,
        object_name=user.display_name or user.username, ip=ip,
    )
    set_auth_cookie(response, create_token(user))
    return _user_out(db, user)


@router.post("/logout", summary="退出登录")
def logout(response: Response):
    clear_auth_cookie(response)
    return {"ok": True}


@router.get("/me", response_model=UserOut, summary="当前登录用户")
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _user_out(db, user)


@router.post("/change-password", summary="修改自己的密码")
def change_password(
    payload: ChangePasswordIn,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not verify_password(payload.old_password, user.password_hash):
        raise HTTPException(status_code=400, detail="原密码不正确")
    user.password_hash = hash_password(payload.new_password)
    db.commit()
    record_audit(
        db, user, "change_password",
        object_type="user", object_id=user.id,
        object_name=user.display_name or user.username, ip=client_ip(request),
    )
    return {"ok": True}
