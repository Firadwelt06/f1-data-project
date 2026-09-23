"""
schema.py

Defines the normalized (3NF) F1 schema using SQLAlchemy Core.

Why Core and not the ORM: we don't need Python objects with behavior
attached (no need for a Driver class with methods) - we just need table
definitions we can hand to `metadata.create_all(engine)` and later use
with `insert()`/`select()` constructs. Core also matches how
load_staging.py already talks to the DB, so there's one mental model
across the whole project instead of two (Core here, ORM there).

This file ONLY defines structure (tables, columns, types, keys).
It does not load data - that's a separate transform/load script that
reads from the stg_ tables, casts types, converts '\\N' to NULL, and
inserts into these tables. We'll build that next.

Run this file directly to create the tables in your database:
    python schema.py
"""

import os
from dotenv import load_dotenv
from sqlalchemy import (
    create_engine,
    MetaData,
    Table,
    Column,
    Integer,
    SmallInteger,
    String,
    Date,
    Time,
    Boolean,
    DECIMAL,
    ForeignKey,
    PrimaryKeyConstraint,
    Index,
)

load_dotenv()

# --- Engine setup -----------------------------------------------------
# ASSUMPTION: these are the .env variable names. If load_staging.py uses
# different names (e.g. MYSQL_USER instead of DB_USER), tell me and I'll
# line this up so both files read from the same .env keys.
DB_USER = os.environ["DB_USER"]
DB_PASSWORD = os.environ["DB_PASSWORD"]
DB_HOST = os.environ["DB_HOST"]
DB_PORT = os.environ.get("DB_PORT", "3306")
DB_NAME = os.environ["DB_NAME"]

engine = create_engine(
    f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)

# MetaData is SQLAlchemy Core's registry of tables. Every Table object
# below registers itself onto this object just by being constructed
# with `metadata` as its second argument. `metadata.create_all(engine)`
# at the bottom then issues CREATE TABLE for all of them, in an order
# that respects foreign key dependencies automatically.
metadata = MetaData()


# --- Dimension tables ---------------------------------------------------
# These change rarely and are referenced by many fact tables. No FKs
# pointing OUT of these tables (except constructor/driver/circuit
# lookups, which are self-contained).

seasons = Table(
    "seasons",
    metadata,
    Column("year", Integer, primary_key=True),
    # PK is the year itself (not a surrogate id) - "year" is already a
    # natural, stable, human-meaningful key with no risk of duplicates
    # or reassignment, so a surrogate int would just be redundant.
    Column("url", String(255)),
)

status = Table(
    "status",
    metadata,
    Column("statusId", Integer, primary_key=True),
    Column("status", String(100), nullable=False),
)

circuits = Table(
    "circuits",
    metadata,
    Column("circuitId", Integer, primary_key=True),
    Column("circuitRef", String(100), nullable=False, unique=True),
    Column("name", String(255), nullable=False),
    Column("location", String(100)),
    Column("country", String(100)),
    # DECIMAL(9,6) for lat/lng: avoids float rounding drift and gives
    # ~11cm precision at the equator - far more than needed, but the
    # point is determinism (DECIMAL math is exact; FLOAT math isn't).
    Column("lat", DECIMAL(9, 6)),
    Column("lng", DECIMAL(9, 6)),
    # alt: README documents 0 as a known placeholder for post-2024
    # circuits (data not available from the source API). We store it
    # as-is rather than NULL, matching the source dataset's convention -
    # NULL would imply "unknown," 0 here means "known to be missing."
    Column("alt", SmallInteger),
    Column("url", String(255)),
)

drivers = Table(
    "drivers",
    metadata,
    Column("driverId", Integer, primary_key=True),
    Column("driverRef", String(100), nullable=False, unique=True),
    Column("number", SmallInteger, nullable=True),
    Column("code", String(3), nullable=True),
    Column("forename", String(100), nullable=False),
    Column("surname", String(100), nullable=False),
    Column("dob", Date, nullable=True),
    Column("nationality", String(100)),
    Column("url", String(255)),
)

