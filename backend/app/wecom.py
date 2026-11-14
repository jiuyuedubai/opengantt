"""企业微信工作简报推送：全员日志 → AI 摘要（失败降级模板）→ 群机器人 Webhook。

设计约定：
- 未配置 WECOM_WEBHOOK_URL 时整体静默关闭，任何调用路径都不报错；
- AI 调用失败/超时/未配置 Key 时自动降级为规则模板摘要，保证每天必发；
- 推送是旁路行为：任何异常只记日志，绝不影响归档与主业务；
- 模型接口走 OpenAI 兼容协议（默认智谱 GLM），换厂商只需改环境变量；
- 密钥只来自环境变量，绝不写入代码库，日志中不打印密钥与完整响应。
"""

import datetime as dt
import json
import logging
import urllib.request

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import (
    DailyReport,
    DailyTask,
    DailyTaskAssignee,
    Department,
    ProgressLog,
    Project,
    Task,
    TaskAssignee,
    User,
    UserDepartment,
)
from app.services import PRIORITY_LABELS, _overdue_days, generate_daily_report

logger = logging.getLogger("opengantt.wecom")

# 企微 markdown 内容上限 4096 字节，留余量
WECOM_MD_LIMIT = 4000

# 每人要点喂给模型的截断长度（防 token 超限）
PER_USER_CLIP = 400

# AI 输出正文上限（约一屏）；超出按行截断兜底
AI_BODY_MAX_CHARS = 320

SYSTEM_PROMPT = (
    "你是项目助理，为领导写一份极简中文工作日报摘要（企业微信群快速浏览用）。\n"
    "硬性要求：\n"
    "1) 只依据材料，绝不编造数字、姓名与事实；\n"
    "2) 输出固定三节，格式如下：\n"
    "**✅ 今日重点进展**\n· …\n**⏳ 待办与风险**\n· …\n**📌 明日重点**\n· …\n"
    "3) 每节最多 3 条、每条不超过 25 字，全文总字数不超过 300 字，宁缺毋滥；\n"
    "4) 挑选标准：\n"
    "   - 「进展」优先写已完成（100%）或说明里有具体成果的任务，同一任务多人负责只写一条，无实质说明的进行中任务不要逐人罗列；\n"
    "   - 「待办与风险」只写逾期、阻塞、明确截止临近的，没有就写「无」，禁止拿普通进行中任务或“进度待提升”这类空话凑数；\n"
    "   - 「明日重点」从次日待办里挑 1-3 项最重要的；\n"
    "5) 某节确无内容写「无」，不要编凑。"
)


def _today_str() -> str:
    return dt.date.today().isoformat()


def _http_post_json(url: str, payload: dict, timeout: int = 40, headers: dict | None = None) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


# 各节保留的最大行数（喂给 AI 的要点瘦身口径：突出重点、剔除空占位）
_SECTION_MAX_LINES = {"一、": 4, "二、": 3, "三、": 3, "四、": 2, "五、": 2, "六、": 2}


def _slim_daily_body(body: str) -> str:
    """截取日志的实质内容节（一~六）并按节限制行数。

    兼容两种排版：纯文本（"一、今日完成"，当前版本）与历史归档的 Markdown（"## 一、…"）。
    作用：显著压缩喂给模型的输入，AI 只见要点、更易输出短摘要。
    """
    out: list[str] = []
    current: str | None = None
    counts = {k: 0 for k in _SECTION_MAX_LINES}
    for raw in body.splitlines():
        line = raw.strip()
        if not line or line.startswith("💡"):
            continue
        if line.startswith(("（无", "（今日无", "（当日无")):
            continue  # 空占位提示行对 AI 是噪音
        head = next((h for h in _SECTION_MAX_LINES if line.startswith(h)), None)
        if head is not None:
            current = head
            counts[current] = 0
            out.append(line)
            continue
        if current is None:
            continue  # 忽略第一节课之前的头部（姓名/日期行）
        if counts[current] >= _SECTION_MAX_LINES[current]:
            continue
        counts[current] += 1
        out.append(line)
    return "\n".join(out)


