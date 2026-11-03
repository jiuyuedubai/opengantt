"""启动入口：建表、轻量迁移、种子数据、每日进度快照线程；生产以 uvicorn 启动。

本地开发:
    uvicorn app.main:app --reload --port 8000
生产:
    uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2
"""

import datetime as dt
import logging
import threading

from sqlalchemy import func, select

from app import create_app
from app.database import Base, SessionLocal, engine
from app.holidays import is_push_workday
from app.migrate import run_migrations
from app.models import DailyReport
from app.seed import seed
from app.services import (
    _today_str,
    record_audit,
    restore_due_work_status,
    save_daily_reports_for_today,
    snapshot_all_for_today,
)
from app.wecom import push_daily_digest

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("opengantt.main")

app = create_app()


def _work_status_worker() -> None:
    """每 60 秒检查一次：预计结束时间已到的请假/休假/出差自动恢复为在岗（幂等）。"""
    import time as _time

    while True:
        try:
            with SessionLocal() as db:
                restored = restore_due_work_status(db)
                if restored:
                    logger.info("在岗状态自动恢复：%s", "、".join(restored))
        except Exception:  # noqa: BLE001 — 后台线程必须自愈
            logger.exception("在岗状态自动恢复检查失败")
        _time.sleep(60)


def _daily_snapshot_worker() -> None:
    """每日 17:30 自动保存：为所有任务补全当日进度快照 + 归档每个人的工作日志（幂等）。"""
    import time as _time

    while True:
        now = dt.datetime.now()
        target = now.replace(hour=17, minute=30, second=0, microsecond=0)
        if target <= now:
            target += dt.timedelta(days=1)
        _time.sleep(max(60, (target - now).total_seconds()))
        try:
            with SessionLocal() as db:
                count = save_daily_reports_for_today(db)
                logger.info("每日自动保存：已归档 %d 份工作日志", count)
                # 法定节假日/普通周末跳过简报推送（调休补班日照常）；日志归档不受影响
                if not is_push_workday():
                    logger.info("今日为节假日/周末，跳过企微简报推送")
                else:
                    # 归档成功后推送企微简报（未配置 webhook 时内部静默跳过）
                    push_result = push_daily_digest(db)
                    record_audit(
                        db, None, "wecom_push",
                        object_type="report",
                        detail=f"每日简报推送{'成功' if push_result.get('ok') else '失败/跳过'}"
                               f"（{'AI 整理' if push_result.get('mode') == 'ai' else '模板汇总'}）",
                    )
                # 每日自动备份一次（含时间戳与版本号；超出保留数量自动清理；失败不影响主流程）
                try:
                    from app.backup import create_backup

                    info = create_backup(trigger="auto")
                    logger.info("每日自动备份完成：%s（v%d）", info["filename"], info["version"])
                except Exception:  # noqa: BLE001 — 备份是旁路行为，绝不影响归档与推送
                    logger.exception("每日自动备份失败")
        except Exception:  # noqa: BLE001 — 后台线程必须自愈
            logger.exception("每日自动保存失败（次日重试）")


def _safe_migrate() -> None:
    """建表 + 迁移：多 worker 并发启动时可能相互冲突（表/列已存在、唯一约束回填、库锁），
    冲突视为对方已完成同项工作，短暂退避后重试确认。"""
    import time as _time

    from sqlalchemy.exc import IntegrityError, OperationalError

    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            Base.metadata.create_all(bind=engine)
            run_migrations()
            return
        except (OperationalError, IntegrityError) as exc:
            msg = str(exc).lower()
            last_exc = exc
            if (
                "already exists" in msg
                or "duplicate" in msg
                or "unique" in msg
                or "locked" in msg
            ) and attempt < 2:
                logger.warning("并发启动迁移冲突（第 %d 次重试）：%s", attempt + 1, msg[:140])
                _time.sleep(1.0 * (attempt + 1))
                continue
            raise
    if last_exc:  # 理论不可达（重试用尽前必 return 或 raise）
        raise last_exc


@app.on_event("startup")
def on_startup() -> None:
    _safe_migrate()
    with SessionLocal() as db:
        seed(db)
        # 启动补全：当日进度快照始终执行（幂等）；
        # 若本次启动已过 17:30 且当日日志尚未归档，则立即补一次归档（覆盖"下班后才开机"场景）
        count = snapshot_all_for_today(db)
        if count:
            logger.info("启动快照：自动保存 %d 条当日任务进度", count)
        now = dt.datetime.now()
        already = db.execute(
            select(func.count(DailyReport.id)).where(DailyReport.log_date == _today_str())
        ).scalar() or 0
        if now.hour > 17 or (now.hour == 17 and now.minute >= 30):
            if not already:
                archived = save_daily_reports_for_today(db)
                logger.info("启动补归档：已保存 %d 份当日工作日志", archived)
        else:
            if already:
                logger.info("当日工作日志已有 %d 份自动保存记录", already)
    threading.Thread(target=_daily_snapshot_worker, name="daily-snapshot", daemon=True).start()
    threading.Thread(target=_work_status_worker, name="work-status-restore", daemon=True).start()
    logger.info("OpenGantt 启动完成")