constructors = Table(
    "constructors",
    metadata,
    Column("constructorId", Integer, primary_key=True),
    Column("constructorRef", String(100), nullable=False, unique=True),
    Column("name", String(255), nullable=False),
    Column("nationality", String(100)),
    Column("url", String(255)),
)


# --- Core fact table: races ---------------------------------------------
# races sits in the middle of the schema - almost every other fact table
# points to it. Defined before results/qualifying/etc. because those
# tables' ForeignKey("races.raceId") references need this table to
# exist first in the script (SQLAlchemy also handles ordering at
# create_all time, but readability benefits from defining it early too).

races = Table(
    "races",
    metadata,
    Column("raceId", Integer, primary_key=True),
    Column("year", Integer, ForeignKey("seasons.year"), nullable=False),
    Column("round", SmallInteger, nullable=False),
    Column("circuitId", Integer, ForeignKey("circuits.circuitId"), nullable=False),
    Column("name", String(255), nullable=False),
    Column("date", Date, nullable=False),
    Column("time", Time, nullable=True),
    Column("url", String(255)),
    Column("fp1_date", Date, nullable=True),
    Column("fp1_time", Time, nullable=True),
    Column("fp2_date", Date, nullable=True),
    Column("fp2_time", Time, nullable=True),
    Column("fp3_date", Date, nullable=True),
    Column("fp3_time", Time, nullable=True),
    Column("quali_date", Date, nullable=True),
    Column("quali_time", Time, nullable=True),
    Column("sprint_date", Date, nullable=True),
    Column("sprint_time", Time, nullable=True),
)


# --- Event-level fact tables ---------------------------------------------

results = Table(
    "results",
    metadata,
    Column("resultId", Integer, primary_key=True),
    Column("raceId", Integer, ForeignKey("races.raceId"), nullable=False),
    Column("driverId", Integer, ForeignKey("drivers.driverId"), nullable=False),
    Column("constructorId", Integer, ForeignKey("constructors.constructorId"), nullable=False),
    Column("number", SmallInteger, nullable=True),
    Column("grid", SmallInteger, nullable=False),
    # position is nullable: DNF/DSQ/etc drivers have no finishing
    # position. positionText carries the human-readable code ('R', 'D',
    # 'W') for those cases - keeping position purely numeric means
    # ORDER BY / AVG / etc. on it never has to filter out garbage text.
    Column("position", SmallInteger, nullable=True),
    Column("positionText", String(10), nullable=False),
    Column("positionOrder", SmallInteger, nullable=False),
    # DECIMAL not FLOAT: half-point races exist (e.g. 2021 Belgian GP).
    # Cumulative points across a season are exactly the kind of running
    # total where float rounding error compounds - DECIMAL guarantees
    # 0.5 + 0.5 is always exactly 1.0.
    Column("points", DECIMAL(6, 2), nullable=False),
    Column("laps", SmallInteger, nullable=False),
    # time/fastestLapTime kept as strings ('1:23.456') rather than a
    # TIME/DECIMAL type - they're display-only. milliseconds (below) is
    # the actual numeric column used for any sorting or math, so we
    # never need to parse the string representation.
    Column("time", String(30), nullable=True),
    Column("milliseconds", Integer, nullable=True),
    Column("fastestLap", SmallInteger, nullable=True),
    Column("rank", SmallInteger, nullable=True),
    Column("fastestLapTime", String(20), nullable=True),
    Column("fastestLapSpeed", DECIMAL(6, 3), nullable=True),
    Column("statusId", Integer, ForeignKey("status.statusId"), nullable=False),
)

