"""Compatibility wrapper for the ETL transform module.

This allows imports such as `from transform_load import cast_time` to work
when the project is run from the repository root, while still delegating to
`etl.transform_load` for the real implementation.
"""

from etl.transform_load import *  # noqa: F401,F403

if __name__ == "__main__":
    from etl.transform_load import main

    main()
