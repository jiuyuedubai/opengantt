"""绩效考核模块：考核表模板预存 + 基于平台数据自动生成考核结果。

- 模板：每位员工预存一份考核表文件（一人一份，可替换），生成考核时直接调用；
- 结果：按周期聚合员工在平台上的任务与日志数据 + 上传文档产出扫描，自动生成考核摘要
  （Markdown）并存档；可选 AI 自动评分（复用企微简报的 OpenAI 兼容 LLM 通道，失败自动
  降级为人工填写）；支持逐人下载或按周期批量打包（zip）。

权限：全部端点仅管理员（页签前端仅 admin 渲染 + 后端 require_roles("admin") 强制）。
"""

import datetime as dt
import io
import json
import logging
import secrets
import zipfile
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import DATA_DIR
from app.errors import NotFoundError, ValidationError
from app.models import (
    DailyTaskAssignee,
    Document,
    PerformanceResult,
    PerformanceTemplate,
    ProgressLog,
    Project,
    Task,
    TaskAssignee,
    User,
)

logger = logging.getLogger("opengantt.performance")

PERF_DIR = Path(DATA_DIR) / "performance"
MAX_TEMPLATE_MB = 20


def _ensure_dir() -> Path:
    PERF_DIR.mkdir(parents=True, exist_ok=True)
    return PERF_DIR


def _period_range(period: str) -> tuple[str, str]:
    """"2026-11" → ("2026-11-01", "2026-11-30")；非法周期抛错。"""
    try:
        base = dt.datetime.strptime(period, "%Y-%m")
    except ValueError:
        raise ValidationError("考核周期格式应为 YYYY-MM，如 2026-11")
    end = (base.replace(day=28) + dt.timedelta(days=6)).replace(day=1) - dt.timedelta(days=1)
    return base.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


# ---------- 模板库（一人一份，可替换） ----------


def save_template(db: Session, admin: User, user_id: int, original_name: str, content: bytes, content_type: str) -> dict:
    target = db.get(User, user_id)
    if target is None or not target.is_active:
        raise NotFoundError("员工不存在或已停用")
    if len(content) > MAX_TEMPLATE_MB * 1024 * 1024:
        raise ValidationError(f"考核表文件超过大小限制（最大 {MAX_TEMPLATE_MB} MB）")
    if not content:
        raise ValidationError("文件内容为空")
    _ensure_dir()
    suffix = Path(original_name).suffix[:20]
    stored = f"{secrets.token_hex(12)}{suffix}"
    (PERF_DIR / stored).write_bytes(content)
    # 一人一份：替换旧模板并删除旧文件
    old = db.execute(select(PerformanceTemplate).where(PerformanceTemplate.user_id == user_id)).scalar_one_or_none()
    if old is not None:
        (PERF_DIR / old.stored_name).unlink(missing_ok=True)
        db.delete(old)
        db.flush()
    tpl = PerformanceTemplate(
        user_id=user_id,
        original_name=original_name[:255],
        stored_name=stored,
        size=len(content),
        content_type=(content_type or "")[:120],
        uploaded_by=admin.id,
    )
    db.add(tpl)
    db.commit()
    logger.info("考核表上传：%s ← %s（%.1f KB）", target.username, original_name, len(content) / 1024)
    return _template_out(db, tpl)


def _template_out(db: Session, tpl: PerformanceTemplate) -> dict:
    user = db.get(User, tpl.user_id)
    return {
        "id": tpl.id,
        "user_id": tpl.user_id,
        "user_name": (user.display_name or user.username) if user else f"用户#{tpl.user_id}",
        "username": user.username if user else "",
        "original_name": tpl.original_name,
        "size": tpl.size,
        "uploaded_at": tpl.uploaded_at.isoformat(timespec="seconds"),
    }


def list_templates(db: Session) -> list[dict]:
    tpls = db.execute(select(PerformanceTemplate).order_by(PerformanceTemplate.id.desc())).scalars().all()
    return [_template_out(db, t) for t in tpls]


def get_template_file(db: Session, template_id: int) -> tuple[PerformanceTemplate, bytes]:
    tpl = db.get(PerformanceTemplate, template_id)
    if tpl is None:
        raise NotFoundError("考核表模板不存在")
    path = _ensure_dir() / tpl.stored_name
    if not path.is_file():
        raise NotFoundError("考核表文件已丢失，请重新上传")
    return tpl, path.read_bytes()


def delete_template(db: Session, admin: User, template_id: int) -> None:
    tpl = db.get(PerformanceTemplate, template_id)
    if tpl is None:
        raise NotFoundError("考核表模板不存在")
    (PERF_DIR / tpl.stored_name).unlink(missing_ok=True)
    db.delete(tpl)
    db.commit()


# ---------- 考核结果生成 ----------


