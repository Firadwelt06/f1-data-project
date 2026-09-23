"""
train_finish_model.py
-----------------------
Stage 5, Sub-step 6: Model Selection + Versioning (Stage B - finishing position
regression)

FINAL MODEL CHOICE: TBD after this run - compare Linear Regression (baseline)
vs. Random Forest Regressor on MAE, with RMSE/R2 as secondary metrics.

Design context (documented for portfolio/interview defense):

- Stage B is deliberately decoupled from Stage A (see train_dnf_model.py).
  Stage A's DNF-risk probability is reported alongside this model's
  prediction, not used to gate which drivers reach Stage B - Stage A's
  ROC-AUC (0.586) was too weak to support a threshold that was both
  meaningfully protective and meaningfully useful as a hard filter.
- Stage B trains and predicts ONLY on non-DNF rows (dnf == 0). Finishing
  position is not a meaningful target for a driver who didn't finish -
  their positionOrder reflects retirement order, not competitive pace.
- Kept as plain regression, not ordinal regression or learning-to-rank.
  Finishing position IS technically ordinal (position 2 isn't "twice as
  bad" as position 1 the way a linear scale implies), but plain regression
  was chosen deliberately to build core scikit-learn fluency first. This
  is a documented simplification, not an oversight - ordinal/ranking
  approaches are a natural next iteration once the basics are solid.
- Feature set starts as a verbatim reuse of Stage A's feature_cols. This is
  a deliberate baseline-first choice: Stage A's features were selected for
  DNF-risk signal (age, experience, rolling reliability proxies), not
  finish-position signal, so grid/qualifying position may end up mattering
  far more here than it did for Stage A. Rather than guess at a "better"
  feature set upfront, we reuse Stage A's list, measure the result (feature
  importances will show if grid dominates as expected), and only expand
  the feature set in a later iteration if MAE suggests it's needed.

NOTE: This duplicates data-prep logic from data_prep.py / train_dnf_model.py
rather than importing it, for the same reason documented there: data_prep.py
is still a flat script, not yet refactored into a function. Flagged for
refactoring once Stage A + Stage B are both confirmed working end-to-end.
"""

import pandas as pd
import numpy as np
from sqlalchemy import create_engine, text
import os
import json
import shutil
from datetime import datetime
from dotenv import load_dotenv
from sklearn.linear_model import LinearRegression
from sklearn.ensemble import RandomForestRegressor
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
import joblib

# ---------------------------------------------------------------------------
# 1. LOAD + PREPARE DATA (same logic as train_dnf_model.py)
# ---------------------------------------------------------------------------

load_dotenv()

engine = create_engine(
    f"mysql+pymysql://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}"
    f"@{os.getenv('DB_HOST')}/{os.getenv('DB_NAME')}"
)

query = text("""
    SELECT
        raceId, driverId, year,
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
    ORDER BY year, raceId, driverId
""")

with engine.connect() as conn:
    df = pd.read_sql(query, conn)

# Cold-start handling: flag + sentinel-fill (identical to Stage A - see
# data_prep.py for full rationale). Computed on the full dataset BEFORE the
# dnf==0 filter below, since rolling averages/prior counts are historical
# features that exist regardless of how this particular race ended.
driver_coldstart_cols = [
    'rollingAvgPoints_last5', 'rollingAvgFinishPos_last5', 'priorWins', 'priorWinPct'
]
constructor_coldstart_cols = [
    'constructorRollingAvgPoints_last5', 'constructorWinPct_last10'
]

df['is_rookie_driver'] = df[driver_coldstart_cols].isnull().any(axis=1).astype(int)
df['is_new_constructor'] = df[constructor_coldstart_cols].isnull().any(axis=1).astype(int)

for col in driver_coldstart_cols + constructor_coldstart_cols:
    df[col] = df[col].fillna(-1)

