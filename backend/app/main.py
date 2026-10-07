from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from sqlmodel import SQLModel, select
import time

from app.db import engine, get_session
from app.domain import (
    RuleError,
    active_stampers,
    assert_can_set_status,
    latest_peak,
)
from app.models import CookLog, Kettle, Stamp, StampBook, User, Workshop, utcnow
from app.security import make_token, parse_token, verify_password
from app.seed import seed_demo


async def current_user(request: Request) -> User | None:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        return None
    username = parse_token(header.split(" ", 1)[1])
    if not username:
        return None
    with get_session() as session:
        return session.exec(select(User).where(User.username == username)).first()


def is_admin(user: User) -> bool:
    return user.role == "admin"


def load_kettle(session, kettle_id: int) -> Kettle | None:
    return session.exec(
        select(Kettle)
        .where(Kettle.id == kettle_id)
        .options(selectinload(Kettle.cooks), selectinload(Kettle.stamps))
    ).first()


def kettle_json(kettle: Kettle) -> dict:
    return {
        "id": kettle.id,
        "code": kettle.code,
        "status": kettle.status,
        "bench": kettle.bench,
        "latestPeakC": latest_peak(kettle),
        "cookCount": len(kettle.cooks or []),
        "activeStampers": active_stampers(kettle),
    }


def stamp_json(stamp: Stamp) -> dict:
    return {
        "id": stamp.id,
        "kettleId": stamp.kettle_id,
        "bookId": stamp.book_id,
        "stamper": stamp.stamper,
        "stampedAt": stamp.stamped_at.isoformat() if stamp.stamped_at else None,
        "revokedAt": stamp.revoked_at.isoformat() if stamp.revoked_at else None,
    }


def open_book(session, kettle_id: int) -> StampBook | None:
    """该锅当前在册（含未撤回押印集合）的押印册。"""
    return session.exec(
        select(StampBook).where(
            StampBook.kettle_id == kettle_id, StampBook.closed_at.is_(None)
        )
    ).first()


def get_or_create_open_book(session, kettle: Kettle) -> StampBook:
    """取在册押印册；不存在则开本。并发首次开本由部分唯一索引仲裁，败者复用胜者之册。"""
    book = open_book(session, kettle.id)
    if book is not None:
        return book
    for attempt in range(20):
        session.add(StampBook(kettle_id=kettle.id))
        try:
            session.flush()
            return session.exec(
                select(StampBook).where(
                    StampBook.kettle_id == kettle.id, StampBook.closed_at.is_(None)
                )
            ).one()
        except IntegrityError:
            # 几乎同时开本：让胜者先提交，再复用其册。
            session.rollback()
            time.sleep(0.02 * (attempt + 1))
            fresh = open_book(session, kettle.id)
            if fresh is not None:
                return fresh
    raise RuleError("押印册正由他人开立，请稍后重试")


async def health(request: Request):
    return JSONResponse({"status": "ok", "service": "GlueKettle"})


async def login(request: Request):
    body = await request.json()
    with get_session() as session:
        user = session.exec(select(User).where(User.username == body.get("username", ""))).first()
        if user is None or not verify_password(body.get("password", ""), user.password_hash):
            return JSONResponse({"detail": "用户名或密码错误"}, status_code=401)
        return JSONResponse(
            {"access_token": make_token(user.username), "user": {"username": user.username, "role": user.role}}
        )


async def me(request: Request):
    user = await current_user(request)
    if user is None:
        return JSONResponse({"detail": "未登录"}, status_code=401)
    return JSONResponse({"username": user.username, "role": user.role})


async def board(request: Request):
    user = await current_user(request)
    if user is None:
        return JSONResponse({"detail": "未登录"}, status_code=401)
    with get_session() as session:
        shop = session.exec(select(Workshop)).first()
        if shop is None:
            return JSONResponse({"detail": "尚无熬胶坊"}, status_code=404)
        kettles = session.exec(
            select(Kettle)
            .where(Kettle.workshop_id == shop.id)
            .options(selectinload(Kettle.cooks), selectinload(Kettle.stamps))
        ).all()
        loaded = sorted(kettles, key=lambda k: k.bench)
        return JSONResponse(
            {"workshop": shop.name, "alley": shop.alley, "kettles": [kettle_json(k) for k in loaded]}
        )