def _compute_metrics(db: Session, user_id: int, start: str, end: str) -> dict:
    """按周期聚合某员工的任务与日志指标（考核结果的客观数据基础）。"""
    task_ids = db.execute(
        select(TaskAssignee.task_id).where(TaskAssignee.user_id == user_id)
    ).scalars().all()
    total = done = overdue = 0
    progress_sum = 0
    if task_ids:
        tasks = db.execute(select(Task).where(Task.id.in_(task_ids))).scalars().all()
        total = len(tasks)
        done = sum(1 for t in tasks if t.status == "done" or t.progress >= 100)
        # 逾期 = 截止日已过（以今天为基准，而非周期末——周期内未到期的任务不算逾期）且未完成
        today_str = dt.date.today().isoformat()
        overdue = sum(
            1 for t in tasks
            if t.end_date < today_str and t.progress < 100 and t.status not in ("done", "cancelled")
        )
        progress_sum = sum(t.progress for t in tasks)
    avg_progress = round(progress_sum / total, 1) if total else 0.0
    log_days = db.execute(
        select(func.count(func.distinct(ProgressLog.log_date))).where(
            ProgressLog.user_id == user_id,
            ProgressLog.log_date >= start,
            ProgressLog.log_date <= end,
        )
    ).scalar() or 0
    daily_done = db.execute(
        select(func.count(func.distinct(DailyTaskAssignee.done_date))).where(
            DailyTaskAssignee.user_id == user_id,
            DailyTaskAssignee.done_date >= start,
            DailyTaskAssignee.done_date <= end,
        )
    ).scalar() or 0
    return {
        "task_total": total,
        "task_done": done,
        "task_overdue": overdue,
        "avg_progress": avg_progress,
        "log_days": log_days,
        "daily_done_days": daily_done,
        "range": f"{start} ~ {end}",
    }


def _doc_metrics(db: Session, user_id: int) -> dict:
    """扫描该员工上传的全部文档产出（含压缩包解压展开后的文件）。"""
    docs = db.execute(
        select(Document).where(Document.uploader_id == user_id).order_by(Document.id.desc())
    ).scalars().all()
    total = len(docs)
    total_size = sum(d.size for d in docs)
    from_archive = sum(1 for d in docs if "来自压缩包" in (d.note or ""))
    project_ids = {d.project_id for d in docs}
    projects = []
    for pid in project_ids:
        p = db.get(Project, pid)
        if p is not None:
            projects.append(p.name)
    samples = [d.original_name for d in docs[:10]]
    return {
        "doc_total": total,
        "doc_size_mb": round(total_size / (1024 * 1024), 2),
        "doc_from_archive": from_archive,
        "doc_projects": projects,
        "doc_samples": samples,
    }


def _doc_section(md_lines: list[str], dm: dict) -> None:
    """把文档产出扫描结果写入考核摘要。"""
    md_lines.append("## 三、文档产出（上传文件扫描）")
    if not dm["doc_total"]:
        md_lines.append("- 周期内未上传任何文档")
        md_lines.append("")
        return
    md_lines.append(f"- 上传文件总数：**{dm['doc_total']}** 份，共 **{dm['doc_size_mb']} MB**")
    if dm["doc_from_archive"]:
        md_lines.append(f"- 其中来自压缩包解压：**{dm['doc_from_archive']}** 份")
    if dm["doc_projects"]:
        md_lines.append(f"- 涉及项目：{'、'.join(dm['doc_projects'][:6])}" + ("…" if len(dm["doc_projects"]) > 6 else ""))
    if dm["doc_samples"]:
        md_lines.append("- 文件清单（最近 10 份）：")
        for s in dm["doc_samples"]:
            md_lines.append(f"  - {s}")
    md_lines.append("")


def _ai_score(name: str, period: str, m: dict, dm: dict) -> dict | None:
    """AI 自动评分（已停用内置 LLM 通道）。

    按用户要求，个人 LLM API key 仅用于工作日志 AI 总结（wecom 简报），
    绩效评分不调用它——本函数恒返回 None（考核摘要降级为人工填写段）。
    评分改由 WorkBuddy 助手桥接完成：tools/perf_ai_score.py（fetch → 评分 → write），
    结果会写回"四、综合评价（WorkBuddy 助手建议评分）"段。
    """
    return None


def _summary_markdown(name: str, period: str, m: dict, dm: dict, tpl_name: str | None, ai: dict | None) -> str:
    """自动生成考核结果摘要（Markdown）。客观数据为主，评价与得分留给人事填写。"""
    lines = [
        f"# 绩效考核结果 · {name}（{period}）",
        "",
        f"> 自动生成于 {dt.datetime.now():%Y-%m-%d %H:%M}，数据区间 {m['range']}；考核表模板：{tpl_name or '（未上传）'}",
        "",
        "## 一、任务完成情况",
        f"- 名下任务总数：**{m['task_total']}** 项",
        f"- 已完成：**{m['task_done']}** 项（完成率 {round(m['task_done'] * 100 / m['task_total']) if m['task_total'] else 0}%）",
        f"- 平均进度：**{m['avg_progress']}%**",
        f"- 逾期未完成：**{m['task_overdue']}** 项",
        "",
        "## 二、工作日志与每日任务",
        f"- 周期内提交工作日志：**{m['log_days']}** 天",
        f"- 周期内完成每日任务：**{m['daily_done_days']}** 天",
        "",
    ]
    _doc_section(lines, dm)
    if ai is not None:
        lines += [
            "## 四、综合评价（AI 建议评分，请人工复核）",
            f"- 建议等级：**{ai['grade']}**（由 AI 依据平台数据自动评定）",
            f"- 评语：{ai['comment']}",
            "",
            "*AI 评分仅供参考，最终等级以考核人复核为准。*",
            "",
        ]
    else:
        lines += [
            "## 四、综合评价（人工填写）",
            "- 评价等级：＿＿＿＿（A / B / C / D）",
            "- 评语：＿＿＿＿＿＿＿＿＿＿＿＿",
            "",
        ]
    lines += [
        "---",
        "*本摘要由 OpenGantt 依据平台任务、日志与上传文档数据自动生成。*",
    ]
    return "\n".join(lines)


