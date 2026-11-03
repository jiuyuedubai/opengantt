"""中国法定节假日判断：控制每日企微简报是否推送。

判定策略（三层）：
1. 优先使用 chinese-calendar 库（社区维护，数据与国务院放假安排同步，含调休补班日）；
2. 库未安装或日期超出其覆盖范围（如新年度安排尚未发布）时，回退规则：
   周一至周五视为工作日（推送），周六日跳过——此时调休补班的周末会漏推一次、
   与法定节假日重叠的普通周末工作日会多推一次，升级库版本后自动恢复精确；
3. 判断过程发生其他异常时按工作日处理（推送是旁路行为，宁可多推不可漏推）。
"""

import datetime as dt
import logging

logger = logging.getLogger("opengantt.holidays")

try:
    import chinese_calendar as _cn_cal
except ImportError:  # 依赖缺失不阻断启动，走回退规则
    _cn_cal = None
    logger.warning("chinese-calendar 未安装，节假日判断退化为周末规则")


def is_push_workday(day: dt.date | None = None) -> bool:
    """day（默认今天）是否应推送工作简报：工作日（含调休补班日）=True。

    法定节假日与普通周末返回 False；供每日 17:30 简报推送前调用。
    """
    day = day or dt.date.today()
    if _cn_cal is not None:
        try:
            return bool(_cn_cal.is_workday(day))
        except NotImplementedError:
            # 库数据尚未覆盖该年份（新年度安排未发布）：回退周末规则
            logger.warning("chinese-calendar 数据未覆盖 %s，按周末规则判断", day)
        except Exception:  # noqa: BLE001 — 判断失败按工作日处理，宁可多推不可漏推
            logger.exception("节假日判断异常，按工作日处理")
            return True
    return day.weekday() < 5