# Keep pre_1981 as the reference category when dropping the first dummy
era_categories = [
    'pre_1981',
    '1981_2005',
    '2006_2013_v8',
    '2014_2021_hybrid',
    '2022_plus_ground_effect'
]
df['era'] = pd.Categorical(df['era'], categories=era_categories, ordered=True)
df = pd.get_dummies(df, columns=['era'], drop_first=True)

# ---------------------------------------------------------------------------
# 2. FILTER TO NON-DNF ROWS
# ---------------------------------------------------------------------------
# finishPosition is only meaningful for drivers who actually finished.
# Filtering here (after cold-start/era prep, before the train/test split)
# means both train and test automatically only ever see dnf==0 rows.

df = df[df['dnf'] == 0].copy()

# ---------------------------------------------------------------------------
# 3. TEMPORAL TRAIN/TEST SPLIT (same split point as Stage A)
# ---------------------------------------------------------------------------

train_df = df[df['year'] < 2025].copy()
test_df = df[df['year'] >= 2025].copy()

# Reused verbatim from Stage A - see module docstring for why this is a
# deliberate starting point, not a final feature set.
feature_cols = [
    'grid', 'qualifyingPosition', 'driverAgeAtRaceDays', 'priorRaceCount',
    'rollingAvgPoints_last5', 'rollingAvgFinishPos_last5',
    'constructorRollingAvgPoints_last5', 'priorWins', 'priorWinPct',
    'constructorWinPct_last10', 'priorWinStreak',
    'is_rookie_driver', 'is_new_constructor',
    'era_1981_2005', 'era_2006_2013_v8', 'era_2014_2021_hybrid',
    'era_2022_plus_ground_effect'
]

X_train = train_df[feature_cols]
y_train = train_df['finishPosition']
X_test = test_df[feature_cols]
y_test = test_df['finishPosition']

# ---------------------------------------------------------------------------
# 4. FEATURE SCALING (StandardScaler) - fit on train only, used for the
#    Linear Regression baseline only (same split as Stage A: tree-based
#    models split on raw thresholds per feature, so scaling changes nothing
#    about what Random Forest Regressor learns - it would only add a step
#    with no effect on results). Fitting the scaler exclusively on
#    X_train and reusing that fit to transform X_test avoids leaking
#    test-set distribution information into training, same as Stage A.
# ---------------------------------------------------------------------------

scaler = StandardScaler()
X_train_scaled = scaler.fit_transform(X_train)
X_test_scaled = scaler.transform(X_test)

# ---------------------------------------------------------------------------
# 5. BASELINE MODEL: LINEAR REGRESSION
# ---------------------------------------------------------------------------

lin_reg = LinearRegression()
lin_reg.fit(X_train_scaled, y_train)
y_pred_lr = lin_reg.predict(X_test_scaled)

# ---------------------------------------------------------------------------
# 6. COMPARISON MODEL: RANDOM FOREST REGRESSOR
# ---------------------------------------------------------------------------
# Sane defaults, minimal tuning for this first pass - consistent with the
# project's "get it working end-to-end before optimizing" philosophy.
# n_estimators=100 is sklearn's own default; random_state fixed for
# reproducibility; n_jobs=-1 to use all cores during training.

rf = RandomForestRegressor(
    n_estimators=100, random_state=42, n_jobs=-1
)
rf.fit(X_train, y_train)
y_pred_rf = rf.predict(X_test)

# ---------------------------------------------------------------------------
# 7. EVALUATION
# ---------------------------------------------------------------------------
# MAE is the headline metric - directly interpretable as "predicted
# position was off by X positions on average," which is the framing this
# whole stage is built around. RMSE is reported alongside it because it
# penalizes large misses more heavily than small ones (useful if e.g. the
# model is occasionally wildly wrong on midfield chaos races), and R2
# gives a variance-explained sanity check.

