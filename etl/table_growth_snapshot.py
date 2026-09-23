"""
table_growth_snapshot.py

Takes a snapshot of every base table in f1_staging (exact row count +
on-disk size) and appends it to f1_monitoring.table_growth_log. Run this
periodically (manually for now) to build up a growth history over time.

WHY A SEPARATE f1_monitoring SCHEMA:
Keeping monitoring/operational metadata physically separate from the
business schema means a backup/restore of f1_staging never gets tangled
up with monitoring history, and vice versa -- standard DBA separation
of concerns.

WHY EXACT COUNT(*) INSTEAD OF information_schema's TABLE_ROWS:
information_schema.TABLES.TABLE_ROWS is an ESTIMATE for InnoDB tables,
based on sampled statistics -- it can drift from the true count. At this
project's scale (largest table ~628K rows), an exact COUNT(*) per table
is cheap enough that the accuracy is worth it for tracking real growth.

Data size (data_length / index_length) still comes from information_schema
since there's no "exact" equivalent query for on-disk size -- that IS
how MySQL tracks it.

USAGE:
    python etl/table_growth_snapshot.py
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT", "3306")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
SOURCE_SCHEMA = os.getenv("DB_NAME")  # f1_staging
MONITORING_SCHEMA = "f1_monitoring"

CREATE_MONITORING_TABLE_DDL = f"""
CREATE TABLE IF NOT EXISTS {MONITORING_SCHEMA}.table_growth_log (
    snapshot_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    snapshot_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    table_name VARCHAR(64) NOT NULL,
    row_count BIGINT NOT NULL,
    data_length_bytes BIGINT NOT NULL,
    index_length_bytes BIGINT NOT NULL,
    total_size_bytes BIGINT GENERATED ALWAYS AS (data_length_bytes + index_length_bytes) STORED,
    INDEX idx_table_time (table_name, snapshot_time)
) ENGINE=InnoDB
"""


def get_engine():
    # No default schema in the connection string -- every query below
    # fully qualifies schema.table, so this connection can read from
    # f1_staging and write to f1_monitoring in the same session.
    url = f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/"
    return create_engine(url)


def ensure_monitoring_infra(engine) -> None:
    with engine.connect() as conn:
        conn.execute(text(f"CREATE DATABASE IF NOT EXISTS {MONITORING_SCHEMA}"))
        conn.execute(text(CREATE_MONITORING_TABLE_DDL))
        conn.commit()


def get_table_sizes(engine, schema: str) -> dict:
    """Returns {table_name: (data_length, index_length)} from information_schema."""
    query = text(
        """
        SELECT TABLE_NAME, DATA_LENGTH, INDEX_LENGTH
        FROM information_schema.TABLES
        WHERE TABLE_SCHEMA = :schema AND TABLE_TYPE = 'BASE TABLE'
        """
    )
    with engine.connect() as conn:
        rows = conn.execute(query, {"schema": schema}).fetchall()
    return {r[0]: (r[1] or 0, r[2] or 0) for r in rows}


def get_exact_row_count(engine, schema: str, table_name: str) -> int:
    # Table/schema names come from information_schema (not user input),
    # so building this string is safe here -- SQLAlchemy can't
    # parameterize identifiers, only values.
    query = text(f"SELECT COUNT(*) FROM `{schema}`.`{table_name}`")
    with engine.connect() as conn:
        return conn.execute(query).scalar()


def insert_snapshot(engine, rows: list[dict]) -> None:
    insert_stmt = text(
        f"""
        INSERT INTO {MONITORING_SCHEMA}.table_growth_log
            (table_name, row_count, data_length_bytes, index_length_bytes)
        VALUES
            (:table_name, :row_count, :data_length_bytes, :index_length_bytes)
        """
    )
    with engine.connect() as conn:
        conn.execute(insert_stmt, rows)
        conn.commit()


def main() -> None:
    if not all([DB_HOST, DB_USER, DB_PASSWORD, SOURCE_SCHEMA]):
        raise RuntimeError("Missing required .env variables (DB_HOST, DB_USER, DB_PASSWORD, DB_NAME).")

    engine = get_engine()

    print(f"[1/3] Ensuring {MONITORING_SCHEMA} schema and table exist...")
    ensure_monitoring_infra(engine)

    print(f"[2/3] Snapshotting tables in '{SOURCE_SCHEMA}'...")
    sizes = get_table_sizes(engine, SOURCE_SCHEMA)
    if not sizes:
        raise RuntimeError(f"No base tables found in schema '{SOURCE_SCHEMA}'.")

    snapshot_rows = []
    for table_name, (data_length, index_length) in sorted(sizes.items()):
        row_count = get_exact_row_count(engine, SOURCE_SCHEMA, table_name)
        snapshot_rows.append(
            {
                "table_name": table_name,
                "row_count": row_count,
                "data_length_bytes": data_length,
                "index_length_bytes": index_length,
            }
        )
        total_kb = (data_length + index_length) / 1024
        print(f"    {table_name}: {row_count:,} rows, {total_kb:,.1f} KB")

    print(f"[3/3] Writing snapshot to {MONITORING_SCHEMA}.table_growth_log...")
    insert_snapshot(engine, snapshot_rows)

    print(f"Done. Snapshotted {len(snapshot_rows)} tables.")


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as e:
        print(f"Snapshot failed: {e}")
        raise SystemExit(1)
    