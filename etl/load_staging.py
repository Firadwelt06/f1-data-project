"""
load_staging.py

Loads all F1 dataset CSVs into the permissive MySQL staging tables
created by staging_schema.sql.

Design notes (the "why", not just the "how"):
- Everything is read from the CSV as plain strings, including the literal
  "\\N" null markers. We do NOT try to convert "\\N" to a real NULL here.
  Staging's job is a lossless copy of the source file. Cleaning/typing
  happens deliberately in Stage 2, where each conversion is a visible,
  reviewable SQL statement instead of something silently decided by a
  Python library during load.
- Inserts are batched (CHUNK_SIZE rows at a time) inside explicit
  transactions. This matters for lap_times.csv, which has ~628k rows -
  inserting row-by-row would be extremely slow, and one giant
  uncommitted transaction risks a huge rollback and a large memory
  footprint if something fails partway through.
- Row counts are validated after each load: CSV line count (minus header)
  must equal the count of rows now in the staging table.
"""

# --- Imports -----------------------------------------------------------
# pathlib.Path: modern, cross-platform way to build file paths (works the
# same on Windows and Linux, unlike manually joining strings with "/" or "\").
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import os
import sys
import time

# --- Configuration -------------------------------------------------------

# load_dotenv() reads the .env file in the project root and copies its
# key=value pairs into the environment variables for this process, so
# os.environ / os.getenv can see them. This is how the DB password stays
# out of the source code.
load_dotenv()

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "3306")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_NAME = os.getenv("DB_NAME", "f1_staging")

# Fail fast and clearly if the .env file wasn't set up, rather than getting
# a confusing MySQL "access denied" error two steps later.
if not DB_USER or not DB_PASSWORD:
    sys.exit(
        "ERROR: DB_USER / DB_PASSWORD not found. "
        "Did you create a .env file from .env.example and fill in real values?"
    )

# Where your CSVs live. Adjust if you put them somewhere else.
DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# How many rows to insert per batch. 5000 is a reasonable default -
# big enough to be efficient, small enough not to build a huge list
# of Python dicts in memory for lap_times.csv (~628k rows).
CHUNK_SIZE = 5000

# Maps each CSV filename -> its staging table name.
# This mirrors the DROP TABLE / CREATE TABLE order in staging_schema.sql.
TABLE_MAP = {
    "circuits.csv": "stg_circuits",
    "constructor_results.csv": "stg_constructor_results",
    "constructor_standings.csv": "stg_constructor_standings",
    "constructors.csv": "stg_constructors",
    "driver_standings.csv": "stg_driver_standings",
    "drivers.csv": "stg_drivers",
    "lap_times.csv": "stg_lap_times",
    "pit_stops.csv": "stg_pit_stops",
    "practice_results.csv": "stg_practice_results",
    "qualifying.csv": "stg_qualifying",
    "races.csv": "stg_races",
    "results.csv": "stg_results",
    "seasons.csv": "stg_seasons",
    "sprint_results.csv": "stg_sprint_results",
    "status.csv": "stg_status",
    "tire_stints.csv": "stg_tire_stints",
    "weather.csv": "stg_weather",
}


def build_engine():
    """
    Build and return a SQLAlchemy Engine.

    The Engine is not a live connection - it's a factory/pool that hands
    out connections when you ask for one (e.g. via `engine.begin()`) and
    takes care of opening/closing/reusing the underlying MySQL
    connections for you. You generally create ONE engine per application
    and reuse it, rather than opening a fresh connection by hand each time.
    """
    # The connection string format is: dialect+driver://user:password@host:port/dbname
    # "mysql" = the dialect (which flavor of SQL), "pymysql" = the driver
    # (the actual library that speaks MySQL's wire protocol).
    url = f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    return create_engine(url)


def csv_row_count(csv_path: Path) -> int:
    """Count data rows in a CSV (total lines minus the header line)."""
    with open(csv_path, encoding="utf-8") as f:
        return sum(1 for _ in f) - 1


