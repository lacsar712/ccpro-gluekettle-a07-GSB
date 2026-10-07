from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from sqlmodel import SQLModel, select

from app.db import engine, get_session
from app.domain import (
    RuleError,
    active_stamp_rows,
    assert_can_set_status,
    distinct_stamper_names,
    evaluate_draw,
    latest_peak,
)
from app.models import CookLog, Kettle, StampBook, StampRow, User, Workshop, utcnow
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


def require_role(user: User | None, role: str) -> bool:
    return user is not None and user.role == role


def load_kettle(session, kettle_id: int, *, for_update: bool = False) -> Kettle | None:
    stmt = (
        select(Kettle)
        .where(Kettle.id == kettle_id)
        .options(
            selectinload(Kettle.cooks),
            selectinload(Kettle.stamps),
            selectinload(Kettle.book),
        )
    )
    if for_update:
        # 行锁：两本几乎同时提交的出胶在此排队，后者拿到的是前者提交后的世界。
        stmt = stmt.with_for_update()
    return session.exec(stmt).first()


def stamp_json(stamp: StampRow) -> dict:
    return {
        "id": stamp.id,
        "kettleId": stamp.kettle_id,
        "stamper": stamp.stamper,
        "stampedAt": stamp.stamped_at.isoformat() if stamp.stamped_at else None,
        "withdrawnAt": stamp.withdrawn_at.isoformat() if stamp.withdrawn_at else None,
        "bookId": stamp.book_id,
    }


def kettle_json(kettle: Kettle) -> dict:
    active = active_stamp_rows(kettle)
    return {
        "id": kettle.id,
        "code": kettle.code,
        "status": kettle.status,
        "bench": kettle.bench,
        "latestPeakC": latest_peak(kettle),
        "cookCount": len(kettle.cooks or []),
        "activeStamperNames": distinct_stamper_names(active),
        "sealed": kettle.book is not None,
    }


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
            .options(selectinload(Kettle.cooks), selectinload(Kettle.stamps), selectinload(Kettle.book))
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
        # 登记峰值完全不碰押印：无需加载 stamps，也不改任何押印状态。
        kettle = session.exec(select(Kettle).where(Kettle.id == kettle_id)).first()
        if kettle is None:
            return JSONResponse({"detail": "锅不存在"}, status_code=404)
        session.add(CookLog(kettle_id=kettle.id, peak_temp_c=peak, operator=user.username))
        session.commit()
        kettle = load_kettle(session, kettle_id)
        return JSONResponse(kettle_json(kettle))


async def list_stamps(request: Request):
    user = await current_user(request)
    if user is None:
        return JSONResponse({"detail": "未登录"}, status_code=401)
    kettle_id = int(request.path_params["kettle_id"])
    with get_session() as session:
        kettle = session.exec(select(Kettle).where(Kettle.id == kettle_id)).first()
        if kettle is None:
            return JSONResponse({"detail": "锅不存在"}, status_code=404)
        rows = session.exec(
            select(StampRow).where(StampRow.kettle_id == kettle_id).order_by(StampRow.id)
        ).all()
        return JSONResponse(
            {
                "kettleId": kettle.id,
                "kettleCode": kettle.code,
                "stamps": [stamp_json(s) for s in rows],
            }
        )


async def add_stamp(request: Request):
    """加印。印人一律取登录人自己——操作工只能给自己加印，无法替他人署名。"""
    user = await current_user(request)
    if user is None:
        return JSONResponse({"detail": "未登录"}, status_code=401)
    kettle_id = int(request.path_params["kettle_id"])
    with get_session() as session:
        kettle = session.exec(select(Kettle).where(Kettle.id == kettle_id)).first()
        if kettle is None:
            return JSONResponse({"detail": "锅不存在"}, status_code=404)
        if session.exec(select(StampBook).where(StampBook.kettle_id == kettle.id)).first() is not None:
            return JSONResponse({"detail": "该锅已出胶封账，不能再加印"}, status_code=400)
        stamp = StampRow(kettle_id=kettle.id, stamper=user.username)
        session.add(stamp)
        session.commit()
        session.refresh(stamp)
        return JSONResponse(stamp_json(stamp), status_code=201)


