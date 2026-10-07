from datetime import datetime, timezone
from typing import ClassVar, Optional

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
    stamps: list["StampRow"] = Relationship(
        back_populates="kettle", sa_relationship_kwargs={"order_by": "StampRow.id"}
    )
    book: Optional["StampBook"] = Relationship(back_populates="kettle")


class StampRow(SQLModel, table=True):
    """一条押印：含锅码（kettle）、印人、加印时刻，撤回时刻可空。"""

    __tablename__ = "stamp_rows"

    id: Optional[int] = Field(default=None, primary_key=True)
    kettle_id: int = Field(foreign_key="kettle.id", index=True)
    stamper: str = Field(index=True)
    stamped_at: datetime = Field(default_factory=utcnow)
    withdrawn_at: Optional[datetime] = Field(default=None, index=True)
    # 出胶封账后写入所属押印集；未封账前为空。
    book_id: Optional[int] = Field(default=None, foreign_key="stamp_books.id", index=True)
    kettle: Optional[Kettle] = Relationship(back_populates="stamps")
    book: Optional["StampBook"] = Relationship(back_populates="stamps")


class StampBook(SQLModel, table=True):
    """一次出胶所封存的「未撤回押印集合」。

    kettle_id 上的唯一约束是硬保证：即便两本账几乎同时提交，库里也只许
    存在一套（第二次插入被数据库直接拒绝）。
    """

    __tablename__ = "stamp_books"

    id: Optional[int] = Field(default=None, primary_key=True)
    kettle_id: int = Field(foreign_key="kettle.id", unique=True)
    sealed_at: datetime = Field(default_factory=utcnow)
    sealed_by: str = ""
    peak_temp_c: float
    stamps: list[StampRow] = Relationship(back_populates="book")
    kettle: Optional[Kettle] = Relationship(back_populates="book")


class CookLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    kettle_id: int = Field(foreign_key="kettle.id")
    taken_at: datetime = Field(default_factory=utcnow)
    peak_temp_c: float
    operator: str = ""
    kettle: Optional[Kettle] = Relationship(back_populates="cooks")
