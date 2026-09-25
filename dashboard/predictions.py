from flask import Blueprint, render_template, request
from sqlalchemy import text

try:
    from .db import get_session
except ImportError:  # pragma: no cover - supports local script execution
    from db import get_session

predictions_bp = Blueprint("predictions", __name__, url_prefix="/predictions")

# Mirrors ml/infer_dnf_risk.py's DEFAULT_THRESHOLD — used only if
# prediction_metadata somehow has no dnf_threshold row. Another small,
# intentional duplication (see ml/precompute_predictions.py's era-CASE
# comment for the same pattern elsewhere in this codebase).
DEFAULT_THRESHOLD_FALLBACK = 0.15


def _meta_int(meta, key, default):
    value = meta.get(key)
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _prediction_metadata(session):
    rows = session.execute(text("SELECT meta_key, meta_value FROM prediction_metadata")).mappings().all()
    return {r["meta_key"]: r["meta_value"] for r in rows}


@predictions_bp.route("/")
def index():
    return render_template("predictions/index.html")


def _covered_races(session):
    # Joins against dnf_predictions_historical rather than
    # finish_predictions_historical: DNF predictions exist for every
    # entrant (dnf=0 and dnf=1), so a race is "covered" here even in the
    # rare case where every entrant DNF'd and finish_predictions_historical
    # has no rows for it at all.
    return session.execute(
        text(
            """
            SELECT DISTINCT r.raceId, r.year, r.round, r.name
            FROM races r
            JOIN dnf_predictions_historical p ON p.raceId = r.raceId
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
        rows = session.execute(
            text(
                """
                SELECT p.driverId, d.forename, d.surname, p.grid, p.qualifyingPosition,
                       p.predicted_finish_position, p.actual_finish_position
                FROM finish_predictions_historical p
                JOIN drivers d ON d.driverId = p.driverId
                WHERE p.raceId = :race_id
                ORDER BY p.predicted_finish_position
                """
            ),
            {"race_id": race_id},
        ).mappings().all()

        if not rows:
            error = (
                "No finish-position predictions available for this race. "
                "Either every entrant DNF'd (the model only predicts for "
                "classified finishers), or this race isn't covered by the "
                "precomputed predictions."
            )
        else:
            predictions = [
                {
                    "driver_name": f"{r['forename']} {r['surname']}",
                    "grid": r["grid"],
                    "qualifyingPosition": r["qualifyingPosition"],
                    "predicted_finish_position": r["predicted_finish_position"],
                    "actual_finish_position": r["actual_finish_position"],
                }
                for r in rows
            ]
            diffs = [abs(r["predicted_finish_position"] - r["actual_finish_position"]) for r in rows]
            mae = round(sum(diffs) / len(diffs), 2)

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
    meta = _prediction_metadata(session)
    threshold = float(meta.get("dnf_threshold", DEFAULT_THRESHOLD_FALLBACK))

    race_id = request.args.get("race_id", type=int)
    predictions = None
    error = None
    race_label = None

    if race_id:
        rows = session.execute(
            text(
                """
                SELECT p.driverId, d.forename, d.surname, p.grid,
                       p.predicted_dnf_probability, p.predicted_dnf_label, p.actual_dnf
                FROM dnf_predictions_historical p
                JOIN drivers d ON d.driverId = p.driverId
                WHERE p.raceId = :race_id
                ORDER BY p.predicted_dnf_probability DESC
                """
            ),
            {"race_id": race_id},
        ).mappings().all()

        if not rows:
            error = "This race isn't covered by the precomputed predictions."
        else:
            predictions = [
                {
                    "driver_name": f"{r['forename']} {r['surname']}",
                    "grid": r["grid"],
                    "predicted_dnf_probability": r["predicted_dnf_probability"],
                    "predicted_dnf_label": bool(r["predicted_dnf_label"]),
                    "actual_dnf": bool(r["actual_dnf"]),
                }
                for r in rows
            ]
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

    meta = _prediction_metadata(session)
    dnf_cutoff_year = _meta_int(meta, "dnf_grid_cutoff_year", 0)
    grid_min = _meta_int(meta, "finish_grid_min", 0)
    grid_max = _meta_int(meta, "finish_grid_max", 34)

    dnf_eligible_driver_ids = {
        r["driverId"] for r in session.execute(text("SELECT DISTINCT driverId FROM dnf_hypothetical_grid")).mappings().all()
    }
    dnf_eligible_constructor_ids = {
        r["constructorId"] for r in session.execute(text("SELECT DISTINCT constructorId FROM dnf_hypothetical_grid")).mappings().all()
    }

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

        if not (driver_id and constructor_id and qualifying_position is not None):
            error = "Pick a driver, a constructor, and a qualifying position."
        else:
            finish_base_raw = meta.get("finish_base")
            if finish_base_raw is None:
                error = (
                    "Prediction data isn’t available for the hypothetical model on this deployment. "
                    "Rebuild the precomputed prediction snapshot and redeploy."
                )
            else:
                try:
                    base = float(finish_base_raw)
                except (TypeError, ValueError):
                    error = (
                        "The prediction baseline is invalid on this deployment. "
                        "Rebuild the precomputed prediction snapshot and redeploy."
                    )
                    base = None

                if base is not None:
                    driver_contrib = session.execute(
                        text("SELECT contribution FROM finish_contrib_driver WHERE driverId = :d"),
                        {"d": driver_id},
                    ).scalar()
                    constructor_contrib = session.execute(
                        text("SELECT contribution FROM finish_contrib_constructor WHERE constructorId = :c"),
                        {"c": constructor_id},
                    ).scalar()
                    grid_contrib = session.execute(
                        text("SELECT contribution FROM finish_contrib_grid WHERE qualifying_position = :g"),
                        {"g": qualifying_position},
                    ).scalar()

                    if driver_contrib is None:
                        error = "No historical data for this driver yet — can't build a feature baseline."
                    elif constructor_contrib is None:
                        error = "No historical data for this constructor yet — can't build a feature baseline."
                    elif grid_contrib is None:
                        error = f"Qualifying position must be between {grid_min} and {grid_max}."
                    else:
                        predicted_finish = round(base + driver_contrib + constructor_contrib + grid_contrib, 2)

                        dnf_row = None
                        if driver_id in dnf_eligible_driver_ids and constructor_id in dnf_eligible_constructor_ids:
                            dnf_row = session.execute(
                                text(
                                    """
                                    SELECT predicted_dnf_probability, predicted_dnf_label
                                    FROM dnf_hypothetical_grid
                                    WHERE driverId = :d AND constructorId = :c AND qualifying_position = :g
                                    """
                                ),
                                {"d": driver_id, "c": constructor_id, "g": qualifying_position},
                            ).mappings().first()

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
                            "dnf_probability": dnf_row["predicted_dnf_probability"] if dnf_row else None,
                            "dnf_label": bool(dnf_row["predicted_dnf_label"]) if dnf_row else None,
                            "dnf_unavailable_reason": None if dnf_row else (
                                f"DNF-risk isn't precomputed for this combination — only available for drivers "
                                f"and constructors active since {dnf_cutoff_year}."
                            ),
                            "dnf_threshold": float(meta.get("dnf_threshold", DEFAULT_THRESHOLD_FALLBACK)),
                            "baseline_year": meta.get("finish_max_year_used"),
                        }

    return render_template(
        "predictions/hypothetical.html",
        drivers=drivers,
        constructors=constructors,
        result=result,
        error=error,
        form=form,
        dnf_cutoff_year=dnf_cutoff_year,
    )
