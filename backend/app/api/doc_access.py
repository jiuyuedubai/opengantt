"""跨部门文档查询授权路由：员工端（申请/查询我的授权）+ 管理员端（审批/直接授权/列表）。"""

import datetime as dt

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import ValidationError
from app.models import User
from app.security import client_ip, get_current_user, require_roles
from app.services import (
    decide_doc_access,
    doc_access_request,
    grant_doc_access,
    list_doc_access,
    my_doc_access,
    record_audit,
)

router = APIRouter(prefix="/api/doc-access", tags=["doc-access"])


def _parse_until(raw: str) -> dt.datetime:
    try:
        return dt.datetime.fromisoformat(raw.strip())
    except ValueError:
        raise ValidationError("有效期截止时间格式不正确")


class DocAccessRequestIn(BaseModel):
    department_id: int = Field(description="要申请查询的目标部门")
    expires_at: str = Field(description="期望有效期截止（ISO）")
    note: str = Field(default="", max_length=200, description="申请说明")


class DocAccessGrantIn(BaseModel):
    user_id: int
    department_id: int
    expires_at: str


class DocAccessDecideIn(BaseModel):
    action: str = Field(pattern=r"^(approve|revoke)$")
    expires_at: str | None = None


@router.get("/mine", response_model=list[dict], summary="我的跨部门查询授权与申请记录")
def my_grants(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return my_doc_access(db, user)


@router.post("/requests", response_model=dict, status_code=201, summary="申请查询其他部门文档")
def request_access(
    payload: DocAccessRequestIn,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    until = _parse_until(payload.expires_at)
    result = doc_access_request(db, user, payload.department_id, until, payload.note)
    record_audit(
        db, user, "doc_access_request_log",
        object_type="doc_access", object_id=result["id"], object_name=result["department_name"],
        detail=f"提交跨部门文档查询申请（有效期至 {result['expires_at']}）",
        ip=client_ip(request),
    )
    return result


@router.get("/all", response_model=list[dict], summary="全部申请与授权（管理员）")
def all_grants(
    status: str | None = None,
    admin: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    return list_doc_access(db, status)


@router.post("/grant", response_model=dict, status_code=201, summary="直接授权（管理员）")
def grant(
    payload: DocAccessGrantIn,
    request: Request,
    admin: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    until = _parse_until(payload.expires_at)
    return grant_doc_access(db, admin, payload.user_id, payload.department_id, until)


@router.post("/{grant_id}/decide", response_model=dict, summary="审批申请（批准/撤销，管理员）")
def decide(
    grant_id: int,
    payload: DocAccessDecideIn,
    request: Request,
    admin: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    until = _parse_until(payload.expires_at) if payload.expires_at else None
    result = decide_doc_access(db, admin, grant_id, payload.action, until)
    record_audit(
        db, admin, f"doc_access_{payload.action}_log",
        object_type="doc_access", object_id=grant_id, object_name=result["department_name"],
        detail=f"{'批准' if payload.action == 'approve' else '撤销'} {result['user_name']} 的跨部门文档查询（有效期至 {result['expires_at']}）",
        ip=client_ip(request),
    )
    return result
