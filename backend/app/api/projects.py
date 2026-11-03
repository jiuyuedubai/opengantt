"""项目路由：控制器只做解析请求、调用服务、格式化响应。"""

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.schemas import ProjectCreate, ProjectUpdate
from app.security import client_ip, get_current_user
from app.services import (
    create_project,
    delete_project,
    get_project,
    list_projects,
    migrate_project,
    record_audit,
    update_project,
)

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.get("", response_model=list[dict], summary="项目列表（含权限标记）")
def get_projects(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return list_projects(db, user)


@router.post("", response_model=dict, status_code=201, summary="新建项目")
def post_project(
    payload: ProjectCreate,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    created = create_project(db, user, payload)
    record_audit(
        db, user, "create_project",
        object_type="project", object_id=created["id"], object_name=created["name"],
        detail=f"归属部门：{created.get('department_name') or '未分部门'}；负责人：{created.get('owner_name') or '—'}",
        ip=client_ip(request),
    )
    return created


class ProjectMigrateIn(BaseModel):
    department_id: int = Field(description="目标部门 ID")


@router.post("/{project_id}/migrate", response_model=dict, summary="迁移项目到其他部门")
def migrate_project_route(
    project_id: int,
    payload: ProjectMigrateIn,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project = get_project(db, project_id)
    old_name = project.department.name if project.department else "未设置部门"
    result = migrate_project(db, user, project_id, payload.department_id)
    record_audit(
        db, user, "project_migrate",
        object_type="project", object_id=project_id, object_name=result["name"],
        detail=f"项目迁移：{old_name} → {result.get('department_name') or '未分部门'}",
        ip=client_ip(request),
    )
    return result


@router.patch("/{project_id}", response_model=dict, summary="更新项目")
def patch_project(
    project_id: int,
    payload: ProjectUpdate,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    updated = update_project(db, user, project_id, payload)
    changed = [k for k, v in payload.model_dump().items() if v is not None]
    record_audit(
        db, user, "update_project",
        object_type="project", object_id=project_id, object_name=updated["name"],
        detail="修改字段：" + "、".join(changed) if changed else "",
        ip=client_ip(request),
    )
    return updated


@router.delete("/{project_id}", status_code=204, summary="删除项目")
def delete_project_route(
    project_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project = get_project(db, project_id)  # 先取名称与级联数量供审计（不存在则 404）
    task_count = len(project.tasks)
    doc_count = len(project.documents)
    delete_project(db, user, project_id)
    record_audit(
        db, user, "delete_project",
        object_type="project", object_id=project_id, object_name=project.name,
        detail=f"级联删除 {task_count} 个任务、{doc_count} 份文档",
        ip=client_ip(request),
    )
