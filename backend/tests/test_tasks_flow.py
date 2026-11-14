"""项目/任务 CRUD、依赖环与状态流转测试。"""

BAD_CYCLE = "依赖成环"


class TestTaskCrud:
    def test_create_and_update(self, admin, demo_pid, task_factory):
        task = task_factory("CRUD-创建", progress=0)
        r = admin.patch(f"/api/projects/{demo_pid}/tasks/{task['id']}", json={
            "name": "CRUD-更新", "progress": 50})
        assert r.status_code == 200
        assert r.json()["progress"] == 50

    def test_delete_task(self, admin, demo_pid):
        r = admin.post(f"/api/projects/{demo_pid}/tasks", json={
            "name": "CRUD-待删", "start_date": "2026-11-01", "end_date": "2026-11-30"})
        tid = r.json()["id"]
        assert admin.delete(f"/api/projects/{demo_pid}/tasks/{tid}").status_code in (200, 204)
        # 再查应 404
        assert admin.get(f"/api/projects/{demo_pid}/tasks/{tid}").status_code == 404

    def test_date_order_validation(self, admin, demo_pid):
        r = admin.post(f"/api/projects/{demo_pid}/tasks", json={
            "name": "日期倒挂", "start_date": "2026-11-10", "end_date": "2026-11-01"})
        assert 400 <= r.status_code < 500, "开始日期晚于结束必须被拒绝"


class TestDependencies:
    def test_dependency_cycle_rejected(self, admin, demo_pid, task_factory):
        a = task_factory("依赖-A")
        b = task_factory("依赖-B", dependencies=str(a["id"]))
        # 让 A 依赖 B → 成环
        r = admin.patch(f"/api/projects/{demo_pid}/tasks/{a['id']}", json={"dependencies": str(b["id"])})
        assert 400 <= r.status_code < 500, "依赖成环必须被拒绝"
        assert "环" in r.text or "cycle" in r.text.lower()


class TestStatusFlow:
    def test_blocked_requires_reason(self, admin, demo_pid, task_factory):
        task = task_factory("状态-转阻塞")
        r = admin.patch(f"/api/projects/{demo_pid}/tasks/{task['id']}", json={"status": "blocked"})
        assert 400 <= r.status_code < 500, "转阻塞不填原因必须被拒绝"
        r2 = admin.patch(f"/api/projects/{demo_pid}/tasks/{task['id']}", json={
            "status": "blocked", "status_reason": "等待外部接口"})
        assert r2.status_code == 200
        assert r2.json()["status"] == "blocked"

    def test_blocked_reason_visible_in_task_out(self, admin, demo_pid, task_factory):
        task = task_factory("状态-原因可见", progress=30)
        admin.patch(f"/api/projects/{demo_pid}/tasks/{task['id']}", json={
            "status": "blocked", "status_reason": "等待授权"})
        r = admin.get(f"/api/projects/{demo_pid}/tasks/{task['id']}")
        assert r.json()["blocked_reason"] == "等待授权"

    def test_blocked_reason_updatable_while_blocked(self, admin, demo_pid, task_factory):
        task = task_factory("状态-原因修订", progress=30)
        admin.patch(f"/api/projects/{demo_pid}/tasks/{task['id']}", json={
            "status": "blocked", "status_reason": "原因一"})
        r = admin.patch(f"/api/projects/{demo_pid}/tasks/{task['id']}", json={
            "status": "blocked", "status_reason": "原因二"})
        assert r.json()["blocked_reason"] == "原因二"

    def test_cancel_clears_blocked_reason(self, admin, demo_pid, task_factory):
        """取消后 blocked_reason 应清空（任务不再处于阻塞状态）。"""
        task = task_factory("状态-取消清空", progress=30)
        admin.patch(f"/api/projects/{demo_pid}/tasks/{task['id']}", json={
            "status": "blocked", "status_reason": "临时阻塞"})
        r = admin.patch(f"/api/projects/{demo_pid}/tasks/{task['id']}", json={"status": "cancelled"})
        assert r.status_code == 200
        assert r.json()["blocked_reason"] == ""

    def test_overdue_uses_today_as_baseline(self, admin, demo_pid, task_factory):
        """逾期判断以今天为基准：未来截止的任务不得误判逾期。"""
        from datetime import date, timedelta

        future_end = (date.today() + timedelta(days=10)).isoformat()
        task = task_factory("状态-未来截止", progress=10, end_date=future_end)
        r = admin.get(f"/api/projects/{demo_pid}/tasks/{task['id']}")
        assert r.json()["status"] == "not_started"  # 未到期未完成，不算逾期异常
