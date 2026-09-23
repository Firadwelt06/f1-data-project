import pandas as pd
from sqlalchemy import create_engine, text
import os
from dotenv import load_dotenv

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

print(df.shape)
print(df.isnull().sum())
print(df['dnf'].value_counts())
print(df[df['finishPosition'].isnull()]['dnf'].value_counts())
print(df[df['dnf'] == 1]['finishPosition'].isnull().value_counts())

# Columns that go cold for early-career drivers/constructors
driver_coldstart_cols = [
    'rollingAvgPoints_last5',
    'rollingAvgFinishPos_last5',
    'priorWins',
    'priorWinPct'
]
constructor_coldstart_cols = [
    'constructorRollingAvgPoints_last5',
    'constructorWinPct_last10'
]

# Flag rows where the driver has no rolling history yet
df['is_rookie_driver'] = df[driver_coldstart_cols].isnull().any(axis=1).astype(int)

# Flag rows where the constructor has no rolling history yet
df['is_new_constructor'] = df[constructor_coldstart_cols].isnull().any(axis=1).astype(int)

# Sentinel-fill the actual NULLs
for col in driver_coldstart_cols + constructor_coldstart_cols:
    df[col] = df[col].fillna(-1)

# Sanity check: no NULLs left except finishPosition (expected, DNF rows)
print(df.isnull().sum())

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

# Display the column names and shape of the DataFrame
print(df.columns.tolist())
print(df.shape)

# Split the data into training and testing sets based on the year
train_df = df[df['year'] < 2025].copy()
test_df = df[df['year'] >= 2025].copy()

print(f"Train: {train_df.shape[0]} rows, years {train_df['year'].min()}-{train_df['year'].max()}")
print(f"Test:  {test_df.shape[0]} rows, years {test_df['year'].min()}-{test_df['year'].max()}")

# Define the feature columns to be used for modeling
feature_cols = [
    'grid', 'qualifyingPosition', 'driverAgeAtRaceDays', 'priorRaceCount',
    'rollingAvgPoints_last5', 'rollingAvgFinishPos_last5',
    'constructorRollingAvgPoints_last5', 'priorWins', 'priorWinPct',
    'constructorWinPct_last10', 'priorWinStreak',
    'is_rookie_driver', 'is_new_constructor',
    'era_1981_2005', 'era_2006_2013_v8', 'era_2014_2021_hybrid',
    'era_2022_plus_ground_effect'
    # note: era_pre_1981 doesn't exist as a column — that's fine, it's the reference case
]

# Stage A: DNF classifier — uses ALL rows (DNF or not)
X_train_dnf = train_df[feature_cols]
y_train_dnf = train_df['dnf']
X_test_dnf = test_df[feature_cols]
y_test_dnf = test_df['dnf']

# Stage B: finish position regressor — ONLY non-DNF rows
train_finished = train_df[train_df['dnf'] == 0]
test_finished = test_df[test_df['dnf'] == 0]

X_train_finish = train_finished[feature_cols]
y_train_finish = train_finished['finishPosition']
X_test_finish = test_finished[feature_cols]
y_test_finish = test_finished['finishPosition']

print(f"Stage A - train: {X_train_dnf.shape}, test: {X_test_dnf.shape}")
print(f"Stage B - train: {X_train_finish.shape}, test: {X_test_finish.shape}")
