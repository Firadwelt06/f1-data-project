from flask import Blueprint, render_template, request
from sqlalchemy import text

from db import get_session


def get_shared_race_driver_candidates(session, driver1_id):
    if not driver1_id:
        return []

    rows = session.execute(
        text(
            """
            SELECT DISTINCT d.driverId, d.forename, d.surname
            FROM drivers d
            JOIN results r ON r.driverId = d.driverId
            WHERE r.raceId IN (
                SELECT raceId
                FROM results
                WHERE driverId = :driver1_id
            )
            AND d.driverId != :driver1_id
            ORDER BY d.surname, d.forename
            """
        ),
        {"driver1_id": driver1_id},
    ).mappings().all()
    return rows


def get_shared_race_driver_map(session):
    rows = session.execute(
        text(
            """
            SELECT
                r1.driverId AS driver1_id,
                d2.driverId,
                d2.forename,
                d2.surname
            FROM results r1
            JOIN results r2
                ON r1.raceId = r2.raceId
                AND r1.driverId <> r2.driverId
            JOIN drivers d2 ON d2.driverId = r2.driverId
            GROUP BY r1.driverId, d2.driverId, d2.forename, d2.surname
            ORDER BY r1.driverId, d2.surname, d2.forename
            """
        )
    ).mappings().all()

    shared_by_driver = {}
    for row in rows:
        shared_by_driver.setdefault(row["driver1_id"], []).append(
            {"driverId": row["driverId"], "forename": row["forename"], "surname": row["surname"]}
        )

    return shared_by_driver


analytics_bp = Blueprint("analytics", __name__, url_prefix="/analytics")


@analytics_bp.route("/")
def index():
    return render_template("analytics/index.html")


@analytics_bp.route("/win-percentage")
def win_percentage():
    session = get_session()
    rows = session.execute(
        text(
            """
            SELECT
                d.driverId,
                d.forename,
                d.surname,
                COUNT(*) AS starts,
                SUM(CASE WHEN r.position = '1' THEN 1 ELSE 0 END) AS wins,
                ROUND(
                    SUM(CASE WHEN r.position = '1' THEN 1 ELSE 0 END) / COUNT(*) * 100, 2
                ) AS win_pct
            FROM results r
            JOIN drivers d ON d.driverId = r.driverId
            GROUP BY d.driverId, d.forename, d.surname
            HAVING starts >= 20
            ORDER BY win_pct DESC
            LIMIT 20
            """
        )
    ).mappings().all()
    return render_template("analytics/win_percentage.html", rows=rows)


@analytics_bp.route("/dominance")
def dominance():
    # Uses the RANK() OVER (PARTITION BY decade ...) version rather than the
    # plain grouped version — same underlying data, but the window function
    # gives a per-decade rank column for free instead of requiring a
    # client-side sort-then-eyeball-the-top approach.
    session = get_session()
    rows = session.execute(
        text(
            """
            WITH decade_stats AS (
                SELECT
                    (r.year - r.year % 10) AS decade,
                    c.constructorId,
                    c.name,
                    COUNT(*) AS races_entered,
                    SUM(CASE WHEN res.position = '1' THEN 1 ELSE 0 END) AS wins,
                    ROUND(
                        SUM(CASE WHEN res.position = '1' THEN 1 ELSE 0 END) / COUNT(*) * 100,
                        2
                    ) AS win_pct_in_decade,
                    SUM(res.points) AS total_points
                FROM results res
                JOIN races r ON r.raceId = res.raceId
                JOIN constructors c ON c.constructorId = res.constructorId
                GROUP BY decade, c.constructorId, c.name
                HAVING races_entered >= 10
            )
            SELECT
                decade,
                name,
                races_entered,
                wins,
                win_pct_in_decade,
                total_points,
                RANK() OVER (PARTITION BY decade ORDER BY win_pct_in_decade DESC) AS dominance_rank
            FROM decade_stats
            ORDER BY decade, dominance_rank
            """
        )
    ).mappings().all()

    decades = sorted({row["decade"] for row in rows})
    return render_template("analytics/dominance.html", rows=rows, decades=decades)


@analytics_bp.route("/pit-stops")
def pit_stops():
    session = get_session()
    rows = session.execute(
        text(
            """
            SELECT
                r.year,
                COUNT(*) AS total_stops,
                COUNT(DISTINCT ps.raceId) AS races_with_stops,
                ROUND(COUNT(*) / COUNT(DISTINCT ps.raceId), 2) AS avg_stops_per_race,
                ROUND(AVG(ps.milliseconds) / 1000, 3) AS avg_stop_duration_sec,
                ROUND(MIN(ps.milliseconds) / 1000, 3) AS fastest_stop_sec
            FROM pit_stops ps
            JOIN races r ON r.raceId = ps.raceId
            WHERE ps.milliseconds > 0
            GROUP BY r.year
            ORDER BY r.year
            """
        )
    ).mappings().all()

    years = [row["year"] for row in rows]
    avg_duration = [float(row["avg_stop_duration_sec"]) for row in rows]
    avg_stops = [float(row["avg_stops_per_race"]) for row in rows]

    return render_template(
        "analytics/pit_stops.html",
        rows=rows,
        years=years,
        avg_duration=avg_duration,
        avg_stops=avg_stops,
    )