qualifying = Table(
    "qualifying",
    metadata,
    Column("qualifyId", Integer, primary_key=True),
    Column("raceId", Integer, ForeignKey("races.raceId"), nullable=False),
    Column("driverId", Integer, ForeignKey("drivers.driverId"), nullable=False),
    Column("constructorId", Integer, ForeignKey("constructors.constructorId"), nullable=False),
    Column("number", SmallInteger, nullable=False),
    Column("position", SmallInteger, nullable=True),
    Column("q1", String(20), nullable=True),
    Column("q2", String(20), nullable=True),
    Column("q3", String(20), nullable=True),
)

sprint_results = Table(
    "sprint_results",
    metadata,
    Column("resultId", Integer, primary_key=True),
    Column("raceId", Integer, ForeignKey("races.raceId"), nullable=False),
    Column("driverId", Integer, ForeignKey("drivers.driverId"), nullable=False),
    Column("constructorId", Integer, ForeignKey("constructors.constructorId"), nullable=False),
    Column("number", SmallInteger, nullable=False),
    Column("grid", SmallInteger, nullable=False),
    Column("position", SmallInteger, nullable=True),
    Column("positionText", String(10), nullable=False),
    Column("positionOrder", SmallInteger, nullable=False),
    Column("points", DECIMAL(6, 2), nullable=False),
    Column("laps", SmallInteger, nullable=False),
    Column("time", String(30), nullable=True),
    Column("milliseconds", Integer, nullable=True),
    Column("fastestLap", SmallInteger, nullable=True),
    Column("fastestLapTime", String(20), nullable=True),
    Column("statusId", Integer, ForeignKey("status.statusId"), nullable=False),
)


# --- Composite-key fact tables -------------------------------------------
# These four don't have a natural single-column surrogate key in the
# source data. Rather than inventing an artificial auto-increment id
# (which would add a column with no real-world meaning), we use a
# composite PRIMARY KEY of the columns that are already guaranteed
# unique together. This also gives us a free, meaningful index for
# lookups like "all pit stops for this driver in this race."

pit_stops = Table(
    "pit_stops",
    metadata,
    Column("raceId", Integer, ForeignKey("races.raceId"), nullable=False),
    Column("driverId", Integer, ForeignKey("drivers.driverId"), nullable=False),
    Column("stop", SmallInteger, nullable=False),
    Column("lap", SmallInteger, nullable=False),
    Column("time", Time, nullable=True),
    Column("duration", DECIMAL(6, 3), nullable=True),
    Column("milliseconds", Integer, nullable=True),
    PrimaryKeyConstraint("raceId", "driverId", "stop"),
)

lap_times = Table(
    "lap_times",
    metadata,
    Column("raceId", Integer, ForeignKey("races.raceId"), nullable=False),
    Column("driverId", Integer, ForeignKey("drivers.driverId"), nullable=False),
    Column("lap", SmallInteger, nullable=False),
    Column("position", SmallInteger, nullable=True),
    Column("time", String(20), nullable=True),
    Column("milliseconds", Integer, nullable=True),
    PrimaryKeyConstraint("raceId", "driverId", "lap"),
)

practice_results = Table(
    "practice_results",
    metadata,
    Column("raceId", Integer, ForeignKey("races.raceId"), nullable=False),
    Column("driverId", Integer, ForeignKey("drivers.driverId"), nullable=False),
    Column("session", String(3), nullable=False),  # 'FP1', 'FP2', 'FP3'
    Column("position", SmallInteger, nullable=True),
    Column("bestLapTime", String(20), nullable=True),
    Column("laps", SmallInteger, nullable=True),
    PrimaryKeyConstraint("raceId", "driverId", "session"),
)

tire_stints = Table(
    "tire_stints",
    metadata,
    Column("raceId", Integer, ForeignKey("races.raceId"), nullable=False),
    Column("driverId", Integer, ForeignKey("drivers.driverId"), nullable=False),
    Column("stint", SmallInteger, nullable=False),
    Column("compound", String(20), nullable=True),
    Column("startLap", SmallInteger, nullable=False),
    Column("endLap", SmallInteger, nullable=False),
    Column("lapsOnTire", SmallInteger, nullable=False),
    PrimaryKeyConstraint("raceId", "driverId", "stint"),
)


