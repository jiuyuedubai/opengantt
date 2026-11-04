"""绩效考核路由：模板库管理与考核结果生成/下载。全部端点仅限管理员。"""

from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import ValidationError
from app.models import User
from app.performance import (
    delete_template,
    export_results_zip,
    generate_results,
    get_result_file,
    get_template_file,
    list_results,
    list_templates,
    save_template,
)
from app.security import client_ip, require_roles
from app.services import record_audit

router = APIRouter(prefix="/api/admin/performance", tags=["performance"])
_ADMIN = Depends(require_roles("admin"))
_DB = Depends(get_db)


class GenerateIn(BaseModel):
    user_ids: list[int] = Field(min_length=1, max_length=100, description="要考核的员工 ID 列表")
    period: str = Field(pattern=r"^\d{4}-\d{2}$", description="考核周期，如 2026-11")
    ai_score: bool = Field(default=False, description="是否调用 AI 自动评分（失败自动降级为人工填写）")


@router.get("/templates", response_model=list[dict], summary="考核表模板列表")
def templates(admin: User = _ADMIN, db: Session = _DB):
    return list_templates(db)


@router.post("/templates", response_model=dict, status_code=201, summary="上传/替换考核表模板（一人一份）")
async def upload_template(
    request: Request,
    admin: User = _ADMIN,
    db: Session = _DB,
):
    form = await request.form()
    user_id = int(form.get("user_id", "0") or 0)
    upload = form.get("file")
    if user_id <= 0:
        raise ValidationError("请选择员工")
    if upload is None:
        raise ValidationError("请选择考核表文件")
    content = await upload.read()
    info = save_template(db, admin, user_id, upload.filename or "考核表", content, upload.content_type or "")
    record_audit(
        db, admin, "performance_template",
        object_type="performance", object_id=info["id"], object_name=info["original_name"],
        detail=f"上传 {info['user_name']} 的考核表模板（{info['size'] / 1024:.1f} KB）",
        ip=client_ip(request),
    )
    return info


@router.get("/templates/{template_id}/download", summary="下载考核表模板")
def download_template(template_id: int, admin: User = _ADMIN, db: Session = _DB):
    tpl, content = get_template_file(db, template_id)
    # HTTP 头仅允许 latin-1：中文文件名必须 percent-encode（RFC 5987）
    quoted = quote(tpl.original_name)
    return Response(
        content,
        media_type=tpl.content_type or "application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quoted}"},
    )


@router.delete("/templates/{template_id}", status_code=204, summary="删除考核表模板")
def remove_template(template_id: int, request: Request, admin: User = _ADMIN, db: Session = _DB):
    tpl, _ = get_template_file(db, template_id)
    delete_template(db, admin, template_id)
    record_audit(
        db, admin, "performance_template_delete",
        object_type="performance", object_id=template_id, object_name=tpl.original_name,
        detail=f"删除 {tpl.user_id} 的考核表模板",
        ip=client_ip(request),
    )


@router.post("/generate", response_model=list[dict], summary="为选定员工批量生成考核结果")
def generate(
    payload: GenerateIn,
    request: Request,
    admin: User = _ADMIN,
    db: Session = _DB,
):
    results = generate_results(db, admin, payload.user_ids, payload.period, ai_score=payload.ai_score)
    record_audit(
        db, admin, "performance_generate",
        object_type="performance", object_name=payload.period,
        detail=f"生成 {len(results)} 名员工的考核结果（周期 {payload.period}，AI评分={'开' if payload.ai_score else '关'}）",
        ip=client_ip(request),
    )
    return results


@router.get("/results", response_model=list[dict], summary="考核结果列表")
def results(period: str | None = None, admin: User = _ADMIN, db: Session = _DB):
    return list_results(db, period)


@router.get("/results/{result_id}/download", summary="下载单个考核结果（Markdown）")
def download_result(result_id: int, admin: User = _ADMIN, db: Session = _DB):
    filename, content = get_result_file(db, result_id)
    quoted = quote(filename)
    return Response(
        content,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quoted}"},
    )


@router.get("/results/export", summary="按周期批量打包下载（zip：结果摘要+考核表模板）")
def export_zip(period: str, admin: User = _ADMIN, db: Session = _DB):
    filename, content = export_results_zip(db, period)
    quoted = quote(filename)
    return Response(
        content,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quoted}"},
    )