def generate_results(db: Session, admin: User, user_ids: list[int], period: str, ai_score: bool = False) -> list[dict]:
    """为选定员工批量生成考核结果（每人一条存档）；ai_score=True 时调用 LLM 建议评分。"""
    if not user_ids:
        raise ValidationError("请先选择要考核的员工")
    if len(user_ids) > 100:
        raise ValidationError("单次最多生成 100 名员工的考核结果")
    start, end = _period_range(period)
    out = []
    for uid in dict.fromkeys(user_ids):
        user = db.get(User, uid)
        if user is None or not user.is_active:
            continue
        name = user.display_name or user.username
        m = _compute_metrics(db, uid, start, end)
        dm = _doc_metrics(db, uid)
        tpl = db.execute(
            select(PerformanceTemplate).where(PerformanceTemplate.user_id == uid)
        ).scalar_one_or_none()
        tpl_name = tpl.original_name if tpl else None
        ai = _ai_score(name, period, m, dm) if ai_score else None
        summary = _summary_markdown(name, period, m, dm, tpl_name, ai)
        # 同一员工同一周期重复生成时覆盖旧结果
        exist = db.execute(
            select(PerformanceResult).where(
                PerformanceResult.user_id == uid, PerformanceResult.period == period
            )
        ).scalar_one_or_none()
        if exist is not None:
            exist.metrics = json.dumps(m, ensure_ascii=False)
            exist.summary = summary
            exist.created_by = admin.id
            exist.created_at = dt.datetime.now()
            rec = exist
        else:
            rec = PerformanceResult(
                user_id=uid, period=period,
                metrics=json.dumps(m, ensure_ascii=False),
                summary=summary, created_by=admin.id,
            )
            db.add(rec)
        db.flush()
        out.append(_result_out(db, rec))
    db.commit()
    logger.info("绩效考核结果生成：%d 人（周期 %s，AI评分=%s），操作人 %s", len(out), period, ai_score, admin.username)
    return out


def _result_out(db: Session, rec: PerformanceResult) -> dict:
    user = db.get(User, rec.user_id)
    return {
        "id": rec.id,
        "user_id": rec.user_id,
        "user_name": (user.display_name or user.username) if user else f"用户#{rec.user_id}",
        "period": rec.period,
        "metrics": json.loads(rec.metrics) if rec.metrics else {},
        "summary": rec.summary,
        "created_at": rec.created_at.isoformat(timespec="seconds"),
    }


def list_results(db: Session, period: str | None = None) -> list[dict]:
    stmt = select(PerformanceResult).order_by(PerformanceResult.id.desc())
    if period:
        stmt = stmt.where(PerformanceResult.period == period)
    recs = db.execute(stmt).scalars().all()
    return [_result_out(db, r) for r in recs]


def get_result_file(db: Session, result_id: int) -> tuple[str, bytes]:
    """单个考核结果下载：Markdown 文本。"""
    rec = db.get(PerformanceResult, result_id)
    if rec is None:
        raise NotFoundError("考核结果不存在")
    user = db.get(User, rec.user_id)
    name = (user.display_name or user.username) if user else f"用户{rec.user_id}"
    filename = f"绩效考核_{name}_{rec.period}.md"
    return filename, rec.summary.encode("utf-8")


def export_results_zip(db: Session, period: str) -> tuple[str, bytes]:
    """按周期批量打包：每人的结果摘要 .md + 考核表模板原文件（无模板则仅摘要）。"""
    recs = db.execute(
        select(PerformanceResult).where(PerformanceResult.period == period).order_by(PerformanceResult.id)
    ).scalars().all()
    if not recs:
        raise NotFoundError("该周期暂无考核结果")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for rec in recs:
            user = db.get(User, rec.user_id)
            name = (user.display_name or user.username) if user else f"用户{rec.user_id}"
            safe = name.replace("/", "_")
            zf.writestr(f"{period}/{safe}_考核结果.md", rec.summary)
            tpl = db.execute(
                select(PerformanceTemplate).where(PerformanceTemplate.user_id == rec.user_id)
            ).scalar_one_or_none()
            if tpl is not None:
                src = _ensure_dir() / tpl.stored_name
                if src.is_file():
                    zf.write(src, f"{period}/考核表模板/{safe}_{tpl.original_name}")
    filename = f"绩效考核汇总_{period}.zip"
    return filename, buf.getvalue()
