"""Compatibility wrapper for the analytics builder."""

from etl.build_analytics_table import *  # noqa: F401,F403

if __name__ == "__main__":
    from etl.build_analytics_table import main

    main()
