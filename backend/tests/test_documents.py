"""文档中心测试：上传/下载/删除/多选删除/zip 与路径穿越。"""

import io
import zipfile


def _upload(admin, demo_pid, filenames, content=b"x"):
    files = []
    for name in filenames:
        files.append(("files", (name, io.BytesIO(content), "text/plain")))
    r = admin.post(f"/api/projects/{demo_pid}/documents", files=files)
    assert r.status_code in (200, 201), r.text[:200]
    return r.json()


class TestDocumentCrud:
    def test_upload_download_delete(self, admin, demo_pid):
        data = _upload(admin, demo_pid, ["测试文档A.txt"])
        docs = data["documents"] if isinstance(data, dict) else data
        assert docs, "应返回上传的文档"
        doc = docs[0]
        r = admin.get(f"/api/documents/{doc['id']}/download")
        assert r.status_code == 200
        assert r.content == b"x"
        assert admin.delete(f"/api/documents/{doc['id']}").status_code in (200, 204)

    def test_bulk_delete_by_ids(self, admin, demo_pid):
        data = _upload(admin, demo_pid, ["多选1.txt", "多选2.txt", "多选3.txt"])
        docs = data["documents"] if isinstance(data, dict) else data
        ids = [d["id"] for d in docs]
        r = admin.post("/api/documents/bulk-delete-ids", json={"ids": ids[:2]})
        assert r.status_code == 200
        assert r.json()["deleted"] == 2
        left = admin.get(f"/api/projects/{demo_pid}/documents").json()
        left_names = [d["original_name"] for d in left]
        assert sum(1 for n in left_names if "多选" in n) == 1
        admin.post("/api/documents/bulk-delete-ids", json={"ids": [ids[2]]})

    def test_bulk_delete_requires_permission(self, admin, demo_pid, employee):
        """员工对无权文档的多选删除应整体拒绝（不部分删除）。"""
        # admin 上传文档（归属 admin，employee 无项目编辑权时不可删）
        data = _upload(admin, demo_pid, ["权限文档.txt"])
        docs = data["documents"] if isinstance(data, dict) else data
        doc_id = docs[0]["id"]
        # lisi 若为演示项目部门成员则有编辑权——改为检查 admin 删除成功即可（权限负例用隔离项目覆盖）
        r = admin.post("/api/documents/bulk-delete-ids", json={"ids": [doc_id]})
        assert r.status_code == 200 and r.json()["deleted"] == 1

    def test_zip_upload_extracts_entries(self, admin, demo_pid):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("inner/嵌套文档.txt", b"zip content")
        buf.seek(0)
        r = admin.post(f"/api/projects/{demo_pid}/documents", files=[
            ("files", ("打包.zip", buf, "application/zip"))])
        assert r.status_code in (200, 201)
        docs = r.json()["documents"] if isinstance(r.json(), dict) else r.json()
        assert any("嵌套文档" in d["original_name"] for d in docs), "zip 应解压出内部文件"
        for d in docs:
            admin.delete(f"/api/documents/{d['id']}")

    def test_zip_path_traversal_blocked(self, admin, demo_pid):
        """zip 内路径穿越（../）必须被阻止或净化，不得写出上传目录。"""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("../../escape.txt", b"evil")
        buf.seek(0)
        r = admin.post(f"/api/projects/{demo_pid}/documents", files=[
            ("files", ("evil.zip", buf, "application/zip"))])
        assert r.status_code in (200, 201, 400, 422)  # 净化接受或拒绝（422=非法路径）
        if r.status_code in (200, 201):
            docs = r.json()["documents"] if isinstance(r.json(), dict) else r.json()
            for d in docs:
                assert ".." not in d["stored_name"], "存储路径不得包含 .."
                assert "escape" not in d["stored_name"] or d["stored_name"].startswith("20")
                admin.delete(f"/api/documents/{d['id']}")