def _dept_member_ids(db: Session, dept_name: str) -> list[int]:
    """某部门的全部在岗启用成员 ID（含一人多部门：全部所属部门命中即算）。

    找不到该部门时返回空列表（对应简报将为空概览，仍按配置推送以示区分）。
    """
    return list(
        db.execute(
            select(User.id)
            .outerjoin(UserDepartment, UserDepartment.user_id == User.id)
            .join(Department, Department.id.in_([UserDepartment.department_id, User.department_id]))
            .where(User.is_active, Department.name == dept_name)
        ).scalars()
    )


def _collect_digest(db: Session, log_date: str, member_ids: list[int] | None = None) -> dict:
    """聚合当日各成员日志；member_ids 非空时仅统计该范围（按部门推送时=本部门成员）。

    历史日期：优先读 17:30 归档的 daily_reports；
    当日：实时生成（不依赖 17:30 归档）——进度只要有更新，推送立即反映，
    避免"白天手动推送永远显示 0 人提交"的时间差问题。
    """
    today = _today_str()
    if member_ids is not None and not member_ids:
        return {"date": log_date, "text": "", "submitted": [], "missing": []}
    submitted: list[str] = []
    missing: list[str] = []
    parts: list[str] = []
    stmt = select(User).where(User.is_active).order_by(User.id)
    if member_ids:
        stmt = stmt.where(User.id.in_(member_ids))
    users = db.execute(stmt).scalars().all()
    for user in users:
        if (user.work_status or "working") != "working":
            continue  # 请假/休假/出差的员工不计入每日日志统计
        name = user.display_name or user.username
        body = None
        if log_date != today:
            archived = db.execute(
                select(DailyReport).where(DailyReport.user_id == user.id, DailyReport.log_date == log_date)
            ).scalar_one_or_none()
            if archived is not None:
                body = (archived.markdown or "").strip()
        if body is None:
            body = generate_daily_report(db, user, log_date).strip()
        if "（当日无任务进度记录）" in body:
            missing.append(name)
            continue
        slim = _slim_daily_body(body)
        if len(slim) > PER_USER_CLIP:
            slim = slim[:PER_USER_CLIP] + "…"
        submitted.append(name)
        parts.append(f"【{name}】\n{slim}")

    return {"date": log_date, "text": "\n\n".join(parts), "submitted": submitted, "missing": missing}


def _clip_lines(text: str, max_chars: int = AI_BODY_MAX_CHARS) -> str:
    """超出字数预算时按行截断（保留前面的高优先级内容），保证简报不超过一屏。"""
    out: list[str] = []
    total = 0
    for line in text.splitlines():
        if out and total + len(line) > max_chars:
            out.append("…")
            break
        out.append(line)
        total += len(line)
    return "\n".join(out)


def _ai_summary(digest: dict) -> str | None:
    """调 OpenAI 兼容接口生成简报；任何失败返回 None（由降级模板兜底）。"""
    if not settings.LLM_API_KEY:
        return None
    prompt = f"今天是 {digest['date']}，共 {len(digest['submitted'])} 人提交日志。"
    if digest["missing"]:
        prompt += f"未提交：{'、'.join(digest['missing'])}。"
    prompt += "\n\n各成员当日要点：\n\n" + (digest["text"] or "（今日暂无归档日志）")
    try:
        resp = _http_post_json(
            f"{settings.LLM_BASE_URL}/chat/completions",
            {
                "model": settings.LLM_MODEL,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.3,
                "max_tokens": 500,
            },
            headers={"Authorization": f"Bearer {settings.LLM_API_KEY}"},
        )
        content = ((resp.get("choices") or [{}])[0].get("message") or {}).get("content", "")
        content = (content or "").strip()
        return _clip_lines(content) or None
    except Exception:  # noqa: BLE001 — AI 失败必须有兜底
        logger.warning("AI 简报生成失败，降级为模板摘要", exc_info=True)
        return None


