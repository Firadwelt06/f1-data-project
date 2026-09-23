"""
build_analytics_table.py

Builds/refreshes analytics_driver_race - the Stage 5 ML feature table -
from the normalized schema. Full rebuild each run (TRUNCATE + INSERT):
the table is small enough (~27K rows, one per driver per race) that
recomputing from scratch is simpler and safer than trying to
incrementally patch rolling averages, which would need to cascade
recalculation forward through every later race anyway.

Run this AFTER transform_load.py and add_indexes.py, and re-run it any
time new races are loaded:
    python build_analytics_table.py

Two correctness details worth reading before touching the SQL below:

1. LEAKAGE GUARD: every rolling-average window function uses
   `ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING` - never
   `ROWS BETWEEN 5 PRECEDING AND CURRENT ROW`. The word "AND 1
   PRECEDING" is what stops the window one row short of the row being
   computed, so "this driver's current race" never gets folded into
   "the average of this driver's last 5 races." Get that boundary wrong
   and every rolling feature quietly leaks the answer into itself.

2. CONSTRUCTOR FORM IS COMPUTED AT THE CONSTRUCTOR-RACE GRAIN, not the
   driver-race grain. If we naively partitioned by constructorId over
   the driver-race rows directly, "5 PRECEDING" would mean 5 preceding
   DRIVER ROWS - since each constructor fields two drivers per race,
   that's really only ~2.5 races of history, not 5. The `constructor_form`
   CTE first collapses to one row per (raceId, constructorId) using
   constructor_results (which already aggregates both drivers' points),
   THEN applies the rolling window on top of that - so "last 5" actually
   means 5 races.
"""

from sqlalchemy import text

try:
    from . import schema
except ImportError:  # pragma: no cover - direct script execution fallback
    import schema

engine = schema.engine


def ensure_analytics_columns(conn):
    existing = conn.execute(text("""
        SELECT COLUMN_NAME
        FROM information_schema.columns
        WHERE table_schema = DATABASE()
          AND table_name = 'analytics_driver_race'
    """)).scalars().all()
    existing_set = set(existing)

    for column_name, definition in {
        "priorWins": "INT NULL",
        "priorWinPct": "DECIMAL(5,3) NULL",
        "priorWinStreak": "INT NULL",
        "constructorWinPct_last10": "DECIMAL(5,3) NULL",
    }.items():
        if column_name not in existing_set:
            print(f"  [ADD] column '{column_name}' to analytics_driver_race")
            conn.execute(text(f"ALTER TABLE analytics_driver_race ADD COLUMN {column_name} {definition}"))


