"""
transform_load.py

Moves data from the permissive stg_* staging tables (everything
VARCHAR(500), no constraints - see Stage 1) into the normalized 3NF
schema defined in schema.py.

This is where the actual "normalization" work happens in practice:
staging holds strings, this script decides what those strings actually
mean (an int? a date? a NULL?) and enforces it on the way in.

RE-RUN BEHAVIOR: incremental + upsert. Every run reads ALL rows currently
in staging and upserts them - new raceIds get inserted, raceIds that
already exist get their non-key columns overwritten with whatever
staging currently holds. This means:
  - Re-running is always safe (idempotent) - no duplicate rows.
  - If the upstream dataset publishes a correction (this has actually
    happened before - see CHANGELOG.md v2, which fixed the `position`
    column after initial release), re-running this script picks up
    the fix automatically, because staging will hold the corrected
    value and the upsert overwrites the old one.
  - It does NOT detect or report a "3 rows changed since last run" diff.
    If you want that visibility later (useful for Stage 4 monitoring),
    we can add a before/after row hash comparison then - not needed yet.

ASSUMPTION (please confirm): staging tables are named `stg_<table>`
(e.g. `stg_races`, `stg_results`) and their columns use the exact same
names as the source CSVs / SCHEMA.md (e.g. `raceId`, `circuitId`), plus
your two provenance columns (`source_file`, `loaded_at`) which we simply
never select. If your staging naming differs, tell me and I'll adjust
STAGING_PREFIX / column names below.
"""

import os
import datetime
from decimal import Decimal, InvalidOperation

from dotenv import load_dotenv
from sqlalchemy import create_engine, select, table as sa_table, column as sa_column, func
from sqlalchemy.dialects.mysql import insert as mysql_insert

try:
    from . import schema
except ImportError:  # pragma: no cover - direct script execution fallback
    import schema

load_dotenv()

STAGING_PREFIX = "stg_"
CHUNK_SIZE = 5000  # upper bound; narrowed per-table below when needed

# MySQL's prepared-statement placeholder limit is 65,535 total bound
# parameters. A batch's placeholder count is (rows_in_batch * columns),
# so a fixed row-based CHUNK_SIZE that's safe for narrow tables (e.g.
# `seasons`, 2 columns -> 10,000 placeholders at 5000 rows) can blow
# past the limit on wide tables (e.g. `results`, 18 columns -> 90,000
# placeholders at 5000 rows, which is what caused the "too many
# placeholders" error). Instead of hardcoding a smaller CHUNK_SIZE for
# every table, we compute a safe row count from the column count, with
# a margin under the real 65,535 ceiling.
MAX_PLACEHOLDERS_PER_STATEMENT = 60000


