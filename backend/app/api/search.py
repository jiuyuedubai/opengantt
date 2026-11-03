"""全局搜索路由：任务 / 项目 / 人员。登录即可用。"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.security import get_current_user
from app.services import search_all

router = APIRouter(prefix="/api/search", tags=["search"])


@router.get("", summary="全局搜索（任务/项目/人员，按项目可见性过滤）")
def search(
    q: str = Query(min_length=1, max_length=60),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return search_all(db, q.strip(), user)