def _fallback_summary(db: Session, digest: dict, member_ids: list[int] | None = None) -> str:
    """规则模板摘要（AI 不可用时的兜底）：完成/进行/风险限量分条，每日任务合并一行。

    与 AI 版同口径：不含概览行（由 push 层统一拼接），正文控制在约 300 字。
    member_ids 非空时（按部门推送）仅统计任务负责人含本部门成员的任务，
    确保简报内容不混入其他部门。
    """
    day = digest["date"]
    logs_stmt = (
        select(ProgressLog, Task, User)
        .join(Task, ProgressLog.task_id == Task.id)
        .outerjoin(User, ProgressLog.user_id == User.id)
        .where(ProgressLog.log_date == day)
        .order_by(Task.id)
    )
    if member_ids:
        mine = select(TaskAssignee.task_id).where(TaskAssignee.user_id.in_(member_ids))
        logs_stmt = logs_stmt.where(
            or_(Task.id.in_(mine), Task.assignee_id.in_(member_ids))
        )
    logs = db.execute(logs_stmt).all()
    done, doing, risks = [], [], []
    for log, task, user in logs:
        who = task.assignee or ((user.display_name if user else "") if user else "") or "—"
        # 多行说明压平（分号分隔）并截断，保持简报单行结构
        note = "；".join(s.strip() for s in (log.note or "").splitlines() if s.strip())[:24]
        line = f"· #{task.id} {task.name} {log.progress}%（{who}）" + (f"：{note}" if note else "")
        overdue = _overdue_days(task.end_date, log.progress, day)
        if log.progress >= 100:
            done.append(line)
        elif overdue:
            risks.append(f"· #{task.id} {task.name}（{who}）：已逾期 {overdue} 天")
        elif (log.note or "") and any(k in log.note for k in ("阻塞", "卡", "等待", "协调")):
            risks.append(f"· #{task.id} {task.name}（{who}）：阻塞，需协调")
        else:
            doing.append(line)
    parts: list[str] = []
    if done:
        parts.append("**✅ 今日完成**\n" + "\n".join(done[:3]))
    if doing:
        parts.append("**🔄 进行中**\n" + "\n".join(doing[:3]))
    if risks:
        parts.append("**⚠️ 风险与关注**\n" + "\n".join(risks[:2]))
    # 每日任务合并为计数一行（说明不再逐条罗列）；按部门推送时仅统计本部门成员
    daily_stmt = (
        select(User, DailyTaskAssignee, DailyTask)
        .join(DailyTask, DailyTaskAssignee.daily_task_id == DailyTask.id)
        .join(User, DailyTaskAssignee.user_id == User.id)
        .where(DailyTaskAssignee.done_date == day)
        .order_by(User.id)
    )
    if member_ids:
        daily_stmt = daily_stmt.where(DailyTaskAssignee.user_id.in_(member_ids))
    daily_rows = db.execute(daily_stmt).all()
    names: list[str] = []
    for _u, _a, t in daily_rows:
        if t.name not in names:
            names.append(t.name)
    if names:
        more = f" 等 {len(names)} 项" if len(names) > 4 else ""
        parts.append("**📋 每日任务**：" + "、".join(names[:4]) + more)
    return "\n".join(parts) if parts else "今日暂无进度更新"


def _digest_head(digest: dict) -> str:
    """概览行：提交/应提交人数与未交名单（超过 5 人折叠），统一拼接在正文最前。"""
    n_sub, n_miss = len(digest["submitted"]), len(digest["missing"])
    head = f"**概览**：提交 {n_sub}/{n_sub + n_miss} 人"
    if digest["missing"]:
        shown = "、".join(digest["missing"][:5])
        if n_miss > 5:
            shown += f" 等 {n_miss} 人"
        head += f"，未交：{shown}"
    return head


def _render(date_str: str, body: str, mode: str, high_projects: list[str]) -> str:
    tag = "AI 整理" if mode == "ai" else "自动汇总"
    md = f"**📊 工作简报 · {date_str}**（{tag}）\n"
    if high_projects:
        md += f"**🔴 高优先级项目**：{'、'.join(high_projects[:6])}\n"
    md += f"{body}\n[打开平台查看详情]({settings.WECOM_PLATFORM_URL})"
    # 按字节截断，避免超出企微 markdown 上限（忽略截断产生的半字符）
    return md.encode("utf-8")[:WECOM_MD_LIMIT].decode("utf-8", errors="ignore")