def safe_chunk_size(num_columns):
    return max(1, MAX_PLACEHOLDERS_PER_STATEMENT // num_columns)

engine = schema.engine


# --- Type casting helpers -------------------------------------------------
# Every staging value arrives as a Python str or None. These helpers
# turn that string into the real type the normalized column expects,
# and treat '\N' (the source dataset's null convention - see README)
# and '' the same as an actual NULL.

def _is_null_marker(v):
    return v is None or v == "" or v == r"\N"


def cast_int(v):
    if _is_null_marker(v):
        return None
    return int(v)


def cast_decimal(v):
    if _is_null_marker(v):
        return None
    s = str(v).strip()
    # Some source columns encode durations as H:MM:SS.sss or M:SS.sss
    # e.g. '1:29.401' or '16:44.718'. Convert these to total seconds.
    if ":" in s:
        parts = s.split(":")
        total = Decimal("0")
        multiplier = Decimal("1")
        # walk right-to-left: seconds, minutes, hours...
        for p in reversed(parts):
            total += Decimal(p) * multiplier
            multiplier *= Decimal(60)
        # DECIMAL(6,3) max is 999.999 in our schema; treat larger values
        # as NULL rather than raising a DB out-of-range error during insert.
        if total >= Decimal("1000"):
            return None
        return total
    return Decimal(s)


def cast_str(v):
    if _is_null_marker(v):
        return None
    s = str(v)
    # Some rows include a pandas Timedelta-like string: '0 days 00:01:17.252000'
    # Trim the leading '0 days ' and reduce microseconds to 3 decimals so
    # they fit into the target VARCHAR columns (e.g. 20 chars).
    if s.startswith("0 days "):
        s = s.replace("0 days ", "", 1)
    if "." in s:
        left, right = s.split(".", 1)
        right = right[:3]  # keep milliseconds
        s = f"{left}.{right}".rstrip('.')
    return s


def cast_date(v):
    if _is_null_marker(v):
        return None
    return datetime.datetime.strptime(v, "%Y-%m-%d").date()


def cast_time(v):
    # Handles both 'HH:MM:SS' and 'HH:MM:SS.ffffff', and also the
    # source dataset's UTC-suffixed values like '04:00:00Z'.
    if _is_null_marker(v):
        return None

    v = str(v).strip()
    if v.endswith("Z"):
        v = v[:-1]
    if "." in v:
        v = v.split(".")[0]
    return datetime.datetime.strptime(v, "%H:%M:%S").time()


def cast_bool(v):
    if _is_null_marker(v):
        return None
    return str(v).strip().lower() in ("1", "true", "t", "yes")


CASTERS = {
    "int": cast_int,
    "decimal": cast_decimal,
    "str": cast_str,
    "date": cast_date,
    "time": cast_time,
    "bool": cast_bool,
}


# --- Per-table configuration ------------------------------------------------
# Order matters: parents must appear before the children that FK to them.
# Each entry: (target Table object, {column_name: cast_type})

TABLE_CONFIGS = [
    (schema.seasons, {"year": "int", "url": "str"}),
    (schema.status, {"statusId": "int", "status": "str"}),
    (schema.circuits, {
        "circuitId": "int", "circuitRef": "str", "name": "str", "location": "str",
        "country": "str", "lat": "decimal", "lng": "decimal", "alt": "int", "url": "str",
    }),
    (schema.drivers, {
        "driverId": "int", "driverRef": "str", "number": "int", "code": "str",
        "forename": "str", "surname": "str", "dob": "date", "nationality": "str", "url": "str",
    }),
    (schema.constructors, {
        "constructorId": "int", "constructorRef": "str", "name": "str",
        "nationality": "str", "url": "str",
    }),
    (schema.races, {
        "raceId": "int", "year": "int", "round": "int", "circuitId": "int", "name": "str",
        "date": "date", "time": "time", "url": "str",
        "fp1_date": "date", "fp1_time": "time", "fp2_date": "date", "fp2_time": "time",
        "fp3_date": "date", "fp3_time": "time", "quali_date": "date", "quali_time": "time",
        "sprint_date": "date", "sprint_time": "time",
    }),
    (schema.results, {
        "resultId": "int", "raceId": "int", "driverId": "int", "constructorId": "int",
        "number": "int", "grid": "int", "position": "int", "positionText": "str",
        "positionOrder": "int", "points": "decimal", "laps": "int", "time": "str",
        "milliseconds": "int", "fastestLap": "int", "rank": "int", "fastestLapTime": "str",
        "fastestLapSpeed": "decimal", "statusId": "int",
    }),
    (schema.qualifying, {
        "qualifyId": "int", "raceId": "int", "driverId": "int", "constructorId": "int",
        "number": "int", "position": "int", "q1": "str", "q2": "str", "q3": "str",
    }),
    (schema.sprint_results, {
        "resultId": "int", "raceId": "int", "driverId": "int", "constructorId": "int",
        "number": "int", "grid": "int", "position": "int", "positionText": "str",
        "positionOrder": "int", "points": "decimal", "laps": "int", "time": "str",
        "milliseconds": "int", "fastestLap": "int", "fastestLapTime": "str", "statusId": "int",
    }),
    (schema.pit_stops, {
        "raceId": "int", "driverId": "int", "stop": "int", "lap": "int",
        "time": "time", "duration": "decimal", "milliseconds": "int",
    }),
    (schema.lap_times, {
        "raceId": "int", "driverId": "int", "lap": "int", "position": "int",
        "time": "str", "milliseconds": "int",
    }),
    (schema.practice_results, {
        "raceId": "int", "driverId": "int", "session": "str", "position": "int",
        "bestLapTime": "str", "laps": "int",
    }),
    (schema.tire_stints, {
        "raceId": "int", "driverId": "int", "stint": "int", "compound": "str",
        "startLap": "int", "endLap": "int", "lapsOnTire": "int",
    }),
    (schema.driver_standings, {
        "driverStandingsId": "int", "raceId": "int", "driverId": "int", "points": "decimal",
        "position": "int", "positionText": "str", "wins": "int",
    }),
    (schema.constructor_standings, {
        "constructorStandingsId": "int", "raceId": "int", "constructorId": "int",
        "points": "decimal", "position": "int", "positionText": "str", "wins": "int",
    }),
    (schema.constructor_results, {
        "constructorResultsId": "int", "raceId": "int", "constructorId": "int",
        "points": "decimal", "status": "str",
    }),
    (schema.weather, {
        "raceId": "int", "airTempAvg": "decimal", "airTempMin": "decimal", "airTempMax": "decimal",
        "trackTempAvg": "decimal", "trackTempMin": "decimal", "trackTempMax": "decimal",
        "humidityAvg": "decimal", "windSpeedAvg": "decimal", "windSpeedMax": "decimal",
        "rainfall": "bool",
    }),
]


def cast_row(raw_row, type_map):
    """
    Cast one staging row (a dict of column_name -> raw string) into a
    dict of column_name -> properly-typed Python value, using type_map.
    Raises on the first bad value so the caller can log which column
    and row failed, rather than silently producing wrong data.
    """
    out = {}
    for col_name, cast_kind in type_map.items():
        try:
            out[col_name] = CASTERS[cast_kind](raw_row[col_name])
        except (ValueError, InvalidOperation, KeyError) as exc:
            raise ValueError(f"column '{col_name}' value {raw_row.get(col_name)!r}: {exc}")
    return out


def load_table(conn, target_table, type_map):
    stg_name = STAGING_PREFIX + target_table.name
    pk_cols = set(target_table.primary_key.columns.keys())
    update_cols = [c for c in type_map if c not in pk_cols]

    # min() of the global cap and the column-count-derived safe size:
    # narrow tables still batch at up to 5000 rows (no reason to shrink
    # those), wide tables like `results` automatically get a smaller
    # batch (e.g. 60000 // 18 = 3333 rows) that stays under MySQL's limit.
    chunk_size = min(CHUNK_SIZE, safe_chunk_size(len(type_map)))

    # Reflect the staging table loosely as raw column/text selects -
    # we don't need schema.py-level typing for staging since everything
    # there is just VARCHAR(500) anyway. A plain textual SELECT * is
    # enough; we only care about the column names to build dicts.
    stg = sa_table(stg_name, *[sa_column(c) for c in type_map])

    total_staged = conn.execute(select(func.count()).select_from(stg)).scalar()

    # NOTE: previously this used conn.execution_options(stream_results=True)
    # to open an unbuffered server-side cursor and page through it with
    # fetchmany(). That's incompatible with also calling conn.execute()
    # for the upsert INSERT on the SAME connection inside the loop -
    # PyMySQL can only have one unbuffered result active on a connection
    # at a time, so the INSERT silently aborts the still-open SELECT
    # stream after the first batch (visible as a
    # "Previous unbuffered result was left incomplete" warning), and the
    # next fetchmany() comes back empty - the loop then exits believing
    # it's done, having actually loaded only the first chunk_size rows.
    # This is why every table needing >1 chunk quietly lost the rest of
    # its rows while single-chunk tables looked fine.
    #
    # Fix: page through staging with explicit LIMIT/OFFSET queries.
    # Each one fully completes (buffered) before the upsert INSERT runs,
    # so there's no open cursor for that INSERT to disturb. We order by
    # the primary key columns so pagination is stable across separate
    # queries - without that, LIMIT/OFFSET over an unordered table isn't
    # guaranteed to return a consistent row order between calls, which
    # can silently skip or duplicate rows across page boundaries.
    pk_col_names = [c.name for c in target_table.primary_key.columns]
    order_cols = [sa_column(c) for c in pk_col_names if c in type_map]

    inserted_or_updated = 0
    skipped = 0
    offset = 0

    def flush(batch):
        if not batch:
            return
        insert_stmt = mysql_insert(target_table).values(batch)
        upsert_stmt = insert_stmt.on_duplicate_key_update(
            **{c: insert_stmt.inserted[c] for c in update_cols}
        )
        conn.execute(upsert_stmt)

    while True:
        stmt_select = select(stg)
        if order_cols:
            stmt_select = stmt_select.order_by(*order_cols)
        stmt_select = stmt_select.limit(chunk_size).offset(offset)

        rows = conn.execute(stmt_select).fetchall()
        if not rows:
            break

        batch = []
        for raw in rows:
            raw_dict = dict(raw._mapping)
            try:
                batch.append(cast_row(raw_dict, type_map))
            except ValueError as exc:
                skipped += 1
                print(f"  [SKIP] {stg_name}: {exc}")
        flush(batch)
        inserted_or_updated += len(batch)
        offset += chunk_size

    return total_staged, inserted_or_updated, skipped


def main():
    with engine.begin() as conn:
        # engine.begin() gives us one transaction per script run across
        # ALL tables. If something fails halfway through, everything
        # rolls back rather than leaving the normalized schema in a
        # half-loaded, FK-inconsistent state.
        print(f"{'table':<24}{'staged':>10}{'loaded':>10}{'skipped':>10}")
        print("-" * 54)
        for target_table, type_map in TABLE_CONFIGS:
            staged, loaded, skipped = load_table(conn, target_table, type_map)
            print(f"{target_table.name:<24}{staged:>10}{loaded:>10}{skipped:>10}")

    print("\nDone.")


if __name__ == "__main__":
    main()