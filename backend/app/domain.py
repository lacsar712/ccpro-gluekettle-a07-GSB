"""熬锅出胶门槛：最近一次煮胶峰值温度须 ≥ 90℃，且未撤回押印去重后至少两名不同人。"""

from app.models import Kettle, StampRow

MIN_PEAK = 90.0
MIN_DISTINCT_STAMPERS = 2


class RuleError(ValueError):
    pass


def latest_peak(kettle: Kettle) -> float | None:
    if not kettle.cooks:
        return None
    latest = max(kettle.cooks, key=lambda c: c.taken_at)
    return latest.peak_temp_c


def active_stamp_rows(kettle: Kettle) -> list[StampRow]:
    """该锅当前「未撤回、且尚未封账」的押印名单。"""
    return [
        s
        for s in (kettle.stamps or [])
        if s.withdrawn_at is None and s.book_id is None
    ]


def distinct_stamper_names(rows: list[StampRow]) -> list[str]:
    """名单按印人去重（同名只算一人），保留首次出现顺序。"""
    names: list[str] = []
    for s in rows:
        if s.stamper not in names:
            names.append(s.stamper)
    return names


def evaluate_draw(kettle: Kettle, rows: list[StampRow]) -> float:
    """出胶前校验：峰值达标且去重后 ≥ 2 名不同印人。返回最近峰值。

    空名单、单人、两人同名（去重后仍一人）一律挡住。
    """
    peak = latest_peak(kettle)
    if peak is None:
        raise RuleError("该锅尚无煮胶峰值，不能出胶")
    if peak < MIN_PEAK:
        raise RuleError(f"最近峰值 {peak}℃ 低于 {MIN_PEAK:.0f}℃，不能出胶")
    if not rows:
        raise RuleError("该锅没有未撤回押印，空名单不能出胶")
    names = distinct_stamper_names(rows)
    if len(names) < MIN_DISTINCT_STAMPERS:
        who = "、".join(names)
        raise RuleError(
            f"未撤回押印去重后仅 {len(names)} 人（{who}），须至少两名不同人，不能出胶"
        )
    return peak


def assert_can_set_status(kettle: Kettle, new_status: str, active_rows=None) -> None:
    allowed = {Kettle.STATUS_COLD, Kettle.STATUS_BOILING, Kettle.STATUS_DRAWN}
    if new_status not in allowed:
        raise RuleError(f"无效状态：{new_status}")
    if new_status != Kettle.STATUS_DRAWN:
        # 改成冷锅 / 熬煮中完全不碰押印。
        return
    evaluate_draw(kettle, list(active_rows or []))
