"""WorkBuddy 桥接绩效评分工具（本机运行，SSH 连生产）。

两段式评分闭环（评分由 WorkBuddy 会话内置模型完成，不使用任何个人 LLM API key）：
  1. python tools/perf_ai_score.py fetch <period>   # 拉取待评分数据到本地 bundle
  2. （WorkBuddy 阅读报告给出等级与评语，写入 bundle 里的 scores.json）
  3. python tools/perf_ai_score.py write <period>   # 写回生产库（替换综合评价段）

用法示例（在 WorkBuddy 对话中直接说"处理绩效 AI 评分"即可）。
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".." / "tmp"))
try:
    sys.path.insert(0, "/tmp")
    from og_ssh import run as ssh_run  # /tmp/og_ssh.py 由部署流程维护
except ImportError:
    from og_ssh import run as ssh_run

BUNDLE = Path("/tmp/perf_ai_bundle")
TEXT_EXT = {".txt", ".md", ".csv", ".html", ".json", ".log"}
MAX_FILE_BYTES = 20 * 1024
MAX_FILES_PER_USER = 10

FETCH_REMOTE = r"""
import json, urllib.request
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
COOKIE = {}
def api(method, path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request('http://127.0.0.1' + path, data=data, method=method,
        headers={'Content-Type': 'application/json', **COOKIE})
    with OPENER.open(req, timeout=30) as resp:
        sc = resp.headers.get('Set-Cookie')
        if sc: COOKIE['Cookie'] = sc.split(';')[0]
        return json.loads(resp.read().decode() or '{}')
api('POST', '/api/auth/login', {'username': 'admin', 'password': 'admin123'})
period = "__PERIOD__"
results = api('GET', f'/api/admin/performance/results?period={period}')
docs = api('GET', '/api/projects/1/documents')  # 占位：真正按人扫库用下方 SQL
out = {'period': period, 'results': results}
print(json.dumps(out, ensure_ascii=False))
"""


def fetch(period: str) -> None:
    out_dir = BUNDLE / period
    out_dir.mkdir(parents=True, exist_ok=True)
    # 1) 结果与指标
    remote = FETCH_REMOTE.replace("__PERIOD__", period)
    script = remote
    # 改为按人扫文档：直接在远端跑 sqlite 查询（文档按 uploader 聚合）
    script = script.replace(
        "docs = api('GET', '/api/projects/1/documents')  # 占位：真正按人扫库用下方 SQL",
        "pass",
    )
    script += "\nimport sqlite3\n"
    script += (
        "conn = sqlite3.connect('/opt/opengantt/backend/data/opengantt.db')\n"
        "conn.row_factory = sqlite3.Row\n"
        "for r in out['results']:\n"
        "    uid = r['user_id']\n"
        "    rows = conn.execute('SELECT original_name, size, note, content_type, stored_name FROM documents WHERE uploader_id=? ORDER BY id DESC', (uid,)).fetchall()\n"
        "    r['documents'] = [dict(x) for x in rows]\n"
        "conn.close()\n"
        "print(json.dumps(out, ensure_ascii=False))\n"
    )
    from og_ssh import put

    put_tmp = Path("/tmp") / f"og_fetch_{period}.py"
    put_tmp.write_text(script)
    put(str(put_tmp), f"/tmp/og_fetch_{period}.py")
    raw = ssh_run(f"cd /opt/opengantt/backend && /opt/opengantt/backend/.venv/bin/python /tmp/og_fetch_{period}.py", sudo=True, timeout=120)
    # 输出最后一行是 JSON（前面可能有日志）
    json_line = [ln for ln in raw.strip().splitlines() if ln.startswith("{")]
    data = json.loads(json_line[-1])
    (out_dir / "results.json").write_text(json.dumps(data, ensure_ascii=False, indent=1))

    # 2) 生成可读报告（给 WorkBuddy 分析用）
    lines = [f"# 绩效评分待办 · {period}\n"]
    for r in data["results"]:
        m = r.get("metrics") or {}
        lines.append(f"## {r['user_name']}（result_id={r['id']}）")
        lines.append(
            f"- 任务：总数 {m.get('task_total', 0)}，完成 {m.get('task_done', 0)}，"
            f"逾期 {m.get('task_overdue', 0)}，平均进度 {m.get('avg_progress', 0)}%"
        )
        lines.append(f"- 日志 {m.get('log_days', 0)} 天 / 每日任务 {m.get('daily_done_days', 0)} 天")
        docs = r.get("documents") or []
        lines.append(f"- 上传文档 {len(docs)} 份：")
        for d in docs[:MAX_FILES_PER_USER]:
            lines.append(f"  - {d['original_name']}（{d['size']} 字节{'，来自压缩包' if '来自压缩包' in (d.get('note') or '') else ''}）")
        lines.append("")
    (out_dir / "report.md").write_text("\n".join(lines))
    (out_dir / "scores.json").write_text(json.dumps(
        {"period": period, "scores": []},
        ensure_ascii=False, indent=1))
    print(f"已生成待评分报告：{out_dir / 'report.md'}")
    print(f"评分后请把等级与评语写入：{out_dir / 'scores.json'}（格式见文件内注释）")


def write(period: str) -> None:
    scores_path = BUNDLE / period / "scores.json"
    payload = json.loads(scores_path.read_text())
    scores = payload.get("scores") or []
    if not scores:
        print("scores.json 中没有评分数据（scores 数组为空）")
        return
    remote_code = r"""
import json, sqlite3
period = "__PERIOD__"
scores = __SCORES__
conn = sqlite3.connect('/opt/opengantt/backend/data/opengantt.db')
conn.row_factory = sqlite3.Row
updated = 0
for s in scores:
    row = conn.execute('SELECT summary FROM performance_results WHERE id=? AND period=?', (s['result_id'], period)).fetchone()
    if row is None:
        continue
    summary = row['summary']
    grade, comment = s['grade'], s['comment']
    import re
    # 替换"四、综合评价"段（无论当前是人工填写还是旧 AI 段）
    pattern = re.compile(r"## 四、综合评价.*?(?=\n---)", re.S)
    replacement = (
        "## 四、综合评价（WorkBuddy 助手建议评分，请人工复核）\n"
        f"- 建议等级：**{grade}**（由 WorkBuddy AI 助手依据平台数据与文档扫描评定）\n"
        f"- 评语：{comment}\n\n"
        "*AI 评分仅供参考，最终等级以考核人复核为准。*\n\n"
    )
    new_summary, n = pattern.subn(replacement, summary)
    if n == 0:
        new_summary = summary + "\n\n" + replacement
    conn.execute('UPDATE performance_results SET summary=? WHERE id=? AND period=?', (new_summary, s['result_id'], period))
    updated += 1
conn.commit()
conn.close()
print(f'已写回 {updated} 条评分')
"""
    remote_code = remote_code.replace("__PERIOD__", period).replace(
        "__SCORES__", json.dumps(scores, ensure_ascii=False)
    )
    from og_ssh import put

    put_tmp = Path("/tmp") / f"og_write_{period}.py"
    put_tmp.write_text(remote_code)
    put(str(put_tmp), f"/tmp/og_write_{period}.py")
    print(ssh_run(f"cd /opt/opengantt/backend && /opt/opengantt/backend/.venv/bin/python /tmp/og_write_{period}.py", sudo=True, timeout=120))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    period = sys.argv[2] if len(sys.argv) > 2 else ""
    if cmd == "fetch" and period:
        fetch(period)
    elif cmd == "write" and period:
        write(period)
    else:
        print("用法：python tools/perf_ai_score.py fetch|write <period>\n例：python tools/perf_ai_score.py fetch 2026-11")
