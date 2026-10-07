from datetime import datetime, timezone
from typing import ClassVar, Optional

from sqlalchemy import Index, text
from sqlmodel import Field, Relationship, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(unique=True, index=True)
    password_hash: str
    role: str = "worker"


class Workshop(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    alley: str = ""
    kettles: list["Kettle"] = Relationship(back_populates="workshop")


class Kettle(SQLModel, table=True):
    STATUS_COLD: ClassVar[str] = "cold"
    STATUS_BOILING: ClassVar[str] = "boiling"
    STATUS_DRAWN: ClassVar[str] = "drawn"

    id: Optional[int] = Field(default=None, primary_key=True)
    workshop_id: int = Field(foreign_key="workshop.id")
    code: str
    status: str = STATUS_COLD
    bench: int = 0
    workshop: Optional[Workshop] = Relationship(back_populates="kettles")
    cooks: list["CookLog"] = Relationship(back_populates="kettle")
    stamps: list["Stamp"] = Relationship(back_populates="kettle")


class CookLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    kettle_id: int = Field(foreign_key="kettle.id")
    taken_at: datetime = Field(default_factory=utcnow)
    peak_temp_c: float
    operator: str = ""
    kettle: Optional[Kettle] = Relationship(back_populates="cooks")


class StampBook(SQLModel, table=True):
    """押印册：一册就是一套未撤回押印集合。

    只要册内还有未撤回押印，该册就在册（closed_at 为空）。一锅至多一册
    在册，由部分唯一索引在库里兜底：两名主管并发各交一本时，库只放行一套。
    册内押印被撤空时关册（closed_at 落时刻），不留空壳集合。
    """

    __tablename__ = "stampbooks"
    __table_args__ = (
        Index(
            "uq_stampbook_one_open_per_kettle",
            "kettle_id",
            unique=True,
            postgresql_where=text("closed_at IS NULL"),
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    kettle_id: int = Field(foreign_key="kettle.id")
    created_at: datetime = Field(default_factory=utcnow)
    submitted_by: Optional[str] = None
    closed_at: Optional[datetime] = None
    stamps: list["Stamp"] = Relationship(back_populates="book")


class Stamp(SQLModel, table=True):
    """押印行：锅码、印人、时刻、撤回时刻（可空）。

    同一印人在同一锅的同一本册里至多保留一枚未撤回押印，
    防止重复行冒充两名不同人。
    """

    __tablename__ = "stamps"
    __table_args__ = (
        Index(
            "uq_stamp_active_per_person_book",
            "book_id",
            "stamper",
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    kettle_id: int = Field(foreign_key="kettle.id")
    book_id: int = Field(foreign_key="stampbooks.id")
    stamper: str
    stamped_at: datetime = Field(default_factory=utcnow)
    revoked_at: Optional[datetime] = None
    kettle: Optional[Kettle] = Relationship(back_populates="stamps")
    book: Optional[StampBook] = Relationship(back_populates="stamps")
