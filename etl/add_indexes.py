"""
add_indexes.py

Applies the Stage 2 indexes (defined in schema.py) to a database whose
tables already exist. `metadata.create_all()` in schema.py only creates
tables that don't exist yet - it won't retroactively add an index to a
table that's already there, which is our situation now that
transform_load.py has already populated everything. Hence this
separate, small script.

Idempotent by design: checks information_schema for each index's
existence before creating it, so re-running this after adding a sixth
index later (e.g. once Stage 3's EXPLAIN work reveals a new need) only
creates the new one, not duplicates of the first five.
"""

from sqlalchemy import text

try:
    from . import schema
except ImportError:  # pragma: no cover - direct script execution fallback
    import schema

engine = schema.engine

# Each entry: (index_name, table_name, "column_list_for_create_index_sql")
INDEXES = [
    ("idx_lap_times_driverid", "lap_times", "driverId"),
    ("idx_pit_stops_driverid", "pit_stops", "driverId"),
    ("idx_tire_stints_driverid", "tire_stints", "driverId"),
    ("idx_practice_results_driverid", "practice_results", "driverId"),
    ("idx_races_year_round", "races", "year, round"),
]


def index_exists(conn, index_name, table_name):
    result = conn.execute(
        text("""
            SELECT COUNT(*)
            FROM information_schema.statistics
            WHERE table_schema = DATABASE()
              AND table_name = :table_name
              AND index_name = :index_name
        """),
        {"table_name": table_name, "index_name": index_name},
    )
    return result.scalar() > 0


def main():
    with engine.begin() as conn:
        for index_name, table_name, columns in INDEXES:
            if index_exists(conn, index_name, table_name):
                print(f"  [SKIP] {index_name} already exists on {table_name}")
                continue
            conn.execute(text(f"CREATE INDEX {index_name} ON {table_name} ({columns})"))
            print(f"  [OK]   created {index_name} on {table_name} ({columns})")

    print("\nDone.")


if __name__ == "__main__":
    main()
