"""每日任务路由：个人周期任务清单（日期恒为当天，数据持久化）。"""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.schemas import DailyTaskCreate, DailyTaskUpdate
from app.security import client_ip, get_current_user
from app.services import (
    create_daily_task,
    delete_daily_task,
    list_daily_tasks,
    record_audit,
    update_daily_task,
)

router = APIRouter(prefix="/api/daily-tasks", tags=["daily-tasks"])


@router.get("", response_model=list[dict], summary="我的每日任务列表（日期恒为当天）")
def get_daily_tasks(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return list_daily_tasks(db, user)


@router.post("", response_model=dict, status_code=201, summary="新增每日任务")
def post_daily_task(
    payload: DailyTaskCreate,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    task = create_daily_task(db, user, payload)
    record_audit(
        db, user, "create_daily_task",
        object_type="daily_task", object_id=task["id"], object_name=task["name"],
        ip=client_ip(request),
    )
    return task


@router.patch("/{task_id}", response_model=dict, summary="修改每日任务（改名/备注/勾选今日完成）")
def patch_daily_task(
    task_id: int,
    payload: DailyTaskUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return update_daily_task(db, user, task_id, payload)


@router.delete("/{task_id}", status_code=204, summary="删除每日任务")
def remove_daily_task(
    task_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    delete_daily_task(db, user, task_id)