def send_wecom_markdown(md: str, url: str | None = None) -> dict:
    """推送到群机器人；未配置/失败均返回结构化结果，不抛出。

    url 缺省使用全局 WECOM_WEBHOOK_URL；按部门推送时传入对应部门的群机器人地址。
    """
    target = (url or settings.WECOM_WEBHOOK_URL).strip()
    if not target:
        return {"ok": False, "skipped": True, "reason": "未配置 WECOM_WEBHOOK_URL"}
    try:
        resp = _http_post_json(
            target,
            {"msgtype": "markdown", "markdown": {"content": md}},
            timeout=15,
        )
        return {"ok": resp.get("errcode") == 0, "resp": resp}
    except Exception as exc:  # noqa: BLE001
        logger.warning("企微 Webhook 推送失败：%s", exc)
        return {"ok": False, "error": str(exc)}


# 任务提醒部门白名单：仅这些部门的新任务提醒会推送到企微群。
# 其他部门 Webhook 未配置（当前统一使用商务运营部群），先关闭避免误发；
# 接入新部门 Webhook 后在此集合加入部门名即可。
REMIND_ENABLED_DEPARTMENTS = {"商务运营部"}


def send_task_remind(db: Session, task: Task, project: Project) -> dict:
    """发送新任务提醒到企微群（text 消息，按手机号 @负责人）。

    - 负责人取 task_assignees 关联账号；旧数据无关联时回退 assignee 文本（仅展示不 @）
    - 账号配置了 wecom_mobile 才能被真正 @（企微机器人仅支持 userid/手机号两种 @ 方式）
    - 未配置 webhook 时静默跳过；任何网络失败返回结构化结果不抛出
    - 仅对 REMIND_ENABLED_DEPARTMENTS 中的部门发送（其他部门 Webhook 未配置，
      避免其提醒误入商务运营部群；接入新部门 Webhook 时在此集合扩展）
    """
    dept_name = ""
    if project.department_id is not None:
        dept = db.get(Department, project.department_id)
        dept_name = dept.name if dept else ""
    if dept_name not in REMIND_ENABLED_DEPARTMENTS:
        label = dept_name or "未分部门"
        return {
            "ok": False,
            "skipped": True,
            "reason": f"「{label}」的任务提醒通道暂未配置（Webhook），提醒未发送",
        }

    url = settings.WECOM_REMIND_WEBHOOK_URL or settings.WECOM_WEBHOOK_URL
    if not url:
        return {"ok": False, "skipped": True, "reason": "未配置企微 Webhook，提醒未发送"}

    users = db.execute(
        select(User)
        .join(TaskAssignee, TaskAssignee.user_id == User.id)
        .where(TaskAssignee.task_id == task.id)
    ).scalars().all()
    names = [(u.display_name or u.username) for u in users]
    if not names and task.assignee:
        names = [task.assignee]
    mobiles = [(u.wecom_mobile or "").strip() for u in users if (u.wecom_mobile or "").strip()]
    no_mobile = [
        (u.display_name or u.username) for u in users if not (u.wecom_mobile or "").strip()
    ]

    priority_label = PRIORITY_LABELS.get(project.priority or "medium", "中")
    content = (
        "【新任务提醒】"
        + (" ".join(f"@{n}" for n in names) if names else "（负责人未指定）")
        + f"\n任务：#{task.id} {task.name}"
        + f"\n项目：{project.name}（优先级：{'🔴 ' if project.priority == 'high' else ''}{priority_label}）"
        + f"\n起止：{task.start_date} ~ {task.end_date}"
        + f"\n当前进度：{task.progress}%"
        + f"\n请负责人尽快登录平台查看并更新进度：{settings.WECOM_PLATFORM_URL}"
    )
    # 企微 text 消息 content 上限 2048 字节，留余量
    content = content.encode("utf-8")[:2000].decode("utf-8", errors="ignore")

    text: dict = {"content": content}
    if mobiles:
        text["mentioned_mobile_list"] = mobiles
    try:
        resp = _http_post_json(url, {"msgtype": "text", "text": text}, timeout=15)
        return {
            "ok": resp.get("errcode") == 0,
            "resp": resp,
            "mentioned": names,
            "mentioned_by_mobile": mobiles,
            "no_mobile": no_mobile,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("任务提醒推送失败：%s", exc)
        return {"ok": False, "error": str(exc)}


def _push_dept_digests(db: Session, date_str: str, enabled: dict[str, str], force_fallback: bool) -> dict:
    """按部门推送：每个已启用（URL 非空）的部门各收到一份仅含本部门成员的工作简报。

    每个部门独立走 AI 摘要 → 降级模板流程；单个部门失败不影响其他部门。
    """
    high_projects = db.execute(
        select(Project.name).where(Project.priority == "high").order_by(Project.id)
    ).scalars().all()
    results: dict[str, dict] = {}
    ok_all = True
    for dept_name, url in enabled.items():
        try:
            member_ids = _dept_member_ids(db, dept_name)
            digest = _collect_digest(db, date_str, member_ids)
            body, mode = None, "fallback"
            if not force_fallback:
                body = _ai_summary(digest)
                mode = "ai" if body else "fallback"
            if body is None:
                body, mode = _fallback_summary(db, digest, member_ids), "fallback"
            full_body = _digest_head(digest) + "\n" + body
            md = _render(date_str, full_body, mode, list(high_projects))
            sent = send_wecom_markdown(md, url=url)
            results[dept_name] = {
                "ok": sent.get("ok", False),
                "mode": mode,
                "members": len(digest["submitted"]),
                "missing": digest["missing"],
                "preview": md,
            }
            ok_all = ok_all and sent.get("ok", False)
            logger.info(
                "部门简报推送 %s → %s：%s 模式，成员 %d 人，成功=%s",
                date_str, dept_name, mode, len(digest["submitted"]), sent.get("ok"),
            )
        except Exception as exc:  # noqa: BLE001 — 单部门失败不影响其余部门
            logger.exception("部门简报推送失败：%s", dept_name)
            results[dept_name] = {"ok": False, "error": str(exc)}
            ok_all = False
    return {"ok": ok_all, "mode": "departments", "departments": results}


def push_daily_digest(db: Session, log_date: str | None = None, force_fallback: bool = False) -> dict:
    """推送指定日期（默认今天）的工作简报；返回结果供测试端点展示。任何失败不抛出。

    推送范围：WECOM_DEPT_WEBHOOKS 中 URL 非空的部门各推一份本部门简报；
    该映射为空/未启用时回退旧全局流程（单群推全员简报）。
    """
    date_str = log_date or _today_str()
    enabled = {k: v for k, v in settings.WECOM_DEPT_WEBHOOKS.items() if v}
    if not enabled:
        if not settings.WECOM_WEBHOOK_URL:
            return {"ok": False, "skipped": True, "reason": "未配置 WECOM_WEBHOOK_URL，推送已关闭"}
        try:
            digest = _collect_digest(db, date_str)
            body, mode = None, "fallback"
            if not force_fallback:
                body = _ai_summary(digest)
                mode = "ai" if body else "fallback"
            if body is None:
                body, mode = _fallback_summary(db, digest), "fallback"
            # 概览行统一拼接（AI/模板同口径），正文三节保持在约一屏内
            full_body = _digest_head(digest) + "\n" + body
            high_projects = db.execute(
                select(Project.name).where(Project.priority == "high").order_by(Project.id)
            ).scalars().all()
            md = _render(date_str, full_body, mode, list(high_projects))
            result = send_wecom_markdown(md)
            logger.info("企微简报推送 %s：%s 模式 → %s", date_str, mode, result.get("ok"))
            return {"ok": result.get("ok", False), "mode": mode, "wecom": result, "preview": md}
        except Exception as exc:  # noqa: BLE001 — 旁路：推送异常不影响主业务
            logger.exception("简报推送流程异常")
            return {"ok": False, "error": str(exc)}
    return _push_dept_digests(db, date_str, enabled, force_fallback)
