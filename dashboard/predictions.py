import sys
from pathlib import Path

from flask import Blueprint, render_template, request
from sqlalchemy import text
import pandas as pd

from db import get_session, engine

# ml/ sits alongside dashboard/ under the project root, not as an installed
# package, so it needs to go on sys.path before we can import from it. This
# reuses the wrappers' own model-loading and preprocessing logic rather than
# duplicating it — if a model is retrained and its _latest.pkl is swapped,
# the dashboard picks up the new model with no code change here.
ML_DIR = Path(__file__).resolve().parent.parent / "ml"
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from infer_finish_positions import load_latest_artifacts, prep_features_for_prediction  # noqa: E402
from infer_dnf_risk import load_latest_dnf_artifacts, DEFAULT_THRESHOLD  # noqa: E402

predictions_bp = Blueprint("predictions", __name__, url_prefix="/predictions")


def classify_era(year: int) -> str:
    """Python mirror of the CASE expression used in every feature query below,
    needed for the hypothetical view where there's no race row to run SQL
    against."""
    if year < 1981:
        return "pre_1981"
    if year <= 2005:
        return "1981_2005"
    if year <= 2013:
        return "2006_2013_v8"
    if year <= 2021:
        return "2014_2021_hybrid"
    return "2022_plus_ground_effect"


def driver_name_map(session, driver_ids):
    if not driver_ids:
        return {}
    ids = tuple(driver_ids) if len(driver_ids) > 1 else (driver_ids[0], -1)
    rows = session.execute(
        text("SELECT driverId, forename, surname FROM drivers WHERE driverId IN :ids").bindparams(ids=ids)
    ).mappings().all()
    return {r["driverId"]: f"{r['forename']} {r['surname']}" for r in rows}


# Shared by retrospective (finish) and dnf-risk: the columns every model
# needs, scoped to one race. Finish-position filters to dnf = 0 downstream
# in Python (see retrospective()); DNF risk does not, since it predicts
# that very outcome for every entrant.
RACE_FEATURE_QUERY = """
    SELECT
        raceId,
        driverId,
        year,
        CASE
            WHEN year < 1981 THEN 'pre_1981'
            WHEN year BETWEEN 1981 AND 2005 THEN '1981_2005'
            WHEN year BETWEEN 2006 AND 2013 THEN '2006_2013_v8'
            WHEN year BETWEEN 2014 AND 2021 THEN '2014_2021_hybrid'
            ELSE '2022_plus_ground_effect'
        END AS era,
        grid,
        COALESCE(qualifyingPosition, grid) AS qualifyingPosition,
        driverAgeAtRaceDays,
        priorRaceCount,
        rollingAvgPoints_last5,
        rollingAvgFinishPos_last5,
        constructorRollingAvgPoints_last5,
        priorWins,
        priorWinPct,
        constructorWinPct_last10,
        priorWinStreak,
        dnf,
        finishPosition
    FROM analytics_driver_race
    WHERE raceId = :race_id
"""


@predictions_bp.route("/")
def index():
    return render_template("predictions/index.html")


def _covered_races(session):
    return session.execute(
        text(
            """
            SELECT DISTINCT r.raceId, r.year, r.round, r.name
            FROM races r
            JOIN analytics_driver_race a ON a.raceId = r.raceId
            ORDER BY r.year DESC, r.round DESC
            """
        )
    ).mappings().all()


