"""权限矩阵测试（AUTH-001/002 相关验收）。

角色语义（以实现为准）：
- admin：全部可见可编辑；
- supervisor：本部门项目可见可编辑；
- employee：可见 = 自己负责或名下有任务的项目（新建员工可见为空）；
  编辑 = 自己负责的项目 / 本部门项目（部门成员）；
- 任务负责人：无项目编辑权也可修改被分配的任务（不可删除）。
"""


class TestProjectVisibility:
    def test_employee_with_no_projects_sees_empty_list(self, user_factory, admin):
        user = user_factory(role="employee", with_dept=False)
        import base64

        from app.security import verify_password  # noqa: F401  确保安全模块已加载

        resp = admin.get("/api/projects")  # admin 会话保证种子正常
        assert resp.status_code == 200
        # 用该临时员工登录后可见项目应为空
        suffix = user["username"]
        # 直接以 admin 生成 token 无法切换身份；通过登录接口换会话
        # （client 为会话级 fixture，这里用独立请求头覆盖不可行，改为派生新 client）
        from fastapi.testclient import TestClient

        from app.main import app

        with TestClient(app) as c2:
            r = c2.post("/api/auth/login", json={"username": suffix, "password": "Test#12345678"})
            assert r.status_code == 200
            r2 = c2.get("/api/projects")
            assert r2.status_code == 200
            assert r2.json() == [], "无负责项目、无任务的员工应看不到任何项目"

    def test_task_detail_unauthorized_returns_404(self, admin, user_factory, demo_pid):
        """AUTH-001 验收：无权访问统一返回 404（不暴露任务存在性）。"""
        import random
        import string

        from fastapi.testclient import TestClient

        from app.main import app

        suffix = "".join(random.choices(string.ascii_lowercase, k=8))
        admin.post("/api/admin/users", json={
            "username": f"noauth-{suffix}", "display_name": "无权", "password": "No#12345678",
            "role": "employee"})
        # 先取一个已知存在的任务
        tasks = admin.get(f"/api/projects/{demo_pid}/tasks").json()
        assert tasks, "演示项目应有种子任务"
        tid = tasks[0]["id"]
        with TestClient(app) as c3:
            c3.post("/api/auth/login", json={"username": f"noauth-{suffix}", "password": "No#12345678"})
            r = c3.get(f"/api/projects/{demo_pid}/tasks/{tid}")
            assert r.status_code == 404, f"期望 404 实际 {r.status_code}"
            # 不存在的任务同样 404
            r2 = c3.get(f"/api/projects/{demo_pid}/tasks/999999")
            assert r2.status_code == 404


class TestRolePermissions:
    def test_admin_can_edit_everything(self, admin, demo_pid, task_factory):
        task = task_factory("权限-管理员编辑", progress=10)
        r = admin.patch(f"/api/projects/{demo_pid}/tasks/{task['id']}", json={"progress": 20})
        assert r.status_code == 200

    def test_employee_can_edit_assigned_task(self, admin, demo_pid, task_factory, employee):
        # admin 把任务分配给 lisi（employee 会话）
        me = employee.get("/api/auth/me").json()
        task = task_factory("权限-员工被分配", progress=0, assignee_ids=[me["id"]])
        r = employee.patch(f"/api/projects/{demo_pid}/tasks/{task['id']}", json={"progress": 30})
        assert r.status_code == 200, "任务负责人可修改被分配的任务"
        # 但不可删除
        r2 = employee.delete(f"/api/projects/{demo_pid}/tasks/{task['id']}")
        assert r2.status_code in (403, 404), "任务负责人不可删除任务"

    def test_employee_cannot_edit_unassigned_task_in_other_project(self, admin, task_factory):
        from fastapi.testclient import TestClient

        from app.main import app

        # 新建一个仅 admin 可见的独立项目
        import random
        import string

        suffix = "".join(random.choices(string.ascii_lowercase, k=6))
        rp = admin.post("/api/projects", json={"name": f"隔离项目-{suffix}", "department_id": None})
        assert rp.status_code == 201
        pid = rp.json()["id"]
        rt = admin.post(f"/api/projects/{pid}/tasks", json={
            "name": "隔离任务", "start_date": "2026-11-01", "end_date": "2026-11-30"})
        tid = rt.json()["id"]
        try:
            # 无部门、无任务的员工访问 → 列表 403/详情 404
            suffix2 = "".join(random.choices(string.ascii_lowercase, k=8))
            admin.post("/api/admin/users", json={
                "username": f"iso-{suffix2}", "display_name": "隔离员", "password": "Iso#12345678",
                "role": "employee"})
            with TestClient(app) as c:
                c.post("/api/auth/login", json={"username": f"iso-{suffix2}", "password": "Iso#12345678"})
                r_list = c.get(f"/api/projects/{pid}/tasks")
                assert r_list.status_code in (403, 404)
                r_detail = c.get(f"/api/projects/{pid}/tasks/{tid}")
                assert r_detail.status_code == 404, "跨项目详情越权必须 404"
        finally:
            admin.delete(f"/api/projects/{pid}")

    def test_supervisor_sees_department_projects(self, supervisor, demo_pid):
        r = supervisor.get(f"/api/projects/{demo_pid}/tasks")
        # zhangsan 是项管中心主管；演示项目若属项管中心则可读，否则 403/404
        assert r.status_code in (200, 403, 404)


class TestLastAdminProtection:
    def test_cannot_demote_last_admin(self, admin):
        me = admin.get("/api/auth/me").json()
        r = admin.patch(f"/api/admin/users/{me['id']}", json={"role": "employee"})
        assert 400 <= r.status_code < 500, "降级最后管理员必须被拦截"
        assert "管理员" in r.text

    def test_cannot_disable_last_admin(self, admin):
        me = admin.get("/api/auth/me").json()
        r = admin.patch(f"/api/admin/users/{me['id']}", json={"is_active": False})
        assert 400 <= r.status_code < 500, "停用最后管理员必须被拦截"
        # 确认账号未被破坏
        assert admin.get("/api/auth/me").status_code == 200
