"""
precompute_predictions.py
--------------------------
Runs both trained models (Stage A DNF-risk, Stage B finish-position) once,
offline, against every row the dashboard could ever need, and writes the
results to CSV files in ml/models/. export_snapshot.py then loads these
CSVs straight into the SQLite snapshot as tables — the public deployment
never loads a model or imports scikit-learn.

This is NOT automatic. Run it manually, before export_snapshot.py, whenever
the models are retrained or analytics_driver_race changes:

    python ml/precompute_predictions.py
    python dashboard/export_snapshot.py

Three things get precomputed:

1. Historical predictions — both models run against every row in
   analytics_driver_race, keyed by (raceId, driverId). This is what backs
   the /predictions/retrospective and /predictions/dnf-risk pages, which
   only ever look up one race at a time.

2. Finish-position "contributions" for the hypothetical page. The finish
   model is a Linear Regression behind a StandardScaler, and that
   composition is affine (an affine function of an affine function is
   still affine) — which means it's exactly separable into independent
   per-driver, per-constructor, and per-grid-position terms, as long as
   every other block is held at a fixed reference point while one block
   varies:

       f(driver, constructor, grid)
         = f(ref)
         + [f(driver, ref_constructor, ref_grid) - f(ref)]   driver term
         + [f(ref_driver, constructor, ref_grid) - f(ref)]   constructor term
         + [f(ref_driver, ref_constructor, grid) - f(ref)]   grid term

   This holds exactly (not approximately) because the driver, constructor,
   and grid feature blocks are disjoint columns feeding one affine
   function — the cross terms cancel algebraically. `era` is not a fourth
   varying block here: it's derived from the dataset's MAX(year), which is
   fixed regardless of which driver/constructor/grid is chosen, so it's
   folded permanently into every term as a constant. base +
   driver_contrib[d] + constructor_contrib[c] + grid_contrib[g] reproduces
   the real model's output to float precision, for ANY combination,
   including ones that never happened historically — full historical
   coverage, not just a recent window.

3. A bounded DNF-risk grid for the hypothetical page. Random Forest
   probabilities do NOT decompose this way — a tree combines driver and
   constructor features jointly through its splits, so there's no
   equivalent shortcut. Instead we brute-force every combination of
   (driver, constructor, grid position) for drivers/constructors active
   since DNF_GRID_CUTOFF_YEAR. That's a real, disclosed coverage
   restriction: the hypothetical page's finish-position half covers all of
   F1 history, its DNF-risk half only covers roughly the current era.
"""

from datetime import datetime, timezone

import pandas as pd
from sqlalchemy import text

from infer_finish_positions import (
    get_engine,
    prep_features_for_prediction,
    load_latest_artifacts,
    fetch_prediction_rows,
    MODELS_DIR,
)
from infer_dnf_risk import load_latest_dnf_artifacts, fetch_dnf_feature_rows, DEFAULT_THRESHOLD

OUTPUT_DIR = MODELS_DIR
DNF_GRID_CUTOFF_YEAR = 2018
GRID_POSITIONS = list(range(0, 35))  # matches the observed 0-34 grid range in results.csv


# Duplicates the era CASE expression already present in fetch_prediction_rows
# / fetch_dnf_feature_rows (SQL) and predictions.py's classify_era() (Python,
# dashboard side). That's an existing pattern in this codebase, not a new one
# introduced here — flagging it rather than hiding it: if the era bucket
# boundaries ever change, they need to change in three places.
def classify_era(year: int) -> str:
    if year < 1981:
        return "pre_1981"
    if year <= 2005:
        return "1981_2005"
    if year <= 2013:
        return "2006_2013_v8"
    if year <= 2021:
        return "2014_2021_hybrid"
    return "2022_plus_ground_effect"


def _predict(df: pd.DataFrame, model, scaler, feature_cols, proba: bool = False):
    prepped = prep_features_for_prediction(df)
    missing = [c for c in feature_cols if c not in prepped.columns]
    if missing:
        raise ValueError(f"Missing required feature columns: {missing}")
    X = prepped[feature_cols]
    if scaler is not None:
        X = scaler.transform(X)
    if proba:
        return model.predict_proba(X)[:, 1]
    return model.predict(X)