def load_csv_to_table(engine, csv_path: Path, table_name: str) -> int:
    """
    Load a single CSV into its staging table. Returns the number of rows inserted.
    """
    # dtype=str: read every column as text, don't let pandas guess types.
    # keep_default_na=False: do NOT let pandas convert things like "\N",
    # empty strings, or "NA" into NaN - we want the raw text preserved
    # exactly as it appears in the file, per the staging design above.
    df = pd.read_csv(csv_path, dtype=str, keep_default_na=False)

    # Record which source file each row came from - useful provenance
    # if you ever reload data later and need to trace where a row came from.
    df["source_file"] = csv_path.name

    # DataFrame.to_dict(orient="records") turns the DataFrame into a list
    # of plain Python dicts, one per row, e.g. [{"circuitId": "1", ...}, ...].
    # This is the format SQLAlchemy's executemany-style insert expects.
    records = df.to_dict(orient="records")

    # Build the parameterized INSERT statement once. The :colname syntax
    # are bind parameters - SQLAlchemy sends the SQL and the data
    # separately to MySQL, so a value like O'Brien or a raw \N can never
    # be misinterpreted as SQL syntax. This is what protects against
    # SQL injection; never build INSERT strings by concatenating values in.
    columns = list(df.columns)
    col_list = ", ".join(f"`{c}`" for c in columns)
    placeholders = ", ".join(f":{c}" for c in columns)
    insert_stmt = text(f"INSERT INTO {table_name} ({col_list}) VALUES ({placeholders})")

    total_inserted = 0
    # engine.begin() opens a connection AND starts a transaction. Using it
    # as a "with" block (a context manager) guarantees that if everything
    # inside succeeds, it's committed automatically; if an exception is
    # raised, it's rolled back automatically. You don't have to remember
    # to call commit()/rollback() yourself.
    with engine.begin() as conn:
        # Staging is meant to be a lossless COPY of the current CSV, not
        # an accumulating log of every run - so clear out whatever's left
        # from a previous run before inserting. Without this, re-running
        # the script (by hand, or repeatedly via Dagster) keeps adding a
        # fresh copy of every row on top of the last one, and row counts
        # silently grow (3x, 4x, ...) instead of staying in sync with the
        # source CSV. TRUNCATE inside the same transaction as the inserts
        # keeps this atomic with everything else in this function - if
        # the load fails partway through, the truncate rolls back too and
        # the table is left as it was, not empty.
        conn.execute(text(f"TRUNCATE TABLE {table_name}"))

        # Process in chunks rather than one 628,000-row executemany call,
        # to keep memory bounded and give visible progress on big tables.
        for start in range(0, len(records), CHUNK_SIZE):
            chunk = records[start:start + CHUNK_SIZE]
            conn.execute(insert_stmt, chunk)
            total_inserted += len(chunk)

    return total_inserted


def validate_load(engine, csv_path: Path, table_name: str, inserted_count: int) -> bool:
    """
    Compare the CSV's data-row count against what's actually in the
    staging table now. Returns True if they match.
    """
    expected = csv_row_count(csv_path)

    with engine.connect() as conn:
        result = conn.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
        actual = result.scalar()  # .scalar() pulls the single value out of a 1x1 result

    ok = expected == actual
    status = "OK" if ok else "MISMATCH"
    print(f"    validate: csv_rows={expected}  table_rows={actual}  inserted_this_run={inserted_count}  [{status}]")
    return ok


def main():
    engine = build_engine()

    # Quick connectivity check before doing any real work, so a bad
    # password/host fails immediately with a clear message.
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as e:
        sys.exit(f"ERROR: could not connect to MySQL. Check your .env values.\n{e}")

    print(f"Connected to {DB_NAME} at {DB_HOST}:{DB_PORT}\n")

    results_summary = []
    overall_start = time.time()

    for csv_name, table_name in TABLE_MAP.items():
        csv_path = DATA_DIR / csv_name
        if not csv_path.exists():
            print(f"[SKIP] {csv_name} not found in {DATA_DIR}")
            results_summary.append((csv_name, table_name, False, "file not found"))
            continue

        print(f"[LOAD] {csv_name} -> {table_name}")
        start = time.time()
        try:
            inserted = load_csv_to_table(engine, csv_path, table_name)
            elapsed = time.time() - start
            print(f"    inserted {inserted} rows in {elapsed:.1f}s")
            ok = validate_load(engine, csv_path, table_name, inserted)
            results_summary.append((csv_name, table_name, ok, None))
        except Exception as e:
            print(f"    ERROR loading {csv_name}: {e}")
            results_summary.append((csv_name, table_name, False, str(e)))

    overall_elapsed = time.time() - overall_start

    # Final summary so you don't have to scroll back through the log
    # to see if everything actually worked.
    print("\n" + "=" * 60)
    print("LOAD SUMMARY")
    print("=" * 60)
    failures = 0
    for csv_name, table_name, ok, error in results_summary:
        marker = "OK" if ok else "FAILED"
        print(f"{marker:7s} {csv_name:30s} -> {table_name}")
        if error:
            print(f"        reason: {error}")
        if not ok:
            failures += 1

    print(f"\n{len(results_summary) - failures}/{len(results_summary)} tables loaded and validated cleanly.")
    print(f"Total time: {overall_elapsed:.1f}s")

    if failures:
        sys.exit(1)  # non-zero exit code = "something failed", useful if this is ever run in a script/CI


if __name__ == "__main__":
    main()
    