# --- Standings tables -----------------------------------------------------

driver_standings = Table(
    "driver_standings",
    metadata,
    Column("driverStandingsId", Integer, primary_key=True),
    Column("raceId", Integer, ForeignKey("races.raceId"), nullable=False),
    Column("driverId", Integer, ForeignKey("drivers.driverId"), nullable=False),
    Column("points", DECIMAL(6, 2), nullable=False),
    Column("position", SmallInteger, nullable=True),
    Column("positionText", String(10), nullable=False),
    Column("wins", SmallInteger, nullable=False),
)

constructor_standings = Table(
    "constructor_standings",
    metadata,
    Column("constructorStandingsId", Integer, primary_key=True),
    Column("raceId", Integer, ForeignKey("races.raceId"), nullable=False),
    Column("constructorId", Integer, ForeignKey("constructors.constructorId"), nullable=False),
    Column("points", DECIMAL(6, 2), nullable=False),
    Column("position", SmallInteger, nullable=True),
    Column("positionText", String(10), nullable=False),
    Column("wins", SmallInteger, nullable=False),
)

constructor_results = Table(
    "constructor_results",
    metadata,
    Column("constructorResultsId", Integer, primary_key=True),
    Column("raceId", Integer, ForeignKey("races.raceId"), nullable=False),
    Column("constructorId", Integer, ForeignKey("constructors.constructorId"), nullable=False),
    Column("points", DECIMAL(6, 2), nullable=False),
    Column("status", String(1), nullable=True),  # 'D' if disqualified, else NULL
)


# --- Weather: a 1:1 extension of races -----------------------------------
# One row per race (confirmed - not merging into `races` itself, per our
# discussion: keeping it separate signals "this is FastF1-sourced,
# 2025/2026-only data" as a distinct concern from the core race record,
# and keeps `races` from growing a pile of nullable columns that are
# NULL for every single pre-2025 row (78 years of NULLs vs 35 rows of
# real data - that asymmetry is a normalization smell on its own).
# raceId is BOTH the primary key AND a foreign key here, enforcing the
# 1:1 relationship at the schema level - you cannot have two weather
# rows for the same race, and you cannot have a weather row for a race
# that doesn't exist.

weather = Table(
    "weather",
    metadata,
    Column("raceId", Integer, ForeignKey("races.raceId"), primary_key=True),
    Column("airTempAvg", DECIMAL(4, 1), nullable=True),
    Column("airTempMin", DECIMAL(4, 1), nullable=True),
    Column("airTempMax", DECIMAL(4, 1), nullable=True),
    Column("trackTempAvg", DECIMAL(4, 1), nullable=True),
    Column("trackTempMin", DECIMAL(4, 1), nullable=True),
    Column("trackTempMax", DECIMAL(4, 1), nullable=True),
    Column("humidityAvg", DECIMAL(4, 1), nullable=True),
    Column("windSpeedAvg", DECIMAL(4, 1), nullable=True),
    Column("windSpeedMax", DECIMAL(4, 1), nullable=True),
    Column("rainfall", Boolean, nullable=True),
)


# --- Indexes beyond what PK/FK/unique already give us for free ---------
# InnoDB auto-indexes every PRIMARY KEY, every ForeignKey column, and
# every unique=True column - so driverId, raceId, constructorId,
# statusId etc. are already indexed everywhere they appear as FKs.
# These five are the exceptions that needed a deliberate decision:
#
# lap_times/pit_stops/tire_stints/practice_results all use a composite
# PK led by raceId (e.g. (raceId, driverId, lap)). A composite index
# only serves queries that filter on its leading column(s) - so
# "WHERE driverId = X" with no raceId filter (a driver's whole career
# in one of these tables) can't use the PK at all, since driverId isn't
# leftmost. Adding a single-column index on driverId closes that gap.
#
# races gets (year, round) rather than relying on year alone: year is
# already indexed via its FK to seasons, but era-based analysis
# (Stage 3's "constructor dominance by era") filters AND orders by
# year, round together - the composite avoids a filesort on top of
# the index scan that a year-only index would still require.