@predictions_bp.route("/retrospective")
def retrospective():
    session = get_session()
    races = _covered_races(session)

    race_id = request.args.get("race_id", type=int)
    predictions = None
    mae = None
    error = None
    race_label = None

    if race_id:
        df = pd.read_sql(text(RACE_FEATURE_QUERY), engine, params={"race_id": race_id})
        df = df[df["dnf"] == 0]  # finish-position model was only ever trained on classified finishers

        if df.empty:
            error = (
                "No finish-position predictions available for this race. "
                "Either every entrant DNF'd (the model only predicts for "
                "classified finishers), or this race isn't covered by "
                "analytics_driver_race."
            )
        else:
            model, scaler, metadata = load_latest_artifacts()
            feature_cols = metadata["feature_columns"]

            prepped = prep_features_for_prediction(df)
            missing = [c for c in feature_cols if c not in prepped.columns]
            if missing:
                raise ValueError(f"Missing required feature columns: {missing}")

            X = prepped[feature_cols]
            if scaler is not None:
                X = scaler.transform(X)

            prepped["predicted_finish_position"] = model.predict(X).round(2)
            prepped["actual_finish_position"] = prepped["finishPosition"]

            mae = round(
                (prepped["predicted_finish_position"] - prepped["actual_finish_position"]).abs().mean(),
                2,
            )

            name_map = driver_name_map(session, prepped["driverId"].tolist())
            prepped["driver_name"] = prepped["driverId"].map(name_map)
            prepped = prepped.sort_values("predicted_finish_position")

            predictions = prepped[
                ["driver_name", "grid", "qualifyingPosition", "predicted_finish_position", "actual_finish_position"]
            ].to_dict("records")

            race_row = next((r for r in races if r["raceId"] == race_id), None)
            if race_row:
                race_label = f"{race_row['year']} Round {race_row['round']} — {race_row['name']}"

    return render_template(
        "predictions/retrospective.html",
        races=races,
        predictions=predictions,
        mae=mae,
        error=error,
        race_label=race_label,
        selected_race_id=race_id,
    )


@predictions_bp.route("/dnf-risk")
def dnf_risk():
    session = get_session()
    races = _covered_races(session)

    race_id = request.args.get("race_id", type=int)
    predictions = None
    error = None
    race_label = None
    threshold = DEFAULT_THRESHOLD

    if race_id:
        df = pd.read_sql(text(RACE_FEATURE_QUERY), engine, params={"race_id": race_id})

        if df.empty:
            error = "This race isn't covered by analytics_driver_race."
        else:
            model, scaler, metadata = load_latest_dnf_artifacts()
            feature_cols = metadata["feature_columns"]
            threshold = metadata.get("decision_threshold", DEFAULT_THRESHOLD)

            prepped = prep_features_for_prediction(df)
            missing = [c for c in feature_cols if c not in prepped.columns]
            if missing:
                raise ValueError(f"Missing required feature columns: {missing}")

            X = prepped[feature_cols]
            if scaler is not None:
                X = scaler.transform(X)

            probabilities = model.predict_proba(X)[:, 1]
            prepped["predicted_dnf_probability"] = probabilities.round(4)
            prepped["predicted_dnf_label"] = probabilities >= threshold
            prepped["actual_dnf"] = prepped["dnf"].astype(bool)

            name_map = driver_name_map(session, prepped["driverId"].tolist())
            prepped["driver_name"] = prepped["driverId"].map(name_map)
            prepped = prepped.sort_values("predicted_dnf_probability", ascending=False)

            predictions = prepped[
                ["driver_name", "grid", "predicted_dnf_probability", "predicted_dnf_label", "actual_dnf"]
            ].to_dict("records")

            race_row = next((r for r in races if r["raceId"] == race_id), None)
            if race_row:
                race_label = f"{race_row['year']} Round {race_row['round']} — {race_row['name']}"

    return render_template(
        "predictions/dnf_risk.html",
        races=races,
        predictions=predictions,
        error=error,
        race_label=race_label,
        selected_race_id=race_id,
        threshold=threshold,
    )


