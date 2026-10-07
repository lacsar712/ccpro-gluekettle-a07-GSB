from sqlmodel import select

from app.db import get_session
from app.models import CookLog, Kettle, StampRow, User, Workshop
from app.security import hash_password


def seed_demo() -> None:
    with get_session() as session:
        admin = session.exec(select(User).where(User.username == "admin")).first()
        if admin is None:
            session.add(User(username="admin", password_hash=hash_password("123456"), role="admin"))
        else:
            admin.password_hash = hash_password("123456")
            admin.role = "admin"
        worker = session.exec(select(User).where(User.username == "worker")).first()
        if worker is None:
            session.add(User(username="worker", password_hash=hash_password("123456"), role="worker"))
        else:
            worker.password_hash = hash_password("123456")
            worker.role = "worker"
        worker2 = session.exec(select(User).where(User.username == "worker2")).first()
        if worker2 is None:
            session.add(User(username="worker2", password_hash=hash_password("123456"), role="worker"))
        else:
            worker2.password_hash = hash_password("123456")
            worker2.role = "worker"

        if session.exec(select(Workshop)).first():
            session.commit()
            seed_demo_stamps(session)
            return
        shop = Workshop(name="骨巷熬胶坊", alley="西市骨巷")
        session.add(shop)
        session.flush()
        layout = [
            ("锅-1", Kettle.STATUS_BOILING, 0, 96.0),
            ("锅-2", Kettle.STATUS_COLD, 1, None),
            ("锅-3", Kettle.STATUS_DRAWN, 2, 102.0),
            ("锅-4", Kettle.STATUS_BOILING, 3, 82.0),
            ("锅-5", Kettle.STATUS_COLD, 4, None),
            ("锅-6", Kettle.STATUS_DRAWN, 5, 94.0),
        ]
        for code, status, bench, peak in layout:
            kettle = Kettle(workshop_id=shop.id, code=code, status=status, bench=bench)
            session.add(kettle)
            session.flush()
            if peak is not None:
                session.add(CookLog(kettle_id=kettle.id, peak_temp_c=peak, operator="worker"))
        session.commit()
        seed_demo_stamps(session)


def seed_demo_stamps(session) -> None:
    """给演示锅补齐押印样本（幂等）。

    - 锅-1（熬煮中、峰值 96）：两名不同印人的未撤回押印，可直接演示出胶。
    - 锅-4（熬煮中、峰值 82）：仅单人押印，且峰值不达标，演示被挡。
    已出胶的锅不加未封账押印；已存在押印的锅不重复加。
    """
    kettle1 = session.exec(select(Kettle).where(Kettle.code == "锅-1")).first()
    if kettle1 is not None and not session.exec(
        select(StampRow).where(StampRow.kettle_id == kettle1.id)
    ).first():
        session.add(StampRow(kettle_id=kettle1.id, stamper="worker"))
        session.add(StampRow(kettle_id=kettle1.id, stamper="worker2"))
    kettle4 = session.exec(select(Kettle).where(Kettle.code == "锅-4")).first()
    if kettle4 is not None and not session.exec(
        select(StampRow).where(StampRow.kettle_id == kettle4.id)
    ).first():
        session.add(StampRow(kettle_id=kettle4.id, stamper="worker"))
    session.commit()
