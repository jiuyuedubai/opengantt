"""统计路由：驾驶舱总览、员工投入度、项目进度趋势。仅主管与管理员可见。"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.security import require_roles
from app.services import (
    stats_activity_matrix,
    stats_overview,
    stats_progress_trend,
    stats_user_activity,
)

router = APIRouter(prefix="/api/stats", tags=["stats"], dependencies=[Depends(require_roles("admin", "supervisor"))])


@router.get("/overview", summary="驾驶舱总览（部门聚合/状态分布/逾期停滞清单）")
def overview(db: Session = Depends(get_db)):
    return stats_overview(db)


@router.get("/activity-matrix", summary="活跃热力图（每人每日更新次数矩阵）")
def activity_matrix(
    days: int = Query(default=14, ge=1, le=31),
    db: Session = Depends(get_db),
):
    return stats_activity_matrix(db, days=days)


@router.get("/user-activity", summary="员工投入度分析（近 N 天）")
def user_activity(
    days: int = Query(default=14, ge=1, le=90),
    db: Session = Depends(get_db),
):
    return stats_user_activity(db, days=days)


@router.get("/progress-trend", summary="进度趋势（实际 vs 期望；project_id=0 或缺省聚合全部项目）")
def progress_trend(
    project_id: int = Query(default=0, description="项目 ID；0 表示全部项目"),
    db: Session = Depends(get_db),
):
    return stats_progress_trend(db, project_id or None)
