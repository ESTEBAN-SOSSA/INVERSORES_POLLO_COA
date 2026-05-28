"""Engine, sesión y Base declarativa de SQLAlchemy."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from src.config import settings


class Base(DeclarativeBase):
    pass


# SQLite necesita check_same_thread=False para usarse desde la API.
_connect_args = {}
if settings.database_url.startswith("sqlite"):
    _connect_args = {"check_same_thread": False}

engine = create_engine(
    settings.database_url,
    echo=False,
    future=True,
    connect_args=_connect_args,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Sesión transaccional: commit al salir bien, rollback si hay excepción."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    """Dependencia FastAPI."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
