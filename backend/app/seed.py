"""首次启动写入种子数据：内置管理员、六个部门、演示账号与演示项目。"""

import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Department, Project, Task, User
from app.security import hash_password

logger = logging.getLogger("opengantt.seed")

DEMO_DEPARTMENTS = [
    ("人事行政部", "人事、行政与后勤事务"),
    ("财务部", "财务核算、预算与资金管理"),
    ("总经办", "总经理办公室与公司战略协同"),
    ("商务运营部", "商务合作与日常运营支撑"),
    ("销售部", "客户开拓、签约与回款"),
    ("项管中心", "项目管理中心：项目排期与交付管控"),
]

# (username, password, 姓名, role, 部门)
DEMO_USERS = [
    (settings.ADMIN_USERNAME, settings.ADMIN_PASSWORD, "系统管理员", "admin", None),
    ("zhangsan", "123456", "张三", "supervisor", "项管中心"),
    ("lisi", "123456", "李四", "employee", "商务运营部"),
    ("wangwu", "123456", "王五", "employee", "项管中心"),
]

DEMO_PROJECT = "OpenGantt 演示项目"

DEMO_TASKS: list[dict] = [
    {"name": "需求分析与立项", "start_date": "2026-10-12", "end_date": "2026-10-16", "progress": 100, "assignee": "张三", "deps": "", "status": "done"},
    {"name": "架构与技术选型", "start_date": "2026-10-17", "end_date": "2026-10-21", "progress": 80, "assignee": "李四", "deps": "1", "status": "in_progress"},
    {"name": "数据库设计", "start_date": "2026-10-22", "end_date": "2026-10-27", "progress": 40, "assignee": "王五", "deps": "2", "status": "in_progress"},
    {"name": "后端接口开发", "start_date": "2026-10-28", "end_date": "2026-11-08", "progress": 0, "assignee": "李四", "deps": "3", "status": "not_started"},
    {"name": "前端界面开发", "start_date": "2026-10-28", "end_date": "2026-11-10", "progress": 0, "assignee": "赵六", "deps": "3", "status": "not_started"},
    {"name": "联调与测试", "start_date": "2026-11-11", "end_date": "2026-11-18", "progress": 0, "assignee": "张三", "deps": "4,5", "status": "not_started"},
    {"name": "部署上线", "start_date": "2026-11-19", "end_date": "2026-11-20", "progress": 0, "assignee": "王五", "deps": "6", "status": "not_started"},
    {"name": "试运行与验收", "start_date": "2026-11-21", "end_date": "2026-11-28", "progress": 0, "assignee": "全体", "deps": "7", "status": "not_started"},
]


def seed(db: Session) -> None:
    if not settings.seed_demo_data:
        return

    # 部门
    dept_count = db.execute(select(func.count(Department.id))).scalar()
    if not dept_count:
        logger.info("首次启动：写入部门数据")
        for name, desc in DEMO_DEPARTMENTS:
            db.add(Department(name=name, description=desc))
        db.flush()

    # 账号
    user_count = db.execute(select(func.count(User.id))).scalar()
    if not user_count:
        logger.info("首次启动：写入内置账号（请登录后尽快修改默认密码）")
        dept_map = {d.name: d.id for d in db.execute(select(Department)).scalars()}
        for username, password, display, role, dept_name in DEMO_USERS:
            db.add(
                User(
                    username=username,
                    password_hash=hash_password(password),
                    display_name=display,
                    role=role,
                    department_id=dept_map.get(dept_name) if dept_name else None,
                )
            )
        db.flush()

    # 孤儿项目修复：历史数据经迁移后可能缺少归属，默认挂到项管中心 + 首位主管
    orphans = db.execute(
        select(Project).where(Project.owner_id.is_(None), Project.department_id.is_(None))
    ).scalars().all()
    if orphans:
        dept_map = {d.name: d.id for d in db.execute(select(Department)).scalars()}
        supervisor = db.execute(
            select(User).where(User.role == "supervisor").order_by(User.id)
        ).scalars().first()
        repair_dept = dept_map.get("项管中心") or next(iter(dept_map.values()), None)
        for project in orphans:
            project.owner_id = supervisor.id if supervisor else None
            project.department_id = repair_dept
        logger.info("种子：为 %d 个无归属历史项目补充负责人与部门", len(orphans))
        db.flush()

    # 演示项目（归属项管中心，负责人 zhangsan）
    project_count = db.execute(select(func.count(Project.id))).scalar()
    if not project_count:
        logger.info("首次启动：写入演示项目")
        dept_map = {d.name: d.id for d in db.execute(select(Department)).scalars()}
        owner = db.execute(select(User).where(User.username == "zhangsan")).scalar_one_or_none()
        project = Project(
            name=DEMO_PROJECT,
            description="开箱即用的演示项目：一个典型的软件研发排期，可随意编辑或删除。",
            owner_id=owner.id if owner else None,
            department_id=dept_map.get("项管中心"),
        )
        db.add(project)
        db.flush()
        for idx, spec in enumerate(DEMO_TASKS):
            db.add(
                Task(
                    project_id=project.id,
                    name=spec["name"],
                    start_date=spec["start_date"],
                    end_date=spec["end_date"],
                    progress=spec["progress"],
                    dependencies=spec["deps"],
                    assignee=spec["assignee"],
                    status=spec["status"],
                    position=idx,
                )
            )
    db.commit()