async def edit_stamp(request: Request):
    """编辑一条押印（改印人 / 撤回或恢复）——仅管理员。"""
    user = await current_user(request)
    if user is None:
        return JSONResponse({"detail": "未登录"}, status_code=401)
    if not require_role(user, "admin"):
        return JSONResponse({"detail": "只有管理员可以编辑押印"}, status_code=403)
    stamp_id = int(request.path_params["stamp_id"])
    body = await request.json()
    with get_session() as session:
        stamp = session.exec(select(StampRow).where(StampRow.id == stamp_id)).first()
        if stamp is None:
            return JSONResponse({"detail": "押印不存在"}, status_code=404)
        if stamp.book_id is not None:
            return JSONResponse({"detail": "已封账的押印不可修改"}, status_code=400)
        if "stamper" in body:
            name = str(body.get("stamper") or "").strip()
            if not name:
                return JSONResponse({"detail": "印人不能为空"}, status_code=400)
            stamp.stamper = name
        if "withdrawn" in body:
            if body.get("withdrawn"):
                if stamp.withdrawn_at is None:
                    stamp.withdrawn_at = utcnow()
            else:
                stamp.withdrawn_at = None
        session.add(stamp)
        session.commit()
        session.refresh(stamp)
        return JSONResponse(stamp_json(stamp))


async def withdraw_stamp(request: Request):
    """撤印——仅管理员。"""
    user = await current_user(request)
    if user is None:
        return JSONResponse({"detail": "未登录"}, status_code=401)
    if not require_role(user, "admin"):
        return JSONResponse({"detail": "撤印归管理员"}, status_code=403)
    stamp_id = int(request.path_params["stamp_id"])
    with get_session() as session:
        stamp = session.exec(select(StampRow).where(StampRow.id == stamp_id)).first()
        if stamp is None:
            return JSONResponse({"detail": "押印不存在"}, status_code=404)
        if stamp.book_id is not None:
            return JSONResponse({"detail": "已封账的押印不可撤回"}, status_code=400)
        if stamp.withdrawn_at is None:
            stamp.withdrawn_at = utcnow()
            session.add(stamp)
            session.commit()
            session.refresh(stamp)
        return JSONResponse(stamp_json(stamp))


async def draw_kettle(session, kettle_id: int, user: User) -> JSONResponse:
    """出胶封账：行锁内校验并封存唯一一套未撤回押印。

    峰值 ≥ 90℃ 且去重后 ≥ 2 名不同印人方可通过；唯一约束兜底并发，
    两本几乎同时提交时库里只保留一套。
    """
    kettle = load_kettle(session, kettle_id, for_update=True)
    if kettle is None:
        return JSONResponse({"detail": "锅不存在"}, status_code=404)
    if kettle.book is not None:
        # 已封存过一套：并发/重复提交一律 409，先于空名单等门槛判断。
        return JSONResponse({"detail": "该锅已封存过一套押印"}, status_code=409)
    active = active_stamp_rows(kettle)
    try:
        peak = evaluate_draw(kettle, active)
    except RuleError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    book = StampBook(kettle_id=kettle.id, sealed_by=user.username, peak_temp_c=peak)
    session.add(book)
    try:
        session.flush()  # 先拿 book.id，并立即撞上唯一约束（若并发已封）
    except IntegrityError:
        session.rollback()
        return JSONResponse({"detail": "该锅已封存过一套押印"}, status_code=409)
    for stamp in active:
        stamp.book_id = book.id
        session.add(stamp)
    kettle.status = Kettle.STATUS_DRAWN
    session.add(kettle)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        return JSONResponse({"detail": "该锅已封存过一套押印"}, status_code=409)
    kettle = load_kettle(session, kettle_id)
    return JSONResponse(kettle_json(kettle))


async def set_status(request: Request):
    user = await current_user(request)
    if user is None:
        return JSONResponse({"detail": "未登录"}, status_code=401)
    kettle_id = int(request.path_params["kettle_id"])
    body = await request.json()
    new_status = body.get("status", "")
    if new_status == Kettle.STATUS_DRAWN:
        with get_session() as session:
            return await draw_kettle(session, kettle_id, user)
    with get_session() as session:
        # 改成冷锅 / 熬煮中：完全不碰押印。
        kettle = load_kettle(session, kettle_id)
        if kettle is None:
            return JSONResponse({"detail": "锅不存在"}, status_code=404)
        try:
            assert_can_set_status(kettle, new_status)
        except RuleError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=400)
        kettle.status = new_status
        session.add(kettle)
        session.commit()
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
        Route("/api/kettles/{kettle_id:int}/stamps", list_stamps),
        Route("/api/kettles/{kettle_id:int}/stamps", add_stamp, methods=["POST"]),
        Route("/api/kettles/{kettle_id:int}/status", set_status, methods=["POST"]),
        Route("/api/stamps/{stamp_id:int}", edit_stamp, methods=["PATCH", "PUT"]),
        Route("/api/stamps/{stamp_id:int}/withdraw", withdraw_stamp, methods=["POST"]),
    ],
    middleware=[Middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])],
)
