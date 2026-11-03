"""部门概览路由：全员可读，用于主页部门导航与部门页面。"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.security import get_current_user
from app.services import list_departments_overview

router = APIRouter(prefix="/api/departments", tags=["departments"])


@router.get("", response_model=list[dict], summary="部门概览（含人数/项目/任务统计，员工仅计可见项目）")
def get_departments(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return list_departments_overview(db, user)
