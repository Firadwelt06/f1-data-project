# Formula 1 Data & Analytics Pipeline

This project builds a local Formula 1 data pipeline for ingesting source CSV data into a MySQL database, normalizing it into a relational schema, orchestrating ETL work with Dagster, training small analytics models, and exposing a lightweight dashboard for review.

It is structured as a practical end-to-end data engineering project: staging raw files, transforming them into structured tables, validating the load, and surfacing useful summaries through SQL and a Flask dashboard.

## Overview

The repository includes:

- ETL scripts for loading raw Formula 1 CSVs into MySQL staging tables
- Schema definitions for a normalized relational model
- Dagster project definitions for orchestration and pipeline execution
- ML utilities for finish-position and DNF prediction experiments
- A small dashboard for inspecting the loaded data and summary metrics
- Backup and restore utilities for schema/data recovery workflows

## Project structure

- `etl/` - data loading, schema creation, transformations, backups, and operational scripts
- `f1_dagster/` - Dagster definitions and orchestration entry points
- `ml/` - machine-learning preparation and model training scripts
- `dashboard/` - Flask dashboard app and supporting config
- `data/` - source Formula 1 CSV datasets
- `sql/` - SQL-related assets and supporting files
- `tests/` - project tests
- `dagster_home/` - local Dagster run metadata and storage

## Prerequisites

Before running the project, make sure you have:

- Python installed with `pip`
- A MySQL-compatible database server available locally or remotely
- Access to a project `.env` file with the required database configuration

## Environment setup

Create a `.env` file in the project root with the database variables used by the ETL and dashboard code, for example:

```env
DB_HOST=localhost
DB_PORT=3306
DB_USER=your_db_user
DB_PASSWORD=your_db_password
DB_NAME=f1_staging
```

If your workflow also uses Dagster or local runtime state, you may also need to set `DAGSTER_HOME` depending on how you run the pipeline.

## Installation

From the project root:

```bash
pip install -r requirements.txt
pip install -r dashboard/requirements.txt
```

## Loading the data

The ETL pipeline loads CSV files from the `data/` folder into MySQL staging tables:

```bash
python etl/load_staging.py
```

This script validates the DB connection, loads the CSVs in chunks, and checks row counts against the source files.

## Running the dashboard

From the dashboard folder:

```bash
cd dashboard
python app.py
```

Then open the local Flask app in a browser:

- http://127.0.0.1:5000

## Dagster

The Dagster configuration is defined under `f1_dagster/` and enabled through `pyproject.toml`.

Typical local execution pattern:

```bash
dagster dev
```

This project is set up for a local development workflow and may be extended with individual jobs or schedules as needed.

## ML experiments

The `ml/` directory includes scripts for preparing data and training model experiments related to race outcomes and DNF classification. These scripts are designed to work with the database tables produced by the ETL flow.

## Notes

- This repository is built around a local development database workflow.
- Some scripts expect `.env` values to be populated before they run.
- The raw staging layer is intentionally permissive; transformations and type-cleaning happen deliberately in later steps.

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.
