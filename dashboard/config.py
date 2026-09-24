import os
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv())


class Config:
    # If SQLITE_DB_PATH is set, the dashboard runs against a bundled,
    # read-only SQLite snapshot instead of live MySQL. This is how the
    # public deployment works: same codebase, no MySQL connection at all —
    # switched purely by which env var is present, not by a code branch you
    # have to remember to flip. Local dev leaves this unset and keeps using
    # the DB_* MySQL vars below, unchanged from Stage 6a.
    SQLITE_DB_PATH = os.environ.get("SQLITE_DB_PATH")

    DB_HOST = os.environ.get("DB_HOST")
    DB_PORT = int(os.environ.get("DB_PORT", 3306))
    DB_USER = os.environ.get("DB_USER")
    DB_PASSWORD = os.environ.get("DB_PASSWORD")
    DB_NAME = os.environ.get("DB_NAME", "f1_staging")

    if SQLITE_DB_PATH:
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{SQLITE_DB_PATH}"
    else:
        SQLALCHEMY_DATABASE_URI = (
            f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
        )

    SECRET_KEY = os.environ.get("FLASK_SECRET_KEY", "dev-only-change-me")
