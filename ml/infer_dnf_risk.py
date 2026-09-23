"""
infer_dnf_risk.py
------------------
Load the latest saved Stage A DNF-risk classifier and generate predictions
from the production analytics table.

The feature set is identical to the finish-position model's, so this reuses
prep_features_for_prediction() from infer_finish_positions.py rather than
duplicating it — one preprocessing implementation for both models.
"""

import json

import pandas as pd
from sqlalchemy import text
import joblib

from infer_finish_positions import get_engine, prep_features_for_prediction, MODELS_DIR

DEFAULT_THRESHOLD = 0.15  # fallback if a meta.json predates the decision_threshold field


def load_latest_dnf_artifacts():
    meta_path = MODELS_DIR / "dnf_model_latest_meta.json"
    model_path = MODELS_DIR / "dnf_model_latest.pkl"
    scaler_path = MODELS_DIR / "dnf_model_latest_scaler.pkl"

    if not meta_path.exists():
        raise FileNotFoundError(f"Missing metadata: {meta_path}")
    if not model_path.exists():
        raise FileNotFoundError(f"Missing model: {model_path}")

    with open(meta_path, "r") as f:
        metadata = json.load(f)

    model = joblib.load(model_path)
    scaler = joblib.load(scaler_path) if metadata.get("requires_scaling") and scaler_path.exists() else None

    return model, scaler, metadata


def fetch_dnf_feature_rows(race_id: int | None = None, limit: int | None = None) -> pd.DataFrame:
    """
    Unlike infer_finish_positions.fetch_prediction_rows, this does NOT filter
    to dnf = 0 — the DNF classifier's whole job is predicting that outcome
    for every entrant, DNF or not, so excluding DNF rows would remove the
    positive class entirely.
    """
    base_query = """
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
            dnf
        FROM analytics_driver_race
    """

    params = {}
    if race_id is not None:
        base_query += " WHERE raceId = :race_id"
        params["race_id"] = race_id

    base_query += " ORDER BY year, raceId, driverId"

    if limit is not None:
        base_query += " LIMIT :limit"
        params["limit"] = limit

    with get_engine().connect() as conn:
        return pd.read_sql(text(base_query), conn, params=params)


def predict_dnf_risk(race_id: int | None = None, limit: int | None = None):
    model, scaler, metadata = load_latest_dnf_artifacts()
    feature_cols = metadata["feature_columns"]
    threshold = metadata.get("decision_threshold", DEFAULT_THRESHOLD)

    df = fetch_dnf_feature_rows(race_id=race_id, limit=limit)
    if df.empty:
        return df, metadata

    df = prep_features_for_prediction(df)

    missing = [col for col in feature_cols if col not in df.columns]
    if missing:
        raise ValueError(f"Missing required feature columns for prediction: {missing}")

    X = df[feature_cols]
    if scaler is not None:
        X = scaler.transform(X)

    probabilities = model.predict_proba(X)[:, 1]
    results = df[["raceId", "driverId", "year", "grid", "dnf"]].copy()
    results["predicted_dnf_probability"] = probabilities.round(4)
    results["predicted_dnf_label"] = (probabilities >= threshold).astype(int)
    results["actual_dnf"] = results["dnf"]
    results = results.drop(columns=["dnf"])

    return results, metadata


if __name__ == "__main__":
    results, metadata = predict_dnf_risk(limit=None)

    print(f"\nModel type: {metadata['model_type']}")
    print(f"Decision threshold: {metadata.get('decision_threshold', DEFAULT_THRESHOLD)}")
    print(f"Predictions rows: {len(results)}")
    print(results.head(10).to_string(index=False))

    output_path = MODELS_DIR / "dnf_predictions_latest.csv"
    results.to_csv(output_path, index=False)
    print(f"\nSaved predictions to: {output_path}")
