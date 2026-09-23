"""Compatibility wrapper for the shared schema definitions."""

from etl.schema import *  # noqa: F401,F403

if __name__ == "__main__":
    from etl.schema import metadata, engine

    metadata.create_all(engine)
    print(f"Created {len(metadata.tables)} tables in the configured database.")
