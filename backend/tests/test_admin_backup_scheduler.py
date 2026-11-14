"""管理后台、迁移清理、备份、调度租约与时区测试。"""

from app.migrate import cleanup_orphan_rows
from app.services import cleanup_orphan_files
from app.models import JobRun


class TestAdmin:
    def test_create_user_writes_department_relations(self, admin):
        """核实 create_user 同时写 users.department_id 与 user_departments（DOC-001 修正的事实）。"""
        from app.database import SessionLocal
        from app.models import UserDepartment

        import random
        import string

        suffix = "".join(random.choices(string.ascii_lowercase, k=8))
        r = admin.post("/api/admin/users", json={
            "username": f"dept-{suffix}", "display_name": "部门关联验证", "password": "Dept#12345678",
            "role": "employee", "department_ids": [2]})
        assert r.status_code in (200, 201)
        uid = r.json()["id"]
        db = SessionLocal()
        rows = db.query(UserDepartment).filter(UserDepartment.user_id == uid).all()
        db.close()
        assert [x.department_id for x in rows] == [2], "建号应写入 user_departments 关联"
        admin.delete(f"/api/admin/users/{uid}")

    def test_password_min_length_8(self, admin):
        r = admin.post("/api/admin/users", json={
            "username": "short-pw", "display_name": "短密码", "password": "a123456",
            "role": "employee"})
        assert 400 <= r.status_code < 500, "密码最短 8 位"


class TestMigrateOrphanCleanup:
    def test_cleanup_orphan_rows_idempotent(self):
        first = cleanup_orphan_rows()
        second = cleanup_orphan_rows()
        assert sum(second.values()) == 0, "二次执行应无孤立行（幂等）"

    def test_cleanup_orphan_files_idempotent(self):
        first = cleanup_orphan_files()
        second = cleanup_orphan_files()
        assert second["removed"] == 0, "二次执行应无新增清理（幂等）"


class TestBackup:
    def test_backup_create_list_restore_cycle(self, admin):
        r = admin.post("/api/admin/backups")
        assert r.status_code in (200, 201), "创建备份"
        name = r.json().get("filename") or (r.json().get("backups") or [{}])[0].get("filename")
        lst = admin.get("/api/admin/backups").json()
        items = lst if isinstance(lst, list) else lst.get("backups", [])
        assert any((b.get("filename") or b.get("name")) == name for b in items), "备份应出现在列表"
        # 恢复演练：恢复刚创建的备份（同一数据，应成功）
        rr = admin.post("/api/admin/backups/restore", json={"filename": name})
        assert rr.status_code == 200, f"恢复失败：{rr.text[:150]}"
        # 健康检查确认服务恢复后正常
        assert admin.get("/api/health").status_code == 200

    def test_backup_rejects_path_traversal(self, admin):
        r = admin.post("/api/admin/backups/restore", json={"filename": "../../etc/passwd"})
        assert 400 <= r.status_code < 500, "路径穿越必须被拒绝"


class TestSchedulerLease:
    def test_job_run_lease_unique(self, db=None):
        """JOB-001：同 (job_name, run_day) 二次插入必须被唯一约束拒绝。"""
        from sqlalchemy.exc import IntegrityError

        from app.database import SessionLocal

        db = SessionLocal()
        db.add(JobRun(job_name="test-lease", run_day="2026-01-01"))
        db.commit()
        db.add(JobRun(job_name="test-lease", run_day="2026-01-01"))
        try:
            db.commit()
            raised = False
        except IntegrityError:
            db.rollback()
            raised = True
        n = db.query(JobRun).filter(JobRun.job_name == "test-lease").count()
        db.query(JobRun).filter(JobRun.job_name == "test-lease").delete()
        db.commit()
        db.close()
        assert raised and n == 1, "租约唯一约束应保证每日只执行一次"


class TestPerformancePeriod:
    def test_doc_metrics_period_filter(self, admin):
        """FUNC-001：历史周期文档扫描按 uploaded_at 过滤（未来周期不受历史数据污染的反向验证）。"""
        import random
        import string

        from app.performance import _doc_metrics
        from app.database import SessionLocal

        suffix = "".join(random.choices(string.ascii_lowercase, k=6))
        demo_pid = None
        demo_dept = None
        for p in admin.get("/api/projects").json():
            if p["name"].startswith("OpenGantt"):
                demo_pid = p["id"]
                demo_dept = p.get("department_id")
        # perf 用户加入演示项目部门（部门成员才有上传权）
        r = admin.post("/api/admin/users", json={
            "username": f"perf-{suffix}", "display_name": "绩效文档", "password": "Perf#12345678",
            "role": "employee", "department_ids": [demo_dept]})
        uid = r.json()["id"]
        files = [("files", ("绩效佐证.txt", __import__("io").BytesIO(b"v"), "text/plain"))]
        # 以 perf 用户身份上传（_doc_metrics 按 uploader_id 过滤）
        # 员工可见性=负责或名下有任务：先给 perf 用户安排一个任务使其可见该项目
        rt = admin.post(f"/api/projects/{demo_pid}/tasks", json={
            "name": "perf-可见性任务", "start_date": "2026-11-01", "end_date": "2026-11-30",
            "assignee_ids": [uid]})
        tid = rt.json()["id"]
        from fastapi.testclient import TestClient

        from app.main import app

        with TestClient(app) as c:
            c.post("/api/auth/login", json={
                "username": f"perf-{suffix}", "password": "Perf#12345678"})
            up = c.post(f"/api/projects/{demo_pid}/documents", files=files)
        doc_id = (up.json()["documents"] if isinstance(up.json(), dict) else up.json())[0]["id"]
        # 上传于 2026-11：查历史周期 2026-01 → 应为 0
        db = SessionLocal()
        past = _doc_metrics(db, uid, end="2026-01-31")
        current = _doc_metrics(db, uid, end="2026-12-31")
        db.close()
        assert past["doc_total"] == 0, "历史周期不得包含周期后上传的文档"
        assert current["doc_total"] >= 1
        admin.delete(f"/api/documents/{doc_id}")
        admin.delete(f"/api/projects/{demo_pid}/tasks/{tid}")
        admin.delete(f"/api/admin/users/{uid}")


class TestSecurityDefaults:
    def test_login_rate_limit(self, client):
        codes = []
        for _ in range(6):
            r = client.post("/api/auth/login", json={"username": "rate-test", "password": "wrong-pass-123"})
            codes.append(r.status_code)
        assert codes[-1] in (400, 422), "第 6 次应触发限速"
        assert all(c in (401, 400, 422) for c in codes)

    def test_password_min_length_8_on_change(self, employee):
        r = employee.post("/api/auth/change-password", json={
            "old_password": "123456", "new_password": "short1"})
        assert 400 <= r.status_code < 500, "新密码最短 8 位"
