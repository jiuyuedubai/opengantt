"""测试基础设施（TEST-001）。

关键隔离原则：
- 每次测试会话使用独立的临时 SQLite 库与临时上传目录，绝不触碰真实数据；
- 环境变量在导入 app 之前写入（config.py 于 import 时读取）；
- 种子数据通过 SEED_DEMO_DATA 生成，账号/项目/任务均有确定 ID。
"""

import os
import tempfile
from pathlib import Path

import pytest

# 在导入 app.* 之前固化测试环境（config.py 于 import 时读取环境变量）
_TMP = tempfile.mkdtemp(prefix="opengantt-test-")
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP}/test.db"
os.environ["UPLOAD_DIR"] = _TMP
os.environ["SEED_DEMO_DATA"] = "true"
os.environ["WECOM_WEBHOOK_URL"] = ""  # 测试不外发
os.environ["WECOM_REMIND_WEBHOOK_URL"] = ""
os.environ["LLM_API_KEY"] = ""
os.environ["JWT_SECRET"] = "test-secret"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client() -> TestClient:
    """未登录的基础 client（供限速等测试构造独立请求）。"""
    with TestClient(app) as c:
        yield c


def _login_client(client: TestClient, username: str, password: str) -> TestClient:
    """独立 client 实例登录（client 参数确保 lifespan 已建表/种子；cookie 各实例独立互不覆盖）。"""
    c = TestClient(app)
    r = c.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, f"登录失败 {username}: {r.status_code} {r.text[:120]}"
    return c


@pytest.fixture(scope="session")
def admin(client):
    """管理员会话（种子 admin/admin123）。"""
    return _login_client(client, "admin", "admin123")


@pytest.fixture(scope="session")
def supervisor(client):
    """主管会话（种子 zhangsan/123456，项管中心）。"""
    return _login_client(client, "zhangsan", "123456")


@pytest.fixture(scope="session")
def employee(client):
    """普通员工会话（种子 lisi/123456）。"""
    return _login_client(client, "lisi", "123456")


@pytest.fixture(scope="session")
def demo_pid(admin) -> int:
    """演示项目 ID（种子内置）。"""
    resp = admin.get("/api/projects")
    assert resp.status_code == 200
    found = [p for p in resp.json() if p["name"].startswith("OpenGantt")]
    if not found:
        me = admin.get("/api/auth/me")
        raise AssertionError(
            f"种子演示项目不存在；当前项目列表：{[p['name'] for p in resp.json()]}；"
            f"当前会话身份：{me.status_code} {me.text[:80]}"
        )
    return found[0]["id"]


@pytest.fixture()
def task_factory(admin, demo_pid):
    """创建临时任务并注册清理（测试结束删除）。"""
    created = []

    def _make(name: str, **fields) -> dict:
        # 默认负责人=zhangsan（种子 uid=2）：日报/周报按"名下任务"聚合，测试任务需归属到查询用户名下
        payload = {"name": name, "start_date": "2026-11-01", "end_date": "2026-11-30",
                   "assignee_ids": [2], **fields}
        resp = admin.post(f"/api/projects/{demo_pid}/tasks", json=payload)
        assert resp.status_code == 201, resp.text[:200]
        task = resp.json()
        created.append(task["id"])
        return task

    yield _make
    for tid in created:
        admin.delete(f"/api/projects/{demo_pid}/tasks/{tid}")


@pytest.fixture()
def user_factory(admin):
    """创建临时账号并注册清理（测试结束删除）。"""
    import random
    import string

    created = []

    def _make(role: str = "employee", with_dept: bool = False) -> dict:
        suffix = "".join(random.choices(string.ascii_lowercase, k=8))
        payload = {
            "username": f"t-{suffix}",
            "display_name": f"临时{role}",
            "password": "Test#12345678",
            "role": role,
        }
        if with_dept:
            payload["department_ids"] = [2]  # 财务部
        resp = admin.post("/api/admin/users", json=payload)
        assert resp.status_code in (200, 201), resp.text[:200]
        user = resp.json()
        created.append(user["id"])
        return user

    yield _make
    for uid in created:
        admin.delete(f"/api/admin/users/{uid}")