BUILD_SQL = """
WITH RECURSIVE deduped_results AS (
    SELECT *
    FROM (
        SELECT
            r.*,
            ROW_NUMBER() OVER (
                PARTITION BY r.raceId, r.driverId
                ORDER BY r.positionOrder ASC
            ) AS rn
        FROM results r
    ) ranked
    WHERE rn = 1
),
driver_race_order AS (
    SELECT
        dr.*,
        ROW_NUMBER() OVER (
            PARTITION BY dr.driverId
            ORDER BY ra.date, dr.raceId
        ) AS race_seq
    FROM deduped_results dr
    JOIN races ra ON ra.raceId = dr.raceId
),
driver_win_streaks AS (
    SELECT
        dro.driverId,
        dro.raceId,
        dro.race_seq,
        CASE WHEN dro.positionOrder = 1 THEN 1 ELSE 0 END AS win_streak
    FROM driver_race_order dro
    WHERE dro.race_seq = 1

    UNION ALL

    SELECT
        dro.driverId,
        dro.raceId,
        dro.race_seq,
        CASE
            WHEN dro.positionOrder = 1 THEN dws.win_streak + 1
            ELSE 0
        END AS win_streak
    FROM driver_race_order dro
    JOIN driver_win_streaks dws
      ON dws.driverId = dro.driverId
     AND dws.race_seq + 1 = dro.race_seq
),
constructor_race_win_pct AS (
    SELECT
        race_summary.raceId,
        race_summary.constructorId,
        AVG(race_summary.raceWonByConstructor) OVER (
            PARTITION BY race_summary.constructorId
            ORDER BY ra.date
            ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING
        ) AS constructorWinPct_last10
    FROM (
        SELECT
            r.raceId,
            r.constructorId,
            MAX(CASE WHEN r.positionOrder = 1 THEN 1 ELSE 0 END) AS raceWonByConstructor
        FROM deduped_results r
        GROUP BY r.raceId, r.constructorId
    ) race_summary
    JOIN races ra ON ra.raceId = race_summary.raceId
),
constructor_form AS (
    SELECT
        cr.raceId,
        cr.constructorId,
        AVG(cr.points) OVER (
            PARTITION BY cr.constructorId
            ORDER BY ra.date
            ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING
        ) AS constructorRollingAvgPoints_last5
    FROM constructor_results cr
    JOIN races ra ON ra.raceId = cr.raceId
),
pit_summary AS (
    SELECT
        raceId,
        driverId,
        COUNT(*) AS pitStopCount,
        AVG(duration) AS avgPitStopDurationSec
    FROM pit_stops
    GROUP BY raceId, driverId
)
SELECT
    r.raceId,
    r.driverId,
    r.constructorId,
    ra.circuitId,
    ra.year,
    ra.round,

    -- pre-race features --
    r.grid,
    q.position AS qualifyingPosition,
    DATEDIFF(ra.date, d.dob) AS driverAgeAtRaceDays,
    COUNT(*) OVER (
        PARTITION BY r.driverId
        ORDER BY ra.date
        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
    ) AS priorRaceCount,
    SUM(CASE WHEN r.positionOrder = 1 THEN 1 ELSE 0 END) OVER (
        PARTITION BY r.driverId
        ORDER BY ra.date
        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
    ) AS priorWins,
    CASE
        WHEN COUNT(*) OVER (
            PARTITION BY r.driverId
            ORDER BY ra.date
            ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
        ) = 0 THEN NULL
        ELSE (
            SUM(CASE WHEN r.positionOrder = 1 THEN 1 ELSE 0 END) OVER (
                PARTITION BY r.driverId
                ORDER BY ra.date
                ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
            ) * 1.0
        ) / NULLIF(
            COUNT(*) OVER (
                PARTITION BY r.driverId
                ORDER BY ra.date
                ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
            ), 0
        )
    END AS priorWinPct,
    COALESCE(prev_win_streak.win_streak, 0) AS priorWinStreak,
    AVG(r.points) OVER (
        PARTITION BY r.driverId
        ORDER BY ra.date
        ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING
    ) AS rollingAvgPoints_last5,
    AVG(r.positionOrder) OVER (
        PARTITION BY r.driverId
        ORDER BY ra.date
        ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING
    ) AS rollingAvgFinishPos_last5,
    cf.constructorRollingAvgPoints_last5,
    crwp.constructorWinPct_last10,

    -- outcome / label columns (targets or post-hoc only - not features) --
    r.position AS finishPosition,
    r.positionOrder,
    r.points,
    (r.position IS NOT NULL AND r.position <= 3) AS podium,
    (r.position IS NULL) AS dnf,
    COALESCE(ps.pitStopCount, 0) AS pitStopCount,
    ps.avgPitStopDurationSec,
    r.rank AS fastestLapRank,
    r.laps AS lapsCompleted

FROM driver_race_order r
JOIN races ra ON ra.raceId = r.raceId
JOIN drivers d ON d.driverId = r.driverId
LEFT JOIN driver_win_streaks prev_win_streak
    ON prev_win_streak.driverId = r.driverId
   AND prev_win_streak.race_seq = r.race_seq - 1
LEFT JOIN qualifying q ON q.raceId = r.raceId AND q.driverId = r.driverId
LEFT JOIN pit_summary ps ON ps.raceId = r.raceId AND ps.driverId = r.driverId
LEFT JOIN constructor_form cf ON cf.raceId = r.raceId AND cf.constructorId = r.constructorId
LEFT JOIN constructor_race_win_pct crwp ON crwp.raceId = r.raceId AND crwp.constructorId = r.constructorId
"""


def main():
    with engine.begin() as conn:
        ensure_analytics_columns(conn)

        print("Truncating analytics_driver_race...")
        conn.execute(text("TRUNCATE TABLE analytics_driver_race"))

        print("Rebuilding from normalized tables (window functions - may take a moment)...")
        conn.execute(text(f"""
            INSERT INTO analytics_driver_race (
                raceId, driverId, constructorId, circuitId, year, round,
                grid, qualifyingPosition, driverAgeAtRaceDays, priorRaceCount,
                priorWins, priorWinPct, priorWinStreak,
                rollingAvgPoints_last5, rollingAvgFinishPos_last5,
                constructorRollingAvgPoints_last5, constructorWinPct_last10,
                finishPosition, positionOrder, points, podium, dnf,
                pitStopCount, avgPitStopDurationSec, fastestLapRank, lapsCompleted
            )
            {BUILD_SQL}
        """))

        count = conn.execute(text("SELECT COUNT(*) FROM analytics_driver_race")).scalar()
        print(f"Done. analytics_driver_race now has {count} rows.")


if __name__ == "__main__":
    main()
