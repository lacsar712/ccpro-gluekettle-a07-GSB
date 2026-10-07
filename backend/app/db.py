import os

from sqlmodel import Session, create_engine

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://gluekettle:gluekettle@127.0.0.1:6190/gluekettle",
)
engine = create_engine(DATABASE_URL, echo=False)


def get_session() -> Session:
    return Session(engine)
