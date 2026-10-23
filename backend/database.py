import os
from contextvars import ContextVar
from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


_request_session: ContextVar[Session | None] = ContextVar("request_db_session", default=None)
_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def _sqlalchemy_url(url: str) -> str:
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url.removeprefix("postgres://")
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url.removeprefix("postgresql://")
    if url.startswith("postgresql+psycopg://"):
        return url
    raise ValueError("DATABASE_URL must be a PostgreSQL connection URL.")


def get_engine() -> Engine:
    global _engine, _session_factory
    if _engine is None:
        raw_url = os.getenv("DATABASE_URL", "").strip()
        if not raw_url:
            raise ValueError("Set DATABASE_URL to a PostgreSQL connection URL.")
        url = _sqlalchemy_url(raw_url)
        if ".neon.tech" in url and "sslmode=" not in url:
            url += "&sslmode=require" if "?" in url else "?sslmode=require"
        _engine = create_engine(
            url,
            pool_pre_ping=True,
            pool_size=int(os.getenv("DB_POOL_SIZE", "5")),
            max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "5")),
            pool_recycle=int(os.getenv("DB_POOL_RECYCLE_SECONDS", "300")),
        )
        _session_factory = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def session_factory() -> sessionmaker[Session]:
    if _session_factory is None:
        get_engine()
    assert _session_factory is not None
    return _session_factory


def current_session() -> Session:
    session = _request_session.get()
    if session is not None:
        return session
    raise RuntimeError("Database access requires an active request session.")


def set_request_session(session: Session):
    return _request_session.set(session)


def reset_request_session(token) -> None:
    _request_session.reset(token)


@contextmanager
def session_scope():
    session = session_factory()()
    previous_session = _request_session.get()
    token = set_request_session(session)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        try:
            reset_request_session(token)
        except ValueError:
            _request_session.set(previous_session)
        session.close()


def get_db_session() -> Generator[Session, None, None]:
    session = session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def ping() -> None:
    with session_factory()() as session:
        session.execute(text("SELECT 1"))


def dispose_engine() -> None:
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None