def export_historical_predictions():
    print("Computing historical finish-position predictions...")
    finish_model, finish_scaler, finish_meta = load_latest_artifacts()
    finish_df = fetch_prediction_rows(limit=None)  # already WHERE dnf = 0
    preds = _predict(finish_df, finish_model, finish_scaler, finish_meta["feature_columns"])
    out = finish_df[["raceId", "driverId", "grid", "qualifyingPosition", "finishPosition"]].copy()
    out["predicted_finish_position"] = preds.round(2)
    out = out.rename(columns={"finishPosition": "actual_finish_position"})
    out.to_csv(OUTPUT_DIR / "finish_predictions_historical.csv", index=False)
    print(f"  {len(out)} rows -> finish_predictions_historical.csv")

    print("Computing historical DNF-risk predictions...")
    dnf_model, dnf_scaler, dnf_meta = load_latest_dnf_artifacts()
    dnf_threshold = dnf_meta.get("decision_threshold", DEFAULT_THRESHOLD)
    dnf_df = fetch_dnf_feature_rows(race_id=None, limit=None)  # every entrant, dnf and non-dnf
    probs = _predict(dnf_df, dnf_model, dnf_scaler, dnf_meta["feature_columns"], proba=True)
    out2 = dnf_df[["raceId", "driverId", "grid", "dnf"]].copy()
    out2["predicted_dnf_probability"] = probs.round(4)
    out2["predicted_dnf_label"] = (probs >= dnf_threshold).astype(int)
    out2 = out2.rename(columns={"dnf": "actual_dnf"})
    out2.to_csv(OUTPUT_DIR / "dnf_predictions_historical.csv", index=False)
    print(f"  {len(out2)} rows -> dnf_predictions_historical.csv")

    return dnf_threshold


DRIVER_BLOCK_COLS = [
    "driverAgeAtRaceDays", "priorRaceCount", "rollingAvgPoints_last5",
    "rollingAvgFinishPos_last5", "priorWins", "priorWinPct", "priorWinStreak",
]
CONSTRUCTOR_BLOCK_COLS = ["constructorRollingAvgPoints_last5", "constructorWinPct_last10"]

# Arbitrary but fixed. Reuses the same -1 cold-start sentinel convention
# prep_features_for_prediction already applies to real missing data, so the
# reference point reads as "an unknown/rookie driver, unknown/new
# constructor, pole position" rather than a meaningless placeholder. The
# actual values don't affect correctness of the decomposition (see module
# docstring) — only that the SAME reference values are reused consistently
# everywhere below.
REFERENCE = {
    "driverAgeAtRaceDays": 0,
    "priorRaceCount": 0,
    "rollingAvgPoints_last5": -1,
    "rollingAvgFinishPos_last5": -1,
    "priorWins": -1,
    "priorWinPct": -1,
    "priorWinStreak": 0,
    "constructorRollingAvgPoints_last5": -1,
    "constructorWinPct_last10": -1,
    "grid": 0,
    "qualifyingPosition": 0,
}


def export_hypothetical_finish_contributions(engine, era: str):
    print("Computing hypothetical finish-position contributions...")
    finish_model, finish_scaler, finish_meta = load_latest_artifacts()
    feature_cols = finish_meta["feature_columns"]

    def score(rows):
        df = pd.DataFrame(rows)
        df["era"] = era
        return _predict(df, finish_model, finish_scaler, feature_cols)

    base = float(score([dict(REFERENCE)])[0])

    with engine.connect() as conn:
        driver_rows = conn.execute(
            text(
                f"""
                SELECT driverId, {', '.join(DRIVER_BLOCK_COLS)}
                FROM (
                    SELECT *, ROW_NUMBER() OVER (
                        PARTITION BY driverId ORDER BY year DESC, raceId DESC
                    ) AS rn
                    FROM analytics_driver_race
                ) t
                WHERE rn = 1
                """
            )
        ).mappings().all()

        constructor_rows = conn.execute(
            text(
                f"""
                SELECT constructorId, {', '.join(CONSTRUCTOR_BLOCK_COLS)}
                FROM (
                    SELECT *, ROW_NUMBER() OVER (
                        PARTITION BY constructorId ORDER BY year DESC, raceId DESC
                    ) AS rn
                    FROM analytics_driver_race
                ) t
                WHERE rn = 1
                """
            )
        ).mappings().all()

    # Driver contributions: real driver block + reference everything else
    driver_input_rows = []
    for r in driver_rows:
        row = dict(REFERENCE)
        row.update({c: r[c] for c in DRIVER_BLOCK_COLS})
        driver_input_rows.append(row)
    driver_preds = score(driver_input_rows)
    driver_contrib = pd.DataFrame({
        "driverId": [r["driverId"] for r in driver_rows],
        "contribution": driver_preds - base,
    })
    driver_contrib.to_csv(OUTPUT_DIR / "finish_contrib_driver.csv", index=False)
    print(f"  {len(driver_contrib)} rows -> finish_contrib_driver.csv")

    # Constructor contributions: real constructor block + reference everything else
    constructor_input_rows = []
    for r in constructor_rows:
        row = dict(REFERENCE)
        row.update({c: r[c] for c in CONSTRUCTOR_BLOCK_COLS})
        constructor_input_rows.append(row)
    constructor_preds = score(constructor_input_rows)
    constructor_contrib = pd.DataFrame({
        "constructorId": [r["constructorId"] for r in constructor_rows],
        "contribution": constructor_preds - base,
    })
    constructor_contrib.to_csv(OUTPUT_DIR / "finish_contrib_constructor.csv", index=False)
    print(f"  {len(constructor_contrib)} rows -> finish_contrib_constructor.csv")

    # Grid contributions: reference driver + reference constructor + real grid
    grid_input_rows = []
    for g in GRID_POSITIONS:
        row = dict(REFERENCE)
        row["grid"] = g
        row["qualifyingPosition"] = g
        grid_input_rows.append(row)
    grid_preds = score(grid_input_rows)
    grid_contrib = pd.DataFrame({
        "qualifying_position": GRID_POSITIONS,
        "contribution": grid_preds - base,
    })
    grid_contrib.to_csv(OUTPUT_DIR / "finish_contrib_grid.csv", index=False)
    print(f"  {len(grid_contrib)} rows -> finish_contrib_grid.csv")

    return base


