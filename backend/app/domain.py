"""熬锅出胶门槛：最近一次煮胶峰值须 ≥ 90℃，且未撤回押印去重后至少两名不同人。"""

from app.models import Kettle

MIN_PEAK = 90.0
MIN_DISTINCT_STAMPERS = 2


class RuleError(ValueError):
    pass


def latest_peak(kettle: Kettle) -> float | None:
    if not kettle.cooks:
        return None
    latest = max(kettle.cooks, key=lambda c: c.taken_at)
    return latest.peak_temp_c


def active_stampers(kettle: Kettle) -> list[str]:
    """该锅未撤回押印的印人，按人名去重。空名单/单人/同名都在这里现形。"""
    names = {s.stamper for s in (kettle.stamps or []) if s.revoked_at is None}
    return sorted(names)


def assert_can_set_status(kettle: Kettle, new_status: str) -> None:
    allowed = {Kettle.STATUS_COLD, Kettle.STATUS_BOILING, Kettle.STATUS_DRAWN}
    if new_status not in allowed:
        raise RuleError(f"无效状态：{new_status}")
    if new_status != Kettle.STATUS_DRAWN:
        # 登记峰值、改成冷锅/熬煮中完全不碰押印。
        return
    peak = latest_peak(kettle)
    if peak is None:
        raise RuleError("该锅尚无煮胶峰值，不能出胶")
    if peak < MIN_PEAK:
        raise RuleError(f"最近峰值 {peak}℃ 低于 {MIN_PEAK:.0f}℃，不能出胶")
    stampers = active_stampers(kettle)
    if not stampers:
        raise RuleError("该锅尚无未撤回押印，不能出胶")
    if len(stampers) < MIN_DISTINCT_STAMPERS:
        raise RuleError(
            f"未撤回押印仅 {stampers[0]} 一人，须两名不同人，不能出胶"
        )
