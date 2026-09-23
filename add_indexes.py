"""Compatibility wrapper for the index-creation helper."""

from etl.add_indexes import *  # noqa: F401,F403

if __name__ == "__main__":
    from etl.add_indexes import main

    main()