@predictions_bp.route("/hypothetical", methods=["GET", "POST"])
def hypothetical():
    session = get_session()

    drivers = session.execute(
        text("SELECT driverId, forename, surname FROM drivers ORDER BY surname, forename")
    ).mappings().all()
    constructors = session.execute(
        text("SELECT constructorId, name FROM constructors ORDER BY name")
    ).mappings().all()

    result = None
    error = None
    form = {"driver_id": None, "constructor_id": None, "qualifying_position": None}

    if request.method == "POST":
        driver_id = request.form.get("driver_id", type=int)
        constructor_id = request.form.get("constructor_id", type=int)
        qualifying_position = request.form.get("qualifying_position", type=int)
        form.update(
            driver_id=driver_id,
            constructor_id=constructor_id,
            qualifying_position=qualifying_position,
        )

        if not (driver_id and constructor_id and qualifying_position):
            error = "Pick a driver, a constructor, and a qualifying position."
        else:
            # Baseline driver-level features: this driver's most recent
            # known race row. Baseline constructor-level features: the most
            # recent row for the CHOSEN constructor (which may differ from
            # this driver's actual last team) — that's what makes this a
            # "driver at a different team" what-if rather than just a
            # driver's own history replayed.
            driver_row = session.execute(
                text(
                    """
                    SELECT driverAgeAtRaceDays, priorRaceCount, rollingAvgPoints_last5,
                           rollingAvgFinishPos_last5, priorWins, priorWinPct, priorWinStreak
                    FROM analytics_driver_race
                    WHERE driverId = :driver_id
                    ORDER BY year DESC, raceId DESC
                    LIMIT 1
                    """
                ),
                {"driver_id": driver_id},
            ).mappings().first()

            constructor_row = session.execute(
                text(
                    """
                    SELECT constructorRollingAvgPoints_last5, constructorWinPct_last10
                    FROM analytics_driver_race
                    WHERE constructorId = :constructor_id
                    ORDER BY year DESC, raceId DESC
                    LIMIT 1
                    """
                ),
                {"constructor_id": constructor_id},
            ).mappings().first()

            max_year = session.execute(text("SELECT MAX(year) AS y FROM races")).mappings().first()["y"]

            if driver_row is None:
                error = "No historical data for this driver yet — can't build a feature baseline."
            elif constructor_row is None:
                error = "No historical data for this constructor yet — can't build a feature baseline."
            else:
                row = {
                    "raceId": -1,
                    "driverId": driver_id,
                    "year": max_year,
                    "era": classify_era(max_year),
                    "grid": qualifying_position,
                    "qualifyingPosition": qualifying_position,
                    "driverAgeAtRaceDays": driver_row["driverAgeAtRaceDays"],
                    "priorRaceCount": driver_row["priorRaceCount"],
                    "rollingAvgPoints_last5": driver_row["rollingAvgPoints_last5"],
                    "rollingAvgFinishPos_last5": driver_row["rollingAvgFinishPos_last5"],
                    "constructorRollingAvgPoints_last5": constructor_row["constructorRollingAvgPoints_last5"],
                    "priorWins": driver_row["priorWins"],
                    "priorWinPct": driver_row["priorWinPct"],
                    "constructorWinPct_last10": constructor_row["constructorWinPct_last10"],
                    "priorWinStreak": driver_row["priorWinStreak"],
                    "dnf": 0,
                    "finishPosition": None,
                }
                one_row = pd.DataFrame([row])
                prepped = prep_features_for_prediction(one_row)

                finish_model, finish_scaler, finish_meta = load_latest_artifacts()
                finish_cols = finish_meta["feature_columns"]
                X_finish = prepped[finish_cols]
                if finish_scaler is not None:
                    X_finish = finish_scaler.transform(X_finish)
                predicted_finish = round(float(finish_model.predict(X_finish)[0]), 2)

                dnf_model, dnf_scaler, dnf_meta = load_latest_dnf_artifacts()
                dnf_cols = dnf_meta["feature_columns"]
                dnf_threshold = dnf_meta.get("decision_threshold", DEFAULT_THRESHOLD)
                X_dnf = prepped[dnf_cols]
                if dnf_scaler is not None:
                    X_dnf = dnf_scaler.transform(X_dnf)
                dnf_probability = round(float(dnf_model.predict_proba(X_dnf)[:, 1][0]), 4)

                driver_label = next(
                    (f"{d['forename']} {d['surname']}" for d in drivers if d["driverId"] == driver_id), "Driver"
                )
                constructor_label = next(
                    (c["name"] for c in constructors if c["constructorId"] == constructor_id), "Constructor"
                )

                result = {
                    "driver_label": driver_label,
                    "constructor_label": constructor_label,
                    "qualifying_position": qualifying_position,
                    "predicted_finish_position": predicted_finish,
                    "dnf_probability": dnf_probability,
                    "dnf_label": dnf_probability >= dnf_threshold,
                    "dnf_threshold": dnf_threshold,
                    "baseline_year": max_year,
                }

    return render_template(
        "predictions/hypothetical.html",
        drivers=drivers,
        constructors=constructors,
        result=result,
        error=error,
        form=form,
    )