def export_hypothetical_dnf_grid(engine, era: str):
    print(f"Computing hypothetical DNF-risk grid (since {DNF_GRID_CUTOFF_YEAR})...")
    dnf_model, dnf_scaler, dnf_meta = load_latest_dnf_artifacts()
    feature_cols = dnf_meta["feature_columns"]
    threshold = dnf_meta.get("decision_threshold", DEFAULT_THRESHOLD)

    with engine.connect() as conn:
        driver_rows = conn.execute(
            text(
                f"""
                SELECT driverId, {', '.join(DRIVER_BLOCK_COLS)}
                FROM (
                    SELECT *, ROW_NUMBER() OVER (
                        PARTITION BY driverId ORDER BY year DESC, raceId DESC
                    ) AS rn
                    FROM analytics_driver_race
                    WHERE year >= :cutoff
                ) t
                WHERE rn = 1
                """
            ),
            {"cutoff": DNF_GRID_CUTOFF_YEAR},
        ).mappings().all()

        constructor_rows = conn.execute(
            text(
                f"""
                SELECT constructorId, {', '.join(CONSTRUCTOR_BLOCK_COLS)}
                FROM (
                    SELECT *, ROW_NUMBER() OVER (
                        PARTITION BY constructorId ORDER BY year DESC, raceId DESC
                    ) AS rn
                    FROM analytics_driver_race
                    WHERE year >= :cutoff
                ) t
                WHERE rn = 1
                """
            ),
            {"cutoff": DNF_GRID_CUTOFF_YEAR},
        ).mappings().all()

    driver_df = pd.DataFrame(driver_rows)
    constructor_df = pd.DataFrame(constructor_rows)
    grid_df = pd.DataFrame({"qualifying_position": GRID_POSITIONS})

    driver_df["_key"] = 1
    constructor_df["_key"] = 1
    grid_df["_key"] = 1
    cross = driver_df.merge(constructor_df, on="_key").merge(grid_df, on="_key").drop(columns="_key")
    cross["grid"] = cross["qualifying_position"]
    cross["qualifyingPosition"] = cross["qualifying_position"]
    cross["era"] = era

    probs = _predict(cross, dnf_model, dnf_scaler, feature_cols, proba=True)
    cross["predicted_dnf_probability"] = probs.round(4)
    cross["predicted_dnf_label"] = (probs >= threshold).astype(int)

    out = cross[[
        "driverId", "constructorId", "qualifying_position",
        "predicted_dnf_probability", "predicted_dnf_label",
    ]]
    out.to_csv(OUTPUT_DIR / "dnf_hypothetical_grid.csv", index=False)
    print(
        f"  {len(out)} rows -> dnf_hypothetical_grid.csv "
        f"({len(driver_df)} drivers x {len(constructor_df)} constructors x {len(GRID_POSITIONS)} grid positions)"
    )


def main():
    engine = get_engine()

    with engine.connect() as conn:
        max_year = conn.execute(text("SELECT MAX(year) AS y FROM races")).mappings().first()["y"]
    era = classify_era(max_year)

    _, _, finish_meta = load_latest_artifacts()
    _, _, dnf_meta = load_latest_dnf_artifacts()

    dnf_threshold = export_historical_predictions()
    finish_base = export_hypothetical_finish_contributions(engine, era)
    export_hypothetical_dnf_grid(engine, era)

    metadata_rows = [
        {"meta_key": "finish_base", "meta_value": str(finish_base)},
        {"meta_key": "finish_era_used", "meta_value": era},
        {"meta_key": "finish_max_year_used", "meta_value": str(max_year)},
        {"meta_key": "finish_grid_min", "meta_value": str(min(GRID_POSITIONS))},
        {"meta_key": "finish_grid_max", "meta_value": str(max(GRID_POSITIONS))},
        {"meta_key": "finish_model_type", "meta_value": finish_meta.get("model_type", "")},
        {"meta_key": "dnf_model_type", "meta_value": dnf_meta.get("model_type", "")},
        {"meta_key": "dnf_threshold", "meta_value": str(dnf_threshold)},
        {"meta_key": "dnf_grid_cutoff_year", "meta_value": str(DNF_GRID_CUTOFF_YEAR)},
        {"meta_key": "computed_at", "meta_value": datetime.now(timezone.utc).isoformat()},
    ]
    pd.DataFrame(metadata_rows).to_csv(OUTPUT_DIR / "prediction_metadata.csv", index=False)
    print("Wrote prediction_metadata.csv")

    print("\nDone. Next: run dashboard/export_snapshot.py to bundle these into f1_snapshot.db.")


if __name__ == "__main__":
    main()