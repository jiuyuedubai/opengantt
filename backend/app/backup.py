"""数据备份与版本回退：SQLite 在线快照（backup API，页级一致，不停服务）。

- 备份文件：data/backups/og_<时间戳>_v<版本号>_<auto|manual|pre_restore>.db
- 版本号：从现存备份的最大版本自增，跨触发方式连续，便于按版本回退
- 保留策略：默认保留最近 30 份，超出自动清理
- 回退流程：备份完整性校验 → 当前数据先做一次安全快照（pre_restore）→
  用 SQLite backup API 反向覆盖主库（页级一致）→ 回退后再校验完整性
"""

import datetime as dt
import logging
import re
import sqlite3
from pathlib import Path

from app.config import DATA_DIR, settings

logger = logging.getLogger("opengantt.backup")

BACKUP_DIR = Path(DATA_DIR) / "backups"
NAME_RE = re.compile(r"^og_(\d{8})_(\d{6})_v(\d+)_(auto|manual|pre_restore)\.db$")
KEEP_COUNT = 30


def _main_db() -> Path:
    """主数据库文件路径（settings.DATABASE_URL 形如 sqlite:////abs/path）。"""
    return Path(settings.DATABASE_URL.split("///", 1)[-1])


def _ensure_dir() -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    return BACKUP_DIR


def _integrity_check(path: Path) -> tuple[bool, str]:
    conn = sqlite3.connect(str(path))
    try:
        ok = conn.execute("PRAGMA integrity_check").fetchone()[0]
        tables = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
        return (ok == "ok" and tables > 0), str(ok)
    finally:
        conn.close()


def _next_version() -> int:
    versions = []
    for f in _ensure_dir().iterdir():
        m = NAME_RE.match(f.name)
        if m:
            versions.append(int(m.group(3)))
    return (max(versions) + 1) if versions else 1


def create_backup(trigger: str = "manual") -> dict:
    """对主库做一次在线一致性快照；返回备份元信息。"""
    if trigger not in ("auto", "manual", "pre_restore"):
        raise ValueError(f"非法备份触发方式：{trigger}")
    db_path = _main_db()
    if not db_path.is_file():
        raise FileNotFoundError("主数据库文件不存在")
    _ensure_dir()
    version = _next_version()
    now = dt.datetime.now()
    name = f"og_{now:%Y%m%d_%H%M%S}_v{version}_{trigger}.db"
    target = BACKUP_DIR / name

    src = sqlite3.connect(str(db_path))
    try:
        dst = sqlite3.connect(str(target))
        try:
            src.backup(dst)  # 页级一致快照：写操作进行中也安全
        finally:
            dst.close()
    finally:
        src.close()

    ok, detail = _integrity_check(target)
    if not ok:
        target.unlink(missing_ok=True)
        raise RuntimeError(f"备份完整性校验失败（{detail}），已删除无效备份")

    prune_backups()
    info = {
        "filename": name,
        "version": version,
        "created_at": now.isoformat(timespec="seconds"),
        "size": target.stat().st_size,
        "trigger": trigger,
    }
    logger.info("数据备份完成：%s（%.1f KB）", name, info["size"] / 1024)
    return info


def list_backups() -> list[dict]:
    """全部备份历史，按版本号倒序（最新在前）。"""
    out = []
    for f in _ensure_dir().iterdir():
        m = NAME_RE.match(f.name)
        if not m:
            continue
        d, t, v, trig = m.groups()
        out.append({
            "filename": f.name,
            "version": int(v),
            "created_at": f"{d[:4]}-{d[4:6]}-{d[6:]} {t[:2]}:{t[2:4]}:{t[4:]}",
            "size": f.stat().st_size,
            "trigger": trig,
        })
    out.sort(key=lambda x: x["version"], reverse=True)
    return out


def restore_backup(filename: str) -> dict:
    """回退到指定备份版本（覆盖当前数据；回退前自动生成安全快照）。"""
    m = NAME_RE.match(filename)
    if not m:
        raise ValueError("非法的备份文件名")
    target = _ensure_dir() / filename
    if not target.is_file():
        raise FileNotFoundError("备份文件不存在")

    ok, detail = _integrity_check(target)
    if not ok:
        raise RuntimeError(f"备份文件完整性校验失败（{detail}），已中止回退")

    # 回退前对当前数据做安全快照：回退失误时可再次回退找回
    pre = create_backup(trigger="pre_restore")

    src = sqlite3.connect(str(target))
    try:
        dst = sqlite3.connect(str(_main_db()))
        try:
            src.backup(dst)  # 反向在线恢复：页级一致，无需停服务
        finally:
            dst.close()
    finally:
        src.close()

    ok2, detail2 = _integrity_check(_main_db())
    if not ok2:
        raise RuntimeError(f"回退后完整性校验失败（{detail2}），请立即用 pre_restore 快照恢复")

    logger.info(
        "数据回退完成：恢复到 %s（v%s），回退前快照 %s",
        filename, m.group(3), pre["filename"],
    )
    return {
        "restored": filename,
        "version": int(m.group(3)),
        "pre_restore_backup": pre["filename"],
        "restored_at": dt.datetime.now().isoformat(timespec="seconds"),
    }


def delete_backup(filename: str) -> int:
    """删除单个备份文件，返回释放的字节数。"""
    m = NAME_RE.match(filename)
    if not m:
        raise ValueError("非法的备份文件名")
    target = _ensure_dir() / filename
    if not target.is_file():
        raise FileNotFoundError("备份文件不存在")
    size = target.stat().st_size
    target.unlink()
    logger.info("备份删除：%s（%.1f KB）", filename, size / 1024)
    return size


def delete_backups(filenames: list[str]) -> dict:
    """批量删除备份；单个失败不中断其余，返回汇总结果。"""
    deleted: list[str] = []
    failed: list[dict] = []
    freed = 0
    for name in dict.fromkeys(filenames):
        try:
            freed += delete_backup(name)
            deleted.append(name)
        except Exception as exc:  # noqa: BLE001 — 单个失败不影响其余
            failed.append({"filename": name, "error": str(exc)})
    if deleted:
        logger.info("批量删除备份 %d 份，释放 %.1f KB", len(deleted), freed / 1024)
    return {"deleted": deleted, "failed": failed, "freed": freed}


def prune_backups(keep: int = KEEP_COUNT) -> int:
    """仅保留最近 keep 份备份，返回清理数量。"""
    backups = [
        f for f in _ensure_dir().iterdir()
        if (m := NAME_RE.match(f.name))
    ]
    backups.sort(key=lambda f: int(NAME_RE.match(f.name).group(3)), reverse=True)
    removed = 0
    for f in backups[keep:]:
        f.unlink(missing_ok=True)
        removed += 1
    if removed:
        logger.info("备份清理：已删除 %d 份超出保留数量的旧备份", removed)
    return removed
