-- Staging schema for F1 dataset
-- Deliberately permissive: VARCHAR everywhere, no PKs/FKs/NOT NULL.
-- Purpose is a lossless landing zone for raw CSV data before Stage 2 normalization.

CREATE DATABASE IF NOT EXISTS f1_staging;
USE f1_staging;

DROP TABLE IF EXISTS stg_circuits;
CREATE TABLE stg_circuits (
    stg_id INT AUTO_INCREMENT PRIMARY KEY,
    `circuitId` VARCHAR(500) NULL,
    `circuitRef` VARCHAR(500) NULL,
    `name` VARCHAR(500) NULL,
    `location` VARCHAR(500) NULL,
    `country` VARCHAR(500) NULL,
    `lat` VARCHAR(500) NULL,
    `lng` VARCHAR(500) NULL,
    `alt` VARCHAR(500) NULL,
    `url` VARCHAR(500) NULL,
    source_file VARCHAR(255) NULL,
    loaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

DROP TABLE IF EXISTS stg_constructor_results;
CREATE TABLE stg_constructor_results (
    stg_id INT AUTO_INCREMENT PRIMARY KEY,
    `constructorResultsId` VARCHAR(500) NULL,
    `raceId` VARCHAR(500) NULL,
    `constructorId` VARCHAR(500) NULL,
    `points` VARCHAR(500) NULL,
    `status` VARCHAR(500) NULL,
    source_file VARCHAR(255) NULL,
    loaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

DROP TABLE IF EXISTS stg_constructor_standings;
CREATE TABLE stg_constructor_standings (
    stg_id INT AUTO_INCREMENT PRIMARY KEY,
    `constructorStandingsId` VARCHAR(500) NULL,
    `raceId` VARCHAR(500) NULL,
    `constructorId` VARCHAR(500) NULL,
    `points` VARCHAR(500) NULL,
    `position` VARCHAR(500) NULL,
    `positionText` VARCHAR(500) NULL,
    `wins` VARCHAR(500) NULL,
    source_file VARCHAR(255) NULL,
    loaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

DROP TABLE IF EXISTS stg_constructors;
CREATE TABLE stg_constructors (
    stg_id INT AUTO_INCREMENT PRIMARY KEY,
    `constructorId` VARCHAR(500) NULL,
    `constructorRef` VARCHAR(500) NULL,
    `name` VARCHAR(500) NULL,
    `nationality` VARCHAR(500) NULL,
    `url` VARCHAR(500) NULL,
    source_file VARCHAR(255) NULL,
    loaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

DROP TABLE IF EXISTS stg_driver_standings;
CREATE TABLE stg_driver_standings (
    stg_id INT AUTO_INCREMENT PRIMARY KEY,
    `driverStandingsId` VARCHAR(500) NULL,
    `raceId` VARCHAR(500) NULL,
    `driverId` VARCHAR(500) NULL,
    `points` VARCHAR(500) NULL,
    `position` VARCHAR(500) NULL,
    `positionText` VARCHAR(500) NULL,
    `wins` VARCHAR(500) NULL,
    source_file VARCHAR(255) NULL,
    loaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

DROP TABLE IF EXISTS stg_drivers;
CREATE TABLE stg_drivers (
    stg_id INT AUTO_INCREMENT PRIMARY KEY,
    `driverId` VARCHAR(500) NULL,
    `driverRef` VARCHAR(500) NULL,
    `number` VARCHAR(500) NULL,
    `code` VARCHAR(500) NULL,
    `forename` VARCHAR(500) NULL,
    `surname` VARCHAR(500) NULL,
    `dob` VARCHAR(500) NULL,
    `nationality` VARCHAR(500) NULL,
    `url` VARCHAR(500) NULL,
    source_file VARCHAR(255) NULL,
    loaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

DROP TABLE IF EXISTS stg_lap_times;
CREATE TABLE stg_lap_times (
    stg_id INT AUTO_INCREMENT PRIMARY KEY,
    `raceId` VARCHAR(500) NULL,
    `driverId` VARCHAR(500) NULL,
    `lap` VARCHAR(500) NULL,
    `position` VARCHAR(500) NULL,
    `time` VARCHAR(500) NULL,
    `milliseconds` VARCHAR(500) NULL,
    source_file VARCHAR(255) NULL,
    loaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

DROP TABLE IF EXISTS stg_pit_stops;
CREATE TABLE stg_pit_stops (
    stg_id INT AUTO_INCREMENT PRIMARY KEY,
    `raceId` VARCHAR(500) NULL,
    `driverId` VARCHAR(500) NULL,
    `stop` VARCHAR(500) NULL,
    `lap` VARCHAR(500) NULL,
    `time` VARCHAR(500) NULL,
    `duration` VARCHAR(500) NULL,
    `milliseconds` VARCHAR(500) NULL,
    source_file VARCHAR(255) NULL,
    loaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

DROP TABLE IF EXISTS stg_practice_results;
CREATE TABLE stg_practice_results (
    stg_id INT AUTO_INCREMENT PRIMARY KEY,
    `raceId` VARCHAR(500) NULL,
    `driverId` VARCHAR(500) NULL,
    `session` VARCHAR(500) NULL,
    `position` VARCHAR(500) NULL,
    `bestLapTime` VARCHAR(500) NULL,
    `laps` VARCHAR(500) NULL,
    source_file VARCHAR(255) NULL,
    loaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

DROP TABLE IF EXISTS stg_qualifying;
CREATE TABLE stg_qualifying (
    stg_id INT AUTO_INCREMENT PRIMARY KEY,
    `qualifyId` VARCHAR(500) NULL,
    `raceId` VARCHAR(500) NULL,
    `driverId` VARCHAR(500) NULL,
    `constructorId` VARCHAR(500) NULL,
    `number` VARCHAR(500) NULL,
    `position` VARCHAR(500) NULL,
    `q1` VARCHAR(500) NULL,
    `q2` VARCHAR(500) NULL,
    `q3` VARCHAR(500) NULL,
    source_file VARCHAR(255) NULL,
    loaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

DROP TABLE IF EXISTS stg_races;
CREATE TABLE stg_races (
    stg_id INT AUTO_INCREMENT PRIMARY KEY,
    `raceId` VARCHAR(500) NULL,
    `year` VARCHAR(500) NULL,
    `round` VARCHAR(500) NULL,
    `circuitId` VARCHAR(500) NULL,
    `name` VARCHAR(500) NULL,
    `date` VARCHAR(500) NULL,
    `time` VARCHAR(500) NULL,
    `url` VARCHAR(500) NULL,
    `fp1_date` VARCHAR(500) NULL,
    `fp1_time` VARCHAR(500) NULL,
    `fp2_date` VARCHAR(500) NULL,
    `fp2_time` VARCHAR(500) NULL,
    `fp3_date` VARCHAR(500) NULL,
    `fp3_time` VARCHAR(500) NULL,
    `quali_date` VARCHAR(500) NULL,
    `quali_time` VARCHAR(500) NULL,
    `sprint_date` VARCHAR(500) NULL,
    `sprint_time` VARCHAR(500) NULL,
    source_file VARCHAR(255) NULL,
    loaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

DROP TABLE IF EXISTS stg_results;
CREATE TABLE stg_results (
    stg_id INT AUTO_INCREMENT PRIMARY KEY,
    `resultId` VARCHAR(500) NULL,
    `raceId` VARCHAR(500) NULL,
    `driverId` VARCHAR(500) NULL,
    `constructorId` VARCHAR(500) NULL,
    `number` VARCHAR(500) NULL,
    `grid` VARCHAR(500) NULL,
    `position` VARCHAR(500) NULL,
    `positionText` VARCHAR(500) NULL,
    `positionOrder` VARCHAR(500) NULL,
    `points` VARCHAR(500) NULL,
    `laps` VARCHAR(500) NULL,
    `time` VARCHAR(500) NULL,
    `milliseconds` VARCHAR(500) NULL,
    `fastestLap` VARCHAR(500) NULL,
    `rank` VARCHAR(500) NULL,
    `fastestLapTime` VARCHAR(500) NULL,
    `fastestLapSpeed` VARCHAR(500) NULL,
    `statusId` VARCHAR(500) NULL,
    source_file VARCHAR(255) NULL,
    loaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

DROP TABLE IF EXISTS stg_seasons;
CREATE TABLE stg_seasons (
    stg_id INT AUTO_INCREMENT PRIMARY KEY,
    `year` VARCHAR(500) NULL,
    `url` VARCHAR(500) NULL,
    source_file VARCHAR(255) NULL,
    loaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

DROP TABLE IF EXISTS stg_sprint_results;
CREATE TABLE stg_sprint_results (
    stg_id INT AUTO_INCREMENT PRIMARY KEY,
    `resultId` VARCHAR(500) NULL,
    `raceId` VARCHAR(500) NULL,
    `driverId` VARCHAR(500) NULL,
    `constructorId` VARCHAR(500) NULL,
    `number` VARCHAR(500) NULL,
    `grid` VARCHAR(500) NULL,
    `position` VARCHAR(500) NULL,
    `positionText` VARCHAR(500) NULL,
    `positionOrder` VARCHAR(500) NULL,
    `points` VARCHAR(500) NULL,
    `laps` VARCHAR(500) NULL,
    `time` VARCHAR(500) NULL,
    `milliseconds` VARCHAR(500) NULL,
    `fastestLap` VARCHAR(500) NULL,
    `fastestLapTime` VARCHAR(500) NULL,
    `statusId` VARCHAR(500) NULL,
    source_file VARCHAR(255) NULL,
    loaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

DROP TABLE IF EXISTS stg_status;
CREATE TABLE stg_status (
    stg_id INT AUTO_INCREMENT PRIMARY KEY,
    `statusId` VARCHAR(500) NULL,
    `status` VARCHAR(500) NULL,
    source_file VARCHAR(255) NULL,
    loaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

DROP TABLE IF EXISTS stg_tire_stints;
CREATE TABLE stg_tire_stints (
    stg_id INT AUTO_INCREMENT PRIMARY KEY,
    `raceId` VARCHAR(500) NULL,
    `driverId` VARCHAR(500) NULL,
    `stint` VARCHAR(500) NULL,
    `compound` VARCHAR(500) NULL,
    `startLap` VARCHAR(500) NULL,
    `endLap` VARCHAR(500) NULL,
    `lapsOnTire` VARCHAR(500) NULL,
    source_file VARCHAR(255) NULL,
    loaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

DROP TABLE IF EXISTS stg_weather;
CREATE TABLE stg_weather (
    stg_id INT AUTO_INCREMENT PRIMARY KEY,
    `raceId` VARCHAR(500) NULL,
    `airTempAvg` VARCHAR(500) NULL,
    `airTempMin` VARCHAR(500) NULL,
    `airTempMax` VARCHAR(500) NULL,
    `trackTempAvg` VARCHAR(500) NULL,
    `trackTempMin` VARCHAR(500) NULL,
    `trackTempMax` VARCHAR(500) NULL,
    `humidityAvg` VARCHAR(500) NULL,
    `windSpeedAvg` VARCHAR(500) NULL,
    `windSpeedMax` VARCHAR(500) NULL,
    `rainfall` VARCHAR(500) NULL,
    source_file VARCHAR(255) NULL,
    loaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- FIRST_QUERY
-- Career wins
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
HAVING starts >= 20          -- filters out one-off/reserve appearances
ORDER BY win_pct DESC
LIMIT 20;

-- CONSTRUCTOR DOMINANCE BY ERA
SELECT
    (r.year DIV 10) * 10 AS decade,
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
ORDER BY decade, win_pct_in_decade DESC;

-- Ranked by decade
WITH decade_stats AS (
    SELECT
        (r.year DIV 10) * 10 AS decade,
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
ORDER BY decade, dominance_rank;

-- pit stop trends
SELECT
    r.year,
    COUNT(*) AS total_stops,
    COUNT(DISTINCT ps.raceId) AS races_with_stops,
    ROUND(COUNT(*) / COUNT(DISTINCT ps.raceId), 2) AS avg_stops_per_race,
    ROUND(AVG(ps.milliseconds) / 1000, 3) AS avg_stop_duration_sec,
    ROUND(MIN(ps.milliseconds) / 1000, 3) AS fastest_stop_sec
FROM pit_stops ps
JOIN races r ON r.raceId = ps.raceId
WHERE ps.milliseconds > 0          -- excludes red-flag-affected stops with a bad 0ms value
GROUP BY r.year
ORDER BY r.year;

-- head to head driver comparison
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
WHERE d1.driverId = 1
  AND d2.driverId = 830
GROUP BY d1.driverId, d2.driverId, d1.forename, d1.surname, d2.forename, d2.surname;

SELECT driverId, forename, surname FROM drivers
WHERE surname IN ('Hamilton', 'Verstappen');

-- first other question: longest consecutive race-win streak per driver
WITH RECURSIVE driver_race_seq AS (
    SELECT
        r.driverId,
        ra.raceId,
        ra.date,
        ROW_NUMBER() OVER (PARTITION BY r.driverId ORDER BY ra.date) AS seq,
        CASE WHEN r.positionOrder = 1 THEN 1 ELSE 0 END AS is_win
    FROM results r
    JOIN races ra ON ra.raceId = r.raceId
	), streaks AS (
    -- Anchor: every driver's very first race starts their timeline
    SELECT driverId, seq, is_win, is_win AS streak_length
    FROM driver_race_seq
    WHERE seq = 1
    UNION ALL

    -- Recursive step: extend the streak if this race is also a win,
    -- otherwise reset it to 0
    SELECT
        drs.driverId,
        drs.seq,
        drs.is_win,
        CASE WHEN drs.is_win = 1 THEN s.streak_length + 1 ELSE 0 END
    FROM driver_race_seq drs
    JOIN streaks s
        ON s.driverId = drs.driverId
       AND drs.seq = s.seq + 1
)
SELECT
    d.forename,
    d.surname,
    MAX(st.streak_length) AS longest_win_streak
FROM streaks st
JOIN drivers d ON d.driverId = st.driverId
GROUP BY st.driverId, d.forename, d.surname
ORDER BY longest_win_streak DESC
LIMIT 15;

-- EXPLAIN ANALYZE FOR LONGEST WIN STREAK
-- first creating index
CREATE INDEX idx_results_race_driver_order 
ON results (raceId, driverId, positionOrder);
-- the explain analyze
EXPLAIN ANALYZE
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
LIMIT 15;

-- checking again
-- for duplicates
SELECT raceId, driverId, COUNT(*) AS row_count
FROM results
GROUP BY raceId, driverId
HAVING COUNT(*) > 1;

-- verstappen win streak
SELECT
    ra.date,
    r.positionOrder,
    CASE WHEN r.positionOrder = 1 THEN 1 ELSE 0 END AS is_win,
    SUM(CASE WHEN r.positionOrder = 1 THEN 0 ELSE 1 END)
        OVER (PARTITION BY r.driverId ORDER BY ra.date) AS streak_group
FROM results r
JOIN races ra ON ra.raceId = r.raceId
WHERE r.driverId = 830
ORDER BY ra.date;

-- SEPERATE SCHEMA FOR LOGS
USE f1_monitoring;
CREATE TABLE IF NOT EXISTS f1_monitoring.table_growth_log (
    snapshot_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    snapshot_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    table_name VARCHAR(64) NOT NULL,
    row_count BIGINT NOT NULL,
    data_length_bytes BIGINT NOT NULL,
    index_length_bytes BIGINT NOT NULL,
    total_size_bytes BIGINT GENERATED ALWAYS AS (data_length_bytes + index_length_bytes) STORED,
    INDEX idx_table_time (table_name, snapshot_time)
) ENGINE=InnoDB;

CREATE DATABASE f1_monitoring;

-- QUERY FOR MONITORING
SELECT table_name, snapshot_time, row_count, total_size_bytes
FROM f1_monitoring.table_growth_log
WHERE table_name = 'lap_times'
ORDER BY snapshot_time;

show tables;
DESCRIBE analytics_driver_race;