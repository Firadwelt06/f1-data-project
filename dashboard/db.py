from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker

try:
    from .config import Config
except ImportError:  # pragma: no cover - supports local script execution
    from config import Config

connect_args = {}
if Config.SQLALCHEMY_DATABASE_URI.startswith("sqlite"):
    # SQLite forbids using a connection from a thread other than the one
    # that created it, by default. Flask serves each request on its own
    # thread, so without this, every request after the first would raise
    # "SQLite objects created in a thread can only be used in that same
    # thread." Safe to disable here specifically because this file is a
    # read-only snapshot — there's no concurrent-write hazard to guard
    # against, which is the actual reason that check exists.
    connect_args = {"check_same_thread": False}

# pool_pre_ping / pool_recycle matter for the MySQL path (guards against a
# long-lived local dev DB dropping idle connections); they're harmless
# no-ops for SQLite, so this stays a single engine-creation call rather
# than branching per backend.
engine = create_engine(
    Config.SQLALCHEMY_DATABASE_URI,
    pool_pre_ping=True,
    pool_recycle=3600,
    connect_args=connect_args,
)

SessionLocal = scoped_session(
    sessionmaker(bind=engine, autoflush=False, autocommit=False)
)


def get_session():
    return SessionLocal()


def close_session(exception=None):
    SessionLocal.remove()