async def add_cook(request: Request):
    user = await current_user(request)
    if user is None:
        return JSONResponse({"detail": "未登录"}, status_code=401)
    kettle_id = int(request.path_params["kettle_id"])
    body = await request.json()
    try:
        peak = float(body.get("peakTempC"))
    except (TypeError, ValueError):
        return JSONResponse({"detail": "峰值温度必须是数字"}, status_code=400)
    with get_session() as session:
        kettle = load_kettle(session, kettle_id)
        if kettle is None:
            return JSONResponse({"detail": "锅不存在"}, status_code=404)
        # 登记峰值完全不碰押印。
        session.add(CookLog(kettle_id=kettle.id, peak_temp_c=peak, operator=user.username))
        session.commit()
        kettle = load_kettle(session, kettle_id)
        return JSONResponse(kettle_json(kettle))


async def set_status(request: Request):
    user = await current_user(request)
    if user is None:
        return JSONResponse({"detail": "未登录"}, status_code=401)
    kettle_id = int(request.path_params["kettle_id"])
    body = await request.json()
    with get_session() as session:
        kettle = load_kettle(session, kettle_id)
        if kettle is None:
            return JSONResponse({"detail": "锅不存在"}, status_code=404)
        try:
            assert_can_set_status(kettle, body.get("status", ""))
        except RuleError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=400)
        # 改成冷锅/熬煮中完全不碰押印。
        kettle.status = body.get("status")
        session.add(kettle)
        session.commit()
        kettle = load_kettle(session, kettle_id)
        return JSONResponse(kettle_json(kettle))


async def list_stamps(request: Request):
    user = await current_user(request)
    if user is None:
        return JSONResponse({"detail": "未登录"}, status_code=401)
    kettle_id = int(request.path_params["kettle_id"])
    with get_session() as session:
        kettle = load_kettle(session, kettle_id)
        if kettle is None:
            return JSONResponse({"detail": "锅不存在"}, status_code=404)
        stamps = session.exec(
            select(Stamp).where(Stamp.kettle_id == kettle_id).order_by(Stamp.stamped_at)
        ).all()
        book = open_book(session, kettle_id)
        return JSONResponse(
            {
                "kettle": kettle_json(kettle),
                "openBookId": book.id if book else None,
                "stamps": [stamp_json(s) for s in stamps],
            }
        )


async def add_stamp(request: Request):
    """操作工只能给自己加印：印人一律取当前登录人，请求体给什么都不作数。"""
    user = await current_user(request)
    if user is None:
        return JSONResponse({"detail": "未登录"}, status_code=401)
    kettle_id = int(request.path_params["kettle_id"])
    with get_session() as session:
        kettle = load_kettle(session, kettle_id)
        if kettle is None:
            return JSONResponse({"detail": "锅不存在"}, status_code=404)
        try:
            book = get_or_create_open_book(session, kettle)
            duplicate = session.exec(
                select(Stamp).where(
                    Stamp.book_id == book.id,
                    Stamp.stamper == user.username,
                    Stamp.revoked_at.is_(None),
                )
            ).first()
            if duplicate is not None:
                return JSONResponse({"detail": "你已在该锅留有未撤回押印"}, status_code=409)
            session.add(Stamp(kettle_id=kettle.id, book_id=book.id, stamper=user.username))
            session.commit()
        except IntegrityError:
            session.rollback()
            return JSONResponse({"detail": "你已在该锅留有未撤回押印"}, status_code=409)
        except RuleError as exc:
            session.rollback()
            return JSONResponse({"detail": str(exc)}, status_code=503)
        kettle = load_kettle(session, kettle_id)
        return JSONResponse(kettle_json(kettle))