@analytics_bp.route("/head-to-head")
def head_to_head():
    session = get_session()

    drivers = [
        dict(row)
        for row in session.execute(
            text("SELECT driverId, forename, surname FROM drivers ORDER BY surname, forename")
        ).mappings().all()
    ]

    driver1_id = request.args.get("driver1_id", type=int)
    driver2_id = request.args.get("driver2_id", type=int)
    shared_race_driver_map = get_shared_race_driver_map(session)
    shared_race_drivers = shared_race_driver_map.get(driver1_id, [])

    if driver1_id and not driver2_id:
        driver2_candidates = [d for d in shared_race_drivers]
    elif driver1_id and driver2_id and driver1_id == driver2_id:
        driver2_candidates = [d for d in shared_race_drivers if d["driverId"] != driver1_id]
    else:
        driver2_candidates = [d for d in shared_race_drivers]

    result = None
    error = None

    if driver1_id and driver2_id:
        if driver1_id == driver2_id:
            error = "Pick two different drivers."
        else:
            # The underlying query's join condition (r1.driverId < r2.driverId)
            # assumes driver1 has the lower ID. Sorting here so the query
            # matches regardless of which dropdown the user picked which
            # driver in.
            lo, hi = sorted((driver1_id, driver2_id))
            result = session.execute(
                text(
                    """
                    SELECT
                        d1.forename AS driver1_forename,
                        d1.surname  AS driver1_surname,
                        d2.forename AS driver2_forename,
                        d2.surname  AS driver2_surname,
                        COUNT(*) AS shared_races,
                        SUM(CASE WHEN r1.positionOrder < r2.positionOrder THEN 1 ELSE 0 END) AS driver1_ahead,
                        SUM(CASE WHEN r2.positionOrder < r1.positionOrder THEN 1 ELSE 0 END) AS driver2_ahead
                    FROM results r1
                    JOIN results r2
                        ON r1.raceId = r2.raceId
                        AND r1.driverId < r2.driverId
                    JOIN drivers d1 ON d1.driverId = r1.driverId
                    JOIN drivers d2 ON d2.driverId = r2.driverId
                    WHERE d1.driverId = :lo
                      AND d2.driverId = :hi
                    GROUP BY d1.driverId, d2.driverId, d1.forename, d1.surname, d2.forename, d2.surname
                    """
                ),
                {"lo": lo, "hi": hi},
            ).mappings().first()

            if result is None:
                error = "These two drivers never shared a race."

    return render_template(
        "analytics/head_to_head.html",
        drivers=drivers,
        result=result,
        error=error,
        selected_driver1=driver1_id,
        selected_driver2=driver2_id,
        driver2_candidates=driver2_candidates,
        shared_race_driver_map=shared_race_driver_map,
    )


@analytics_bp.route("/win-streaks")
def win_streaks():
    # This is the EXPLAIN-optimized, deduped rewrite of the original
    # recursive CTE, not the recursive version itself — see the note on
    # this page's template for why. Requires idx_results_race_driver_order
    # (raceId, driverId, positionOrder) to run fast; that index should
    # already exist from the Stage 3 optimization work.
    session = get_session()
    rows = session.execute(
        text(
            """
            WITH driver_race_dedup AS (
                SELECT raceId, driverId, MIN(positionOrder) AS positionOrder
                FROM results
                GROUP BY raceId, driverId
            ),
            driver_race_seq AS (
                SELECT
                    d.driverId,
                    ra.date,
                    CASE WHEN d.positionOrder = 1 THEN 1 ELSE 0 END AS is_win,
                    SUM(CASE WHEN d.positionOrder = 1 THEN 0 ELSE 1 END)
                        OVER (PARTITION BY d.driverId ORDER BY ra.date) AS streak_group
                FROM driver_race_dedup d
                JOIN races ra ON ra.raceId = d.raceId
            ),
            win_streaks AS (
                SELECT
                    driverId,
                    COUNT(*) AS streak_length
                FROM driver_race_seq
                WHERE is_win = 1
                GROUP BY driverId, streak_group
            )
            SELECT
                d.forename,
                d.surname,
                MAX(ws.streak_length) AS longest_win_streak
            FROM win_streaks ws
            JOIN drivers d ON d.driverId = ws.driverId
            GROUP BY ws.driverId, d.forename, d.surname
            ORDER BY longest_win_streak DESC
            LIMIT 15
            """
        )
    ).mappings().all()

    return render_template("analytics/win_streaks.html", rows=rows)
