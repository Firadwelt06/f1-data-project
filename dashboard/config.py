import os
from dotenv import load_dotenv, find_dotenv

# find_dotenv() walks up from the current working directory until it finds
# a .env file, so this works whether you run `flask run` from the project
# root or from inside /dashboard. It resolves to the SAME .env your ETL
# scripts already use, under DB_HOST/DB_PORT/DB_USER/DB_PASSWORD/DB_NAME.
load_dotenv(find_dotenv())


class Config:
    DB_HOST = os.environ.get("DB_HOST")
    DB_PORT = int(os.environ.get("DB_PORT", 3306))
    DB_USER = os.environ.get("DB_USER")
    DB_PASSWORD = os.environ.get("DB_PASSWORD")
    DB_NAME = os.environ.get("DB_NAME", "f1_staging")

    SQLALCHEMY_DATABASE_URI = (
        f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    )

    # Only used for Flask's session/flash machinery, which this dashboard
    # doesn't rely on yet. A placeholder is fine for local dev; if the
    # dashboard ever needs real sessions, move this to .env too.
    SECRET_KEY = os.environ.get("FLASK_SECRET_KEY", "dev-only-change-me")
