# assets.py
from dagster import asset
from etl import load_staging
from etl import transform_load
from etl import add_indexes
from etl import build_analytics_table

@asset
def staged_data():
    """Loads F1 CSVs into stg_* tables."""
    load_staging.main()

@asset(deps=[staged_data])
def normalized_schema():
    """Casts + upserts staging data into the 3NF schema."""
    transform_load.main()

@asset(deps=[normalized_schema])
def indexed_schema():
    """Applies the deliberate indexes from Stage 2."""
    add_indexes.main()

@asset(deps=[normalized_schema])
def analytics_table():
    """Builds the denormalized analytics/feature table."""
    build_analytics_table.main()
