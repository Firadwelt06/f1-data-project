# definitions.py
from dagster import Definitions
from . import assets

defs = Definitions(assets=[
    assets.staged_data,
    assets.normalized_schema,
    assets.indexed_schema,
    assets.analytics_table,
])