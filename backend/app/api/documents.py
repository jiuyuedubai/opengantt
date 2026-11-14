"""项目进度文档路由：上传、列表、下载、删除。"""

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.errors import ValidationError
from app.models import User
from app.security import client_ip, get_current_user, require_roles
from app.services import (
    _can_view_document,
    bulk_delete_by_ids,
    bulk_delete_documents,
    bulk_document_stats,
    delete_document,
    get_document_file,
    list_document_tree,
    list_documents,
    record_audit,
    save_document_bulk,
)

router = APIRouter(prefix="/api", tags=["documents"])


@router.post("/projects/{project_id}/documents", status_code=201, summary="上传进度文档（支持多文件与 zip 压缩包自动解压）")
async def upload_document(
    project_id: int,
    request: Request,
    note: str = Query(default="", max_length=200),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # 手动解析 multipart：兼容任意字段名（file/files），旧缓存客户端也不报 Field required
    form = await request.form()
    uploads = []
    for _key, value in form.multi_items():
        if hasattr(value, "read") and hasattr(value, "filename"):  # UploadFile
            content = await value.read()
            uploads.append((value.filename or "未命名文件", content, value.content_type or ""))
    if not uploads:
        raise ValidationError("未选择任何文件")
    docs = save_document_bulk(
        db,
        user,
        project_id,
        uploads=uploads,
        note=note,
    )
    total = sum(d.size for d in docs)
    record_audit(
        db, user, "upload_document",
        object_type="document", object_id=docs[0].id if docs else None,
        object_name=docs[0].original_name if docs else "",
        detail=f"项目 #{project_id}；上传 {len(docs)} 个文件（含压缩包解压展开），共 {total} 字节"
               + (f"；备注：{note}" if note else ""),
        ip=client_ip(request),
    )
    return {
        "count": len(docs),
        "total_size": total,
        "documents": [
            {
                "id": d.id,
                "project_id": d.project_id,
                "original_name": d.original_name,
                "size": d.size,
                "note": d.note,
            }
            for d in docs
        ],
    }


@router.get("/projects/{project_id}/documents", response_model=list[dict], summary="文档列表（按部门可见）")
def get_documents(project_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return list_documents(db, user, project_id)


@router.get("/documents/tree", response_model=list[dict], summary="进度文档树（部门 → 员工 → 文档）")
def get_document_tree(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return list_document_tree(db, user)


@router.get("/documents/{document_id}/download", summary="下载文档")
def download_document(
    document_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    doc = get_document_file(db, document_id)
    if not _can_view_document(db, user, doc):
        # 文档按部门可见：无权部门直接 404，不暴露存在性
        from app.errors import NotFoundError

        raise NotFoundError("文档不存在或已被删除")
    path = settings.UPLOAD_DIR / doc.stored_name
    if not path.is_file():
        from app.errors import NotFoundError

        raise NotFoundError("文件已丢失，请联系管理员")
    # 审计：下载行为可追溯（谁在何时取走了哪份文件）
    record_audit(
        db, user, "download_document",
        object_type="document", object_id=document_id, object_name=doc.original_name,
        detail=f"项目 #{doc.project_id}",
        ip=client_ip(request),
    )
    return FileResponse(
        path,
        filename=doc.original_name,
        media_type=doc.content_type or "application/octet-stream",
    )


@router.delete("/documents/{document_id}", status_code=204, summary="删除文档")
def remove_document(
    document_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    doc = get_document_file(db, document_id)  # 先取名称供审计（不存在则 404）
    delete_document(db, user, document_id)
    record_audit(
        db, user, "delete_document",
        object_type="document", object_id=document_id, object_name=doc.original_name,
        detail=f"项目 #{doc.project_id}",
        ip=client_ip(request),
    )


class BulkDeleteIn(BaseModel):
    user_id: int | None = Field(default=None, description="上传人 ID")
    date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$", description="上传日期（本地）")


class BulkDeleteIdsIn(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=500, description="要删除的文档 ID 列表")


@router.post("/documents/bulk-delete-ids", response_model=dict, summary="按 ID 列表批量删除文档（多选删除）")
def bulk_delete_ids(
    payload: BulkDeleteIdsIn,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    result = bulk_delete_by_ids(db, user, payload.ids)
    record_audit(
        db, user, "documents_bulk_delete_ids_log",
        object_type="document", object_name=f"count={result['deleted']}",
        detail=f"多选删除 {result['deleted']} 份文档（{result['freed_mb']} MB）",
        ip=client_ip(request),
    )
    return result


@router.get("/admin/documents/bulk-stats", response_model=dict, summary="批量删除前预览统计（管理员）")
def bulk_stats(
    user_id: int | None = None,
    date: str | None = None,
    admin: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    return bulk_document_stats(db, user_id, date)


@router.post("/admin/documents/bulk-delete", response_model=dict, summary="按上传人/日期批量删除（管理员）")
def bulk_delete(
    payload: BulkDeleteIn,
    request: Request,
    admin: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    result = bulk_delete_documents(db, admin, payload.user_id, payload.date)
    record_audit(
        db, admin, "documents_bulk_delete_log",
        object_type="document", object_name=f"user_id={payload.user_id}, date={payload.date}",
        detail=f"批量删除 {result['deleted']} 份文档（{result['freed_mb']} MB）",
        ip=client_ip(request),
    )
    return result
