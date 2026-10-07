from sqlmodel import select

from app.db import get_session
from app.models import CookLog, Kettle, Stamp, StampBook, User, Workshop
from app.security import hash_password


def _ensure_user(session, username: str, role: str) -> None:
    user = session.exec(select(User).where(User.username == username)).first()
    if user is None:
        session.add(User(username=username, password_hash=hash_password("123456"), role=role))
    else:
        user.password_hash = hash_password("123456")
        user.role = role


def seed_demo() -> None:
    with get_session() as session:
        _ensure_user(session, "admin", "admin")
        _ensure_user(session, "worker", "worker")
        _ensure_user(session, "worker2", "worker")
        if session.exec(select(Workshop)).first():
            session.commit()
            return
        shop = Workshop(name="骨巷熬胶坊", alley="西市骨巷")
        session.add(shop)
        session.flush()
        layout = [
            # （锅码, 状态, 台位, 最近峰值, 已在册印人）
            ("锅-1", Kettle.STATUS_BOILING, 0, 96.0, []),            # 峰值够但零押印：出胶应被挡
            ("锅-2", Kettle.STATUS_COLD, 1, None, []),
            ("锅-3", Kettle.STATUS_DRAWN, 2, 102.0, ["admin", "worker"]),
            ("锅-4", Kettle.STATUS_BOILING, 3, 82.0, ["worker", "worker2"]),  # 押印够但峰值不够
            ("锅-5", Kettle.STATUS_COLD, 4, None, []),
            ("锅-6", Kettle.STATUS_DRAWN, 5, 94.0, ["worker", "worker2"]),
        ]
        for code, status, bench, peak, stampers in layout:
            kettle = Kettle(workshop_id=shop.id, code=code, status=status, bench=bench)
            session.add(kettle)
            session.flush()
            if peak is not None:
                session.add(CookLog(kettle_id=kettle.id, peak_temp_c=peak, operator="worker"))
            if stampers:
                book = StampBook(kettle_id=kettle.id, submitted_by="admin")
                session.add(book)
                session.flush()
                for name in stampers:
                    session.add(Stamp(kettle_id=kettle.id, book_id=book.id, stamper=name))
        session.commit()
