"""项目进度文档路由：上传、列表、下载、删除。"""

from fastapi import APIRouter, Depends, Query, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import User
from app.security import client_ip, get_current_user
from app.services import (
    _can_view_document,
    delete_document,
    get_document_file,
    list_document_tree,
    list_documents,
    record_audit,
    save_document,
)

router = APIRouter(prefix="/api", tags=["documents"])


@router.post("/projects/{project_id}/documents", status_code=201, summary="上传进度文档")
def upload_document(
    project_id: int,
    request: Request,
    file: UploadFile,
    note: str = Query(default="", max_length=200),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    content = file.file.read()
    doc = save_document(
        db,
        user,
        project_id,
        original_name=file.filename or "未命名文件",
        content=content,
        content_type=file.content_type or "",
        note=note,
    )
    record_audit(
        db, user, "upload_document",
        object_type="document", object_id=doc.id, object_name=doc.original_name,
        detail=f"项目 #{project_id}；{doc.size} 字节" + (f"；备注：{note}" if note else ""),
        ip=client_ip(request),
    )
    return {
        "id": doc.id,
        "project_id": doc.project_id,
        "original_name": doc.original_name,
        "size": doc.size,
        "content_type": doc.content_type,
        "note": doc.note,
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
