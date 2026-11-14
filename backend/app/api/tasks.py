"""任务路由：含拖拽后的批量更新端点与权限校验。"""

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import NotFoundError, PermissionDeniedError, ValidationError
from app.models import User
from app.schemas import TaskBulkUpdate, TaskCreate, TaskOut, TaskUpdate
from app.security import client_ip, get_current_user
from app.services import (
    _resolve_task,
    _assignee_ids_by_task,
    bulk_update_tasks,
    create_task,
    delete_task,
    ensure_can_edit_task,
    _blocked_reason_for,
    ensure_can_view_project,
    get_project,
    list_progress_logs,
    list_tasks_with_note,
    record_audit,
    update_task,
)
from app.wecom import send_task_remind

router = APIRouter(prefix="/api", tags=["tasks"])


@router.get("/projects/{project_id}/tasks", response_model=list[TaskOut], summary="任务列表（含当日进度说明）")
def get_tasks(project_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ensure_can_view_project(db, user, get_project(db, project_id))
    return list_tasks_with_note(db, project_id, user=user)


@router.get(
    "/projects/{project_id}/progress-logs",
    response_model=list[dict],
    summary="项目进度记录（每日快照）",
)
def get_progress_logs(
    project_id: int,
    date: str | None = Query(default=None, description="按日过滤 YYYY-MM-DD"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if date:
        from datetime import date as _date

        try:
            _date.fromisoformat(date)
        except ValueError:
            raise ValidationError("日期必须为 YYYY-MM-DD 格式")
    ensure_can_view_project(db, user, get_project(db, project_id))
    return list_progress_logs(db, project_id, log_date=date)


@router.post("/projects/{project_id}/tasks", response_model=TaskOut, status_code=201, summary="新建任务")
def post_task(
    project_id: int,
    payload: TaskCreate,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    task = create_task(db, user, project_id, payload)
    record_audit(
        db, user, "create_task",
        object_type="task", object_id=task.id, object_name=task.name,
        detail=f"项目 #{project_id}；{task.start_date} ~ {task.end_date}；进度 {task.progress}%",
        ip=client_ip(request),
    )
    # 返回带 assignee_ids 的完整视图（TaskOut ORM 序列化取不到多对多字段）
    return next(t for t in list_tasks_with_note(db, project_id, user=user) if t["id"] == task.id)


@router.patch(
    "/projects/{project_id}/tasks/bulk",
    response_model=list[TaskOut],
    summary="批量更新任务",
)
def patch_tasks_bulk(
    project_id: int,
    payload: TaskBulkUpdate,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    changes_by_id: dict[int, TaskUpdate] = {}
    for change in payload.changes:
        if change.id is None:
            raise ValidationError("批量更新的每一项都必须携带任务 id")
        if change.id in changes_by_id:
            raise ValidationError(f"任务 {change.id} 在批量更新中重复出现")
        changes_by_id[change.id] = change
    tasks = bulk_update_tasks(db, user, project_id, changes_by_id)
    # 审计：批量更新合并为一条（拖拽保存频繁，避免日志刷屏）
    fields = sorted(
        {k for c in changes_by_id.values() for k, v in c.model_dump().items() if v is not None and k != "id"}
    )
    ids = ",".join("#" + str(t.id) for t in sorted(tasks, key=lambda x: x.id))
    record_audit(
        db, user, "bulk_update_tasks",
        object_type="task", object_id=project_id,
        detail=f"批量更新 {len(tasks)} 项（{ids}）；字段：{'、'.join(fields) or '—'}",
        ip=client_ip(request),
    )
    # 返回带 assignee_ids 的完整视图（TaskOut ORM 序列化取不到多对多字段）
    updated_ids = {t.id for t in tasks}
    out = [t for t in list_tasks_with_note(db, project_id, user=user) if t["id"] in updated_ids]
    return sorted(out, key=lambda t: t["position"])


@router.get(
    "/projects/{project_id}/tasks/{task_id}",
    response_model=TaskOut,
    summary="任务详情",
)
def get_task(project_id: int, task_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project = get_project(db, project_id)
    # 权限边界：无项目可见权时统一返回 404，不暴露任务存在性
    try:
        ensure_can_view_project(db, user, project)
    except PermissionDeniedError:
        raise NotFoundError("任务不存在")
    task = _resolve_task(db, project_id, task_id)
    out = TaskOut.model_validate(task)
    if out.status == "blocked":
        out.blocked_reason = _blocked_reason_for(db, task.id)
    return out


@router.patch(
    "/projects/{project_id}/tasks/{task_id}", response_model=TaskOut, summary="更新任务"
)
def patch_task(
    project_id: int,
    task_id: int,
    payload: TaskUpdate,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    task = update_task(db, user, project_id, task_id, payload)
    changed = [k for k, v in payload.model_dump().items() if v is not None and k != "id"]
    record_audit(
        db, user, "update_task",
        object_type="task", object_id=task_id, object_name=task.name,
        detail=f"项目 #{project_id}；修改字段：{'、'.join(changed) or '—'}",
        ip=client_ip(request),
    )
    # 返回带 assignee_ids 的完整视图（TaskOut ORM 序列化取不到多对多字段）
    return next(t for t in list_tasks_with_note(db, project_id, user=user) if t["id"] == task_id)


@router.delete(
    "/projects/{project_id}/tasks/{task_id}", status_code=204, summary="删除任务"
)
def delete_task_route(
    project_id: int,
    task_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    task = _resolve_task(db, project_id, task_id)  # 先取名称供审计（不存在则 404）
    delete_task(db, user, project_id, task_id)
    record_audit(
        db, user, "delete_task",
        object_type="task", object_id=task_id, object_name=task.name,
        detail=f"从项目 #{project_id} 删除",
        ip=client_ip(request),
    )


@router.post(
    "/projects/{project_id}/tasks/{task_id}/remind",
    summary="在企业微信群提醒任务负责人（@其企微手机号）",
)
def remind_task_route(
    project_id: int,
    task_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project = get_project(db, project_id)
    task = _resolve_task(db, project_id, task_id)
    ensure_can_edit_task(db, user, task, project)
    result = send_task_remind(db, task, project)
    if result.get("ok"):
        by_mobile = "、".join(result.get("mentioned_by_mobile") or [])
        detail = f"提醒已发送（@{by_mobile}）" if by_mobile else "提醒已发送（无人配置企微手机号，未@）"
    else:
        detail = f"提醒发送失败/跳过：{result.get('reason') or result.get('error') or '未知原因'}"
    record_audit(
        db, user, "task_remind",
        object_type="task", object_id=task_id, object_name=task.name,
        detail=detail,
        ip=client_ip(request),
    )
    return result
