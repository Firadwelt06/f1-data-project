"""
infer_finish_positions.py
------------------------
Load the latest saved Stage B finish-position model and generate predictions
from the production analytics table using the exact same preprocessing logic
as the training script.

This is the final stage wrapper that makes the model usable outside the
training notebook/script environment.
"""

import os
import json
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import joblib


load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
MODELS_DIR = BASE_DIR / "models"


def get_engine():
    return create_engine(
        f"mysql+pymysql://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}"
        f"@{os.getenv('DB_HOST')}/{os.getenv('DB_NAME')}"
    )


def build_era_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    era_categories = [
        'pre_1981',
        '1981_2005',
        '2006_2013_v8',
        '2014_2021_hybrid',
        '2022_plus_ground_effect',
    ]
    df['era'] = pd.Categorical(df['era'], categories=era_categories, ordered=True)
    df = pd.get_dummies(df, columns=['era'], drop_first=True)
    return df


def prep_features_for_prediction(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    driver_coldstart_cols = [
        'rollingAvgPoints_last5',
        'rollingAvgFinishPos_last5',
        'priorWins',
        'priorWinPct',
    ]
    constructor_coldstart_cols = [
        'constructorRollingAvgPoints_last5',
        'constructorWinPct_last10',
    ]

    df['is_rookie_driver'] = df[driver_coldstart_cols].isnull().any(axis=1).astype(int)
    df['is_new_constructor'] = df[constructor_coldstart_cols].isnull().any(axis=1).astype(int)

    for col in driver_coldstart_cols + constructor_coldstart_cols:
        df[col] = df[col].fillna(-1)

    df = build_era_features(df)
    return df


def load_latest_artifacts():
    meta_path = MODELS_DIR / "finish_model_latest_meta.json"
    model_path = MODELS_DIR / "finish_model_latest.pkl"
    scaler_path = MODELS_DIR / "finish_model_latest_scaler.pkl"

    if not meta_path.exists():
        raise FileNotFoundError(f"Missing metadata: {meta_path}")
    if not model_path.exists():
        raise FileNotFoundError(f"Missing model: {model_path}")

    with open(meta_path, 'r') as f:
        metadata = json.load(f)

    model = joblib.load(model_path)
    scaler = joblib.load(scaler_path) if metadata.get('requires_scaling') and scaler_path.exists() else None

    return model, scaler, metadata


def fetch_prediction_rows(limit: int | None = None):
    query = text("""
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
        WHERE dnf = 0
        ORDER BY year, raceId, driverId
    """)

    if limit is not None:
        query = text(f"""
            SELECT * FROM (
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
                WHERE dnf = 0
                ORDER BY year, raceId, driverId
                LIMIT :limit
            ) x
        """)

    with get_engine().connect() as conn:
        if limit is None:
            return pd.read_sql(query, conn)
        return pd.read_sql(query, conn, params={"limit": limit})


def predict_finish_positions(limit: int | None = None):
    model, scaler, metadata = load_latest_artifacts()
    feature_cols = metadata['feature_columns']

    df = fetch_prediction_rows(limit=limit)
    df = prep_features_for_prediction(df)

    missing = [col for col in feature_cols if col not in df.columns]
    if missing:
        raise ValueError(f"Missing required feature columns for prediction: {missing}")

    X = df[feature_cols]
    if scaler is not None:
        X = scaler.transform(X)

    preds = model.predict(X)
    results = df[['raceId', 'driverId', 'year', 'grid', 'finishPosition']].copy()
    results['predicted_finish_position'] = preds.round(2)
    results['actual_finish_position'] = results['finishPosition']
    results = results.drop(columns=['finishPosition'])

    return results, metadata


if __name__ == '__main__':
    results, metadata = predict_finish_positions(limit=None)

    print(f"\nModel type: {metadata['model_type']}")
    print(f"Requires scaling: {metadata.get('requires_scaling', False)}")
    print(f"Predictions rows: {len(results)}")
    print(results.head(10).to_string(index=False))

    output_path = MODELS_DIR / "finish_predictions_latest.csv"
    results.to_csv(output_path, index=False)
    print(f"\nSaved predictions to: {output_path}")