def report(name, y_true, y_pred):
    mae = mean_absolute_error(y_true, y_pred)
    rmse = np.sqrt(mean_squared_error(y_true, y_pred))
    r2 = r2_score(y_true, y_pred)
    metrics = {"mae": mae, "rmse": rmse, "r2": r2}
    print(f"\n--- {name} ---")
    print(f"MAE  : {mae:.3f}")
    print(f"RMSE : {rmse:.3f}")
    print(f"R2   : {r2:.3f}")
    return metrics

lr_metrics = report("Linear Regression (baseline)", y_test, y_pred_lr)
rf_metrics = report("Random Forest Regressor", y_test, y_pred_rf)

importances = pd.Series(rf.feature_importances_, index=feature_cols).sort_values(ascending=False)
print("\n--- Random Forest Feature Importances ---")
print(importances)

# ---------------------------------------------------------------------------
# 8. MODEL VERSIONING (same pattern as Stage A)
# ---------------------------------------------------------------------------
# Whichever model has the lower test MAE is saved as the "final" Stage B
# model. Both models' metrics are recorded in metadata regardless, so the
# comparison is preserved even though only one model file is versioned.

final_model, final_model_type, final_metrics = (
    (rf, "RandomForestRegressor", rf_metrics)
    if rf_metrics["mae"] <= lr_metrics["mae"]
    else (lin_reg, "LinearRegression", lr_metrics)
)
print(f"\nFinal model selected: {final_model_type} (lower test MAE)")

MODELS_DIR = "ml/models"
os.makedirs(MODELS_DIR, exist_ok=True)

timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
versioned_model_path = os.path.join(MODELS_DIR, f"finish_model_{timestamp}.pkl")
versioned_meta_path = os.path.join(MODELS_DIR, f"finish_model_{timestamp}_meta.json")
latest_model_path = os.path.join(MODELS_DIR, "finish_model_latest.pkl")
latest_meta_path = os.path.join(MODELS_DIR, "finish_model_latest_meta.json")

joblib.dump(final_model, versioned_model_path)

# If Linear Regression wins, the saved model expects SCALED input at
# inference time - the scaler is saved alongside it so downstream code
# (Stage 6 dashboard, etc.) knows to transform features before predicting.
# If Random Forest wins, no scaler is needed, but we still record which
# case applies in metadata so inference code doesn't have to guess.
requires_scaling = final_model_type == "LinearRegression"
if requires_scaling:
    scaler_path = os.path.join(MODELS_DIR, f"finish_model_{timestamp}_scaler.pkl")
    latest_scaler_path = os.path.join(MODELS_DIR, "finish_model_latest_scaler.pkl")
    joblib.dump(scaler, scaler_path)
    shutil.copyfile(scaler_path, latest_scaler_path)

metadata = {
    "trained_at": timestamp,
    "model_type": final_model_type,
    "requires_scaling": requires_scaling,
    "hyperparameters": (
        {"n_estimators": 100, "random_state": 42}
        if final_model_type == "RandomForestRegressor"
        else {}
    ),
    "feature_columns": feature_cols,
    "train_years": [int(train_df['year'].min()), int(train_df['year'].max())],
    "test_years": [int(test_df['year'].min()), int(test_df['year'].max())],
    "train_rows": int(len(train_df)),
    "test_rows": int(len(test_df)),
    "filtered_to_dnf_zero": True,
    "test_metrics": {k: float(v) for k, v in final_metrics.items()},
    "comparison": {
        "linear_regression": {k: float(v) for k, v in lr_metrics.items()},
        "random_forest_regressor": {k: float(v) for k, v in rf_metrics.items()},
    }
}

with open(versioned_meta_path, "w") as f:
    json.dump(metadata, f, indent=2)

shutil.copyfile(versioned_model_path, latest_model_path)
shutil.copyfile(versioned_meta_path, latest_meta_path)

print(f"\nModel saved: {versioned_model_path}")
print(f"Metadata saved: {versioned_meta_path}")
print(f"Latest pointers updated: {latest_model_path}, {latest_meta_path}")
