from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker

from config import Config

# pool_pre_ping: issues a cheap "SELECT 1" before handing out a pooled
# connection, and transparently reconnects if it's gone stale. Worth having
# specifically because this is a long-lived local dev MySQL instance on
# Windows that can drop idle connections between dashboard requests.
# pool_recycle: proactively recycles connections older than this many
# seconds, as a second line of defense against the same problem.
engine = create_engine(
    Config.SQLALCHEMY_DATABASE_URI,
    pool_pre_ping=True,
    pool_recycle=3600,
)

# scoped_session gives each request thread its own Session transparently.
# Flask serves each request on its own thread (in the dev server and most
# WSGI servers), so a single shared Session object would let one request's
# in-progress transaction bleed into another's. scoped_session keys the
# session by thread, and SessionLocal.remove() in the teardown hook below
# clears it at the end of each request so connections go back to the pool
# instead of leaking.
SessionLocal = scoped_session(
    sessionmaker(bind=engine, autoflush=False, autocommit=False)
)


def get_session():
    return SessionLocal()


def close_session(exception=None):
    SessionLocal.remove()
