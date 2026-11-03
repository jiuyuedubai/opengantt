"""操作审计日志路由：分页筛选查询与动作字典。所有端点仅限 admin 角色。"""

import datetime as dt

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import ValidationError
from app.security import require_roles
from app.services import AUDIT_ACTION_LABELS, list_audit_logs

router = APIRouter(prefix="/api/audit-logs", tags=["audit"])
_ADMIN_ONLY = Depends(require_roles("admin"))
router.dependencies = [_ADMIN_ONLY]


def _validate_date(date_str: str | None, label: str) -> str | None:
    if not date_str:
        return None
    try:
        dt.date.fromisoformat(date_str)
    except ValueError:
        raise ValidationError(f"{label}必须为 YYYY-MM-DD 格式")
    return date_str


@router.get("", summary="操作日志分页查询（操作人/动作/时间范围筛选）")
def list_logs(
    user_id: int | None = Query(default=None, description="按操作人账号 ID 筛选"),
    action: str | None = Query(default=None, description="按操作类型筛选（audit action value）"),
    start_date: str | None = Query(default=None, description="开始日期 YYYY-MM-DD（含）"),
    end_date: str | None = Query(default=None, description="结束日期 YYYY-MM-DD（含）"),
    page: int = Query(default=1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页条数（1-100）"),
    db: Session = Depends(get_db),
):
    return list_audit_logs(
        db,
        user_id=user_id,
        action=action or None,
        start_date=_validate_date(start_date, "开始日期"),
        end_date=_validate_date(end_date, "结束日期"),
        page=page,
        page_size=page_size,
    )


@router.get("/actions", summary="操作类型字典（筛选下拉用）")
def actions():
    return [{"value": k, "label": v} for k, v in AUDIT_ACTION_LABELS.items()]