async def revoke_stamp(request: Request):
    """撤印归管理员：置撤回时刻；在册册被撤空则关册，不留空壳集合。"""
    user = await current_user(request)
    if user is None:
        return JSONResponse({"detail": "未登录"}, status_code=401)
    if not is_admin(user):
        return JSONResponse({"detail": "仅管理员可撤印"}, status_code=403)
    stamp_id = int(request.path_params["stamp_id"])
    with get_session() as session:
        stamp = session.exec(select(Stamp).where(Stamp.id == stamp_id)).first()
        if stamp is None:
            return JSONResponse({"detail": "押印不存在"}, status_code=404)
        if stamp.revoked_at is not None:
            return JSONResponse({"detail": "该押印已撤回"}, status_code=409)
        # 锁册串行化撤印：两人同时撤最后两枚时，后行者能看到先行者的撤回，由其关册。
        book = session.exec(
            select(StampBook).where(StampBook.id == stamp.book_id).with_for_update()
        ).first()
        stamp.revoked_at = utcnow()
        session.flush()
        if book is not None and book.closed_at is None:
            remaining = session.exec(
                select(Stamp).where(
                    Stamp.book_id == book.id, Stamp.revoked_at.is_(None)
                )
            ).first()
            if remaining is None:
                # 最后一枚押印被撤回：关册，使该锅回到零在册集合。
                book.closed_at = stamp.revoked_at
                session.add(book)
        session.commit()
        return JSONResponse(stamp_json(stamp))


async def submit_book(request: Request):
    """主管交本：一次交入两名以上不同人的未撤回押印集合。

    两名主管几乎同时抢交时，一锅一册在册的部分唯一索引只放行一套，
    败者整册回滚并得到 409，库里不会有两套未撤回集合并存。
    """
    user = await current_user(request)
    if user is None:
        return JSONResponse({"detail": "未登录"}, status_code=401)
    if not is_admin(user):
        return JSONResponse({"detail": "仅管理员可交本"}, status_code=403)
    kettle_id = int(request.path_params["kettle_id"])
    body = await request.json()
    raw_names = body.get("stampers")
    if not isinstance(raw_names, list):
        return JSONResponse({"detail": "stampers 必须是人名数组"}, status_code=400)
    names: list[str] = []
    seen: set[str] = set()
    for item in raw_names:
        name = str(item or "").strip()
        if not name:
            continue
        if name not in seen:
            seen.add(name)
            names.append(name)
    if len(names) < 2:
        return JSONResponse({"detail": "交本须含两名不同印人，单人或同名不算满"}, status_code=400)
    with get_session() as session:
        kettle = load_kettle(session, kettle_id)
        if kettle is None:
            return JSONResponse({"detail": "锅不存在"}, status_code=404)
        if open_book(session, kettle_id) is not None:
            return JSONResponse({"detail": "该锅已有在册未撤回押印集合，不能另交一本"}, status_code=409)
        book = StampBook(kettle_id=kettle.id, submitted_by=user.username)
        session.add(book)
        try:
            session.flush()
            for name in names:
                session.add(Stamp(kettle_id=kettle.id, book_id=book.id, stamper=name))
            session.flush()
            session.commit()
        except IntegrityError:
            session.rollback()
            return JSONResponse({"detail": "该锅押印集合已被抢先交入，只保留一套"}, status_code=409)
        kettle = load_kettle(session, kettle_id)
        return JSONResponse(kettle_json(kettle))


def init() -> None:
    SQLModel.metadata.create_all(engine)
    seed_demo()


init()

app = Starlette(
    routes=[
        Route("/api/health", health),
        Route("/api/auth/login", login, methods=["POST"]),
        Route("/api/auth/me", me),
        Route("/api/board", board),
        Route("/api/kettles/{kettle_id:int}/cooks", add_cook, methods=["POST"]),
        Route("/api/kettles/{kettle_id:int}/status", set_status, methods=["POST"]),
        Route("/api/kettles/{kettle_id:int}/stamps", list_stamps),
        Route("/api/kettles/{kettle_id:int}/stamps/add", add_stamp, methods=["POST"]),
        Route("/api/kettles/{kettle_id:int}/stamp-books/submit", submit_book, methods=["POST"]),
        Route("/api/stamps/{stamp_id:int}/revoke", revoke_stamp, methods=["POST"]),
    ],
    middleware=[Middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])],
)