Index("idx_lap_times_driverid", lap_times.c.driverId)
Index("idx_pit_stops_driverid", pit_stops.c.driverId)
Index("idx_tire_stints_driverid", tire_stints.c.driverId)
Index("idx_practice_results_driverid", practice_results.c.driverId)
Index("idx_races_year_round", races.c.year, races.c.round)


# --- Analytics table: Stage 5 ML feature table --------------------------
# Deliberately denormalized: one row per (raceId, driverId), pre-joining
# race/circuit/constructor context that would otherwise take a 5+ table
# join to reconstruct. This is NOT populated by transform_load.py - it's
# derived data, built by build_analytics_table.py from the normalized
# tables above (via window functions for rolling form). Re-run that
# script after loading new races to refresh it.
#
# COLUMNS ARE SPLIT INTO TWO HONEST GROUPS. This matters for Stage 5:
#   - "Pre-race features": known before the race starts. Safe model inputs.
#   - "Outcome / label columns": only known after the race finishes.
#     These are prediction TARGETS, or post-hoc analysis fields - never
#     model inputs for a pre-race prediction task. Mixing them in as
#     features would be data leakage (the model "sees the answer").
# weather.csv is intentionally NOT included here at all: it's measured
# DURING the race (not forecast), so it's a post-hoc analysis field, not
# a legitimate pre-race predictor - keeping it out avoids the temptation
# to leak it in later without noticing.

analytics_driver_race = Table(
    "analytics_driver_race",
    metadata,
    Column("raceId", Integer, ForeignKey("races.raceId"), nullable=False),
    Column("driverId", Integer, ForeignKey("drivers.driverId"), nullable=False),
    Column("constructorId", Integer, ForeignKey("constructors.constructorId"), nullable=False),
    Column("circuitId", Integer, ForeignKey("circuits.circuitId"), nullable=False),
    Column("year", Integer, nullable=False),
    Column("round", SmallInteger, nullable=False),

    # --- Pre-race features (safe model inputs) ---
    Column("grid", SmallInteger, nullable=False),
    Column("qualifyingPosition", SmallInteger, nullable=True),
    Column("driverAgeAtRaceDays", Integer, nullable=True),
    Column("priorRaceCount", Integer, nullable=True),
    Column("priorWins", Integer, nullable=True),
    Column("priorWinPct", DECIMAL(5, 3), nullable=True),
    Column("priorWinStreak", SmallInteger, nullable=True),
    Column("rollingAvgPoints_last5", DECIMAL(6, 3), nullable=True),
    Column("rollingAvgFinishPos_last5", DECIMAL(6, 3), nullable=True),
    Column("constructorRollingAvgPoints_last5", DECIMAL(6, 3), nullable=True),
    Column("constructorWinPct_last10", DECIMAL(5, 3), nullable=True),

    # --- Outcome / label columns (targets or post-hoc only - NOT features) ---
    Column("finishPosition", SmallInteger, nullable=True),
    Column("positionOrder", SmallInteger, nullable=False),
    Column("points", DECIMAL(6, 2), nullable=False),
    Column("podium", Boolean, nullable=False),
    Column("dnf", Boolean, nullable=False),
    Column("pitStopCount", SmallInteger, nullable=False),
    Column("avgPitStopDurationSec", DECIMAL(6, 3), nullable=True),
    Column("fastestLapRank", SmallInteger, nullable=True),
    Column("lapsCompleted", SmallInteger, nullable=False),

    PrimaryKeyConstraint("raceId", "driverId"),
)


if __name__ == "__main__":
    # Creates every table defined above, in dependency order, if it
    # doesn't already exist. Safe to re-run - create_all() skips tables
    # that are already present rather than erroring.
    metadata.create_all(engine)
    print(f"Created {len(metadata.tables)} tables in '{DB_NAME}'.")
