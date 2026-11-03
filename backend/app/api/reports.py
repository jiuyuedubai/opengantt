"""每日工作日志路由：模板生成、关键决策保存、管理员历史导出。"""

import datetime as dt

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import NotFoundError, PermissionDeniedError, ValidationError
from app.models import User
from app.security import client_ip, get_current_user, require_roles
from app.services import (
    _today_str,
    generate_daily_report,
    generate_user_history_report,
    get_auto_save_status,
    get_daily_decisions,
    get_daily_extras,
    record_audit,
    save_daily_decisions,
    save_daily_extras,
)

router = APIRouter(prefix="/api/reports", tags=["reports"])


def _validate_date(date_str: str) -> str:
    try:
        dt.date.fromisoformat(date_str)
    except ValueError:
        raise ValidationError("日期必须为 YYYY-MM-DD 格式")
    return date_str


class DailyNoteIn(BaseModel):
    date: str = Field(min_length=10, max_length=10)
    decisions: str | None = Field(default=None, max_length=1000)
    extras: str | None = Field(default=None, max_length=2000, description="补充条目（临时事项），每行一条")


@router.get("/daily", response_class=Response, summary="我的每日工作日志（Markdown，按模板生成）")
def daily_report(
    date: str = Query(default=None, description="日志日期，默认今天"),
    user_id: int = Query(default=None, description="查看指定用户的日志（仅管理员）"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    target = user
    if user_id is not None:
        if user.role != "admin":
            raise PermissionDeniedError("仅管理员可查看他人的工作日志")
        target = db.get(User, user_id)
        if target is None:
            raise NotFoundError("用户不存在")
    day = _validate_date(date) if date else _today_str()
    markdown = generate_daily_report(db, target, day)
    return Response(
        content=markdown,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'inline; filename="worklog-{day}.md"'},
    )


@router.get("/daily/decisions", summary="读取某日关键决策与补充事项")
def daily_decisions(
    date: str = Query(description="YYYY-MM-DD"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    day = _validate_date(date)
    return {
        "date": day,
        "decisions": get_daily_decisions(db, user.id, day),
        "extras": get_daily_extras(db, user.id, day),
    }


@router.put("/daily/decisions", summary="保存某日关键决策/补充事项（本人）")
def put_daily_decisions(
    payload: DailyNoteIn,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    day = _validate_date(payload.date)
    if payload.decisions is None and payload.extras is None:
        raise ValidationError("decisions 与 extras 至少提供一项")
    if payload.decisions is not None:
        save_daily_decisions(db, user, day, payload.decisions)
    if payload.extras is not None:
        save_daily_extras(db, user, day, payload.extras)
    parts = []
    if payload.decisions is not None:
        parts.append(f"关键决策（{len(payload.decisions)} 字）")
    if payload.extras is not None:
        parts.append(f"补充事项（{len(payload.extras)} 字）")
    record_audit(
        db, user, "save_daily_decisions",
        object_type="daily_note", object_id=user.id, object_name=f"{user.display_name or user.username} {day}",
        detail=f"{day} {'、'.join(parts)}",
        ip=client_ip(request),
    )
    return {"ok": True, "date": payload.date}


@router.get("/auto-save-status", summary="今日工作日志自动保存状态（轻提示轮询用）")
def auto_save_status(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return get_auto_save_status(db)


@router.get(
    "/user/{user_id}/history",
    response_class=Response,
    summary="导出指定用户全部历史工作日志（仅管理员）",
)
def user_history_report(
    user_id: int,
    user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    target = db.get(User, user_id)
    if target is None:
        raise NotFoundError("用户不存在")
    markdown = generate_user_history_report(db, target)
    name = target.display_name or target.username
    from urllib.parse import quote

    ascii_name = f"worklog-history-{target.username}.md"
    utf8_name = quote(f"工作日志汇总-{name}.md")
    return Response(
        content=markdown,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f"inline; filename=\"{ascii_name}\"; filename*=UTF-8''{utf8_name}"
        },
    )
