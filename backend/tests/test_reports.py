"""日报/周报生成与阻塞同步测试（对应 11-09/11-10 的状态同步修复）。"""

import pytest


@pytest.fixture()
def blocked_then_cancel_task(admin, demo_pid, task_factory):
    """造一个转阻塞（带原因）→ 今日进度 → 取消的任务，返回 (tid, reason)。"""
    task = task_factory("日志-阻塞取消", progress=50)
    admin.patch(f"/api/projects/{demo_pid}/tasks/{task['id']}", json={
        "progress": 50, "status": "blocked", "status_reason": "等待供应商提供备件清单"})
    admin.patch(f"/api/projects/{demo_pid}/tasks/{task['id']}", json={"progress": 50})  # 今日进度
    return task


class TestDailyReport:
    def test_blocked_task_appears_with_reason(self, admin, supervisor):
        r = supervisor.get("/api/reports/daily")  # 主管今日日志
        assert r.status_code == 200

    def test_cancelled_task_removed_from_report(self, admin, demo_pid, blocked_then_cancel_task):
        """取消后（实时生成）日报不再包含该任务的阻塞/进行中记录。"""
        tid = blocked_then_cancel_task["id"]
        admin.patch(f"/api/projects/{demo_pid}/tasks/{tid}", json={"status": "cancelled"})
        me = admin.get("/api/auth/me").json()
        # zhangsan 的日志由主管会话生成；admin 用自己的（admin 不名下任务）——改用 zhangsan 查询
        from app.database import SessionLocal
        from app.services import generate_daily_report
        from app.models import User

        db = SessionLocal()
        u = db.query(User).filter(User.username == "zhangsan").first()
        md = generate_daily_report(db, u, __import__("app.services", fromlist=["_today_str"])._today_str())
        db.close()
        assert "日志-阻塞取消" not in md, "取消后任务不应出现在日报"
        assert "等待供应商提供备件清单" not in md, "取消后阻塞原因不应残留"

    def test_blocked_task_shows_reason(self, admin, demo_pid, task_factory):
        from app.database import SessionLocal
        from app.services import generate_daily_report
        from app.models import User

        task = task_factory("日志-阻塞展示", progress=40)
        admin.patch(f"/api/projects/{demo_pid}/tasks/{task['id']}", json={
            "progress": 40, "status": "blocked", "status_reason": "等待授权审批"})
        admin.patch(f"/api/projects/{demo_pid}/tasks/{task['id']}", json={"progress": 40})
        db = SessionLocal()
        u = db.query(User).filter(User.username == "zhangsan").first()
        md = generate_daily_report(db, u, __import__("app.services", fromlist=["_today_str"])._today_str())
        db.close()
        assert "日志-阻塞展示" in md and "等待授权审批" in md


class TestWeeklyReport:
    def test_blocked_items_deduped(self, admin, demo_pid, task_factory):
        """同一任务多天阻塞 → 周报阻塞项只出现一条。"""
        from app.database import SessionLocal
        from app.services import generate_weekly_report
        from app.models import User

        task = task_factory("周报-阻塞去重", progress=20)
        admin.patch(f"/api/projects/{demo_pid}/tasks/{task['id']}", json={
            "progress": 20, "status": "blocked", "status_reason": "原因A"})
        admin.patch(f"/api/projects/{demo_pid}/tasks/{task['id']}", json={
            "progress": 20, "status": "blocked", "status_reason": "原因B"})  # blocked→blocked 原因修订

        db = SessionLocal()
        u = db.query(User).filter(User.username == "zhangsan").first()
        md = generate_weekly_report(db, u, __import__("app.services", fromlist=["_today_str"])._today_str())
        db.close()
        i3 = md.find("三、遇到的问题")
        i4 = md.find("四、下周工作计划")
        seg = md[i3:i4]
        assert seg.count("周报-阻塞去重") == 1, f"阻塞项段应去重为一条（实际 {seg.count('周报-阻塞去重')}）"
        assert "原因B" in seg, "应采用最新原因"
        assert "原因A" not in seg

    def test_next_week_plan_no_duplicate(self, admin, demo_pid, task_factory):
        """同任务两天不同进度 → 下周计划只出现一次（最新进度）。"""
        from app.database import SessionLocal
        from app.services import generate_weekly_report
        from app.models import User

        task = task_factory("周报-计划去重", progress=60)
        admin.patch(f"/api/projects/{demo_pid}/tasks/{task['id']}", json={"progress": 60})
        admin.patch(f"/api/projects/{demo_pid}/tasks/{task['id']}", json={"progress": 80})

        db = SessionLocal()
        u = db.query(User).filter(User.username == "zhangsan").first()
        md = generate_weekly_report(db, u, __import__("app.services", fromlist=["_today_str"])._today_str())
        db.close()
        i4 = md.find("四、下周工作计划")
        seg = md[i4: md.find("────", i4) if md.find("────", i4) > i4 else len(md)]
        assert seg.count("周报-计划去重") == 1, "下周计划同任务应只出现一次"
