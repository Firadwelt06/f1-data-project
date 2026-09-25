"""
export_snapshot.py
-------------------
Builds a frozen SQLite snapshot of the tables the dashboard actually
queries, for the public deployment — which never connects to live MySQL
at all.

This is NOT automatic. Run it manually whenever you want the public
site's data refreshed:

    python ml/precompute_predictions.py   (run this FIRST — see its docstring)
    python export_snapshot.py

...then commit the resulting f1_snapshot.db and push/redeploy. The public
site is static between runs by design — that was the whole point of
choosing a snapshot over a live connection.

Always reads from real MySQL directly (its own engine, built straight
from Config's DB_* vars) rather than importing db.engine — that avoids a
footgun where, if SQLITE_DB_PATH happened to be set in your local .env,
this script would try to read the (possibly stale or nonexistent) SQLite
file instead of the live database it's supposed to be exporting from.

The precomputed-predictions tables below are the one exception: those come
from CSV files on disk, not MySQL, because they're the output of running
the ML models (a separate, decoupled step — see ml/precompute_predictions.py).
Keeping that decoupled means this script never needs to import
scikit-learn/joblib itself; it only ever moves already-computed numbers
from disk into the snapshot.
"""

import sqlite3
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text

from config import Config

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_PATH = BASE_DIR / "f1_snapshot.db"
PREDICTIONS_DIR = BASE_DIR.parent / "ml" / "models"

# Only the tables the dashboard's routes actually query — no need to ship
# the other 11 tables in the full schema (in particular, lap_times stays
# out: it's by far the largest table and nothing in the dashboard queries
# it).
TABLES = [
    "races",
    "drivers",
    "constructors",
    "results",
    "pit_stops",
    "analytics_driver_race",
]

# Output of ml/precompute_predictions.py. Loaded as-is into the snapshot;
# see that script's docstring for what each one contains and why.
PREDICTION_FILES = {
    "finish_predictions_historical.csv": "finish_predictions_historical",
    "dnf_predictions_historical.csv": "dnf_predictions_historical",
    "finish_contrib_driver.csv": "finish_contrib_driver",
    "finish_contrib_constructor.csv": "finish_contrib_constructor",
    "finish_contrib_grid.csv": "finish_contrib_grid",
    "dnf_hypothetical_grid.csv": "dnf_hypothetical_grid",
    "prediction_metadata.csv": "prediction_metadata",
}

mysql_engine = create_engine(
    f"mysql+pymysql://{Config.DB_USER}:{Config.DB_PASSWORD}"
    f"@{Config.DB_HOST}:{Config.DB_PORT}/{Config.DB_NAME}"
)


def export_precomputed_predictions(sqlite_conn):
    for filename, table in PREDICTION_FILES.items():
        path = PREDICTIONS_DIR / filename
        if not path.exists():
            raise FileNotFoundError(
                f"Missing {path}. Run `python ml/precompute_predictions.py` "
                f"before export_snapshot.py — the snapshot needs its "
                f"precomputed predictions to exist first."
            )
        print(f"Loading precomputed {table}...")
        df = pd.read_csv(path)
        df.to_sql(table, sqlite_conn, if_exists="replace", index=False)
        print(f"  {len(df)} rows")

    sqlite_conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_finish_pred_race "
        "ON finish_predictions_historical (raceId)"
    )
    sqlite_conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_dnf_pred_race "
        "ON dnf_predictions_historical (raceId)"
    )
    sqlite_conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_dnf_grid_lookup "
        "ON dnf_hypothetical_grid (driverId, constructorId, qualifying_position)"
    )


def export():
    if OUTPUT_PATH.exists():
        OUTPUT_PATH.unlink()

    sqlite_conn = sqlite3.connect(OUTPUT_PATH)

    with mysql_engine.connect() as conn:
        for table in TABLES:
            print(f"Exporting {table}...")
            df = pd.read_sql(text(f"SELECT * FROM {table}"), conn)
            df.to_sql(table, sqlite_conn, if_exists="replace", index=False)
            print(f"  {len(df)} rows")

    # Recreate the index the win-streaks query depends on for speed —
    # to_sql() above only creates the tables and data, no indexes.
    sqlite_conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_results_race_driver_order "
        "ON results (raceId, driverId, positionOrder)"
    )

    export_precomputed_predictions(sqlite_conn)

    sqlite_conn.commit()
    sqlite_conn.close()

    size_kb = OUTPUT_PATH.stat().st_size / 1024
    print(f"\nSnapshot written to {OUTPUT_PATH} ({size_kb:.1f} KB)")


if __name__ == "__main__":
    export()
    