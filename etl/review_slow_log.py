"""
review_slow_log.py

Parses MySQL's slow query log and summarizes it: groups repeated query
patterns together (normalizing literal values so `WHERE driverId = 1`
and `WHERE driverId = 2` count as the same pattern), then reports each
pattern's occurrence count, total time, and average time.

WHY GROUP BY PATTERN INSTEAD OF LISTING RAW ENTRIES:
A query that ran slowly once might just be a one-off (cold cache, a
one-time backfill). A query pattern that ran slowly 200 times is a real
problem worth indexing or rewriting. Grouping surfaces the second case,
which a flat chronological log makes easy to miss.

USAGE:
    python etl/review_slow_log.py [path_to_slow_log] [top_n]

    path_to_slow_log  optional, defaults to MYSQL_SLOW_LOG_PATH in .env
    top_n             optional, defaults to 10 (show top 10 patterns by total time)
"""

import os
import re
import sys
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

DEFAULT_LOG_PATH = os.getenv("MYSQL_SLOW_LOG_PATH")

# Matches the "# Query_time: 1.234567  Lock_time: ..." header line that
# precedes each entry in MySQL's slow query log format.
QUERY_TIME_RE = re.compile(r"^# Query_time:\s*([\d.]+)")

# Used to normalize literal values in a query so repeated queries with
# different parameters collapse into the same pattern.
NUMBER_RE = re.compile(r"\b\d+\b")
STRING_RE = re.compile(r"'[^']*'")


def normalize_query(query: str) -> str:
    query = STRING_RE.sub("?", query)
    query = NUMBER_RE.sub("?", query)
    return " ".join(query.split())  # collapse whitespace/newlines


def parse_slow_log(log_path: Path):
    """Yields (query_time_seconds, normalized_query) for each entry."""
    current_time = None
    query_lines = []

    def flush():
        if current_time is not None and query_lines:
            raw_query = " ".join(query_lines).strip().rstrip(";")
            if raw_query and not raw_query.upper().startswith("SET TIMESTAMP"):
                yield current_time, normalize_query(raw_query)

    with open(log_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.rstrip("\n")

            match = QUERY_TIME_RE.match(line)
            if match:
                yield from flush()
                current_time = float(match.group(1))
                query_lines = []
                continue

            if line.startswith("#"):
                continue  # other header lines (Lock_time, Rows_examined, etc.)
            if line.startswith("SET timestamp"):
                continue
            if line.strip():
                query_lines.append(line.strip())

        yield from flush()


def main():
    args = sys.argv[1:]
    log_path = Path(args[0]) if len(args) >= 1 else Path(DEFAULT_LOG_PATH) if DEFAULT_LOG_PATH else None
    top_n = int(args[1]) if len(args) >= 2 else 10

    if log_path is None:
        raise RuntimeError(
            "No slow log path given and MYSQL_SLOW_LOG_PATH is not set in .env. "
            "Pass a path as the first argument, or add MYSQL_SLOW_LOG_PATH to .env."
        )
    if not log_path.exists():
        raise RuntimeError(f"Slow query log not found at: {log_path}")

    stats = defaultdict(lambda: {"count": 0, "total_time": 0.0, "max_time": 0.0})

    entry_count = 0
    for query_time, pattern in parse_slow_log(log_path):
        entry_count += 1
        s = stats[pattern]
        s["count"] += 1
        s["total_time"] += query_time
        s["max_time"] = max(s["max_time"], query_time)

    if entry_count == 0:
        print(f"No slow query entries found in {log_path}.")
        print("(This is good news -- it means nothing has exceeded long_query_time yet.)")
        return

    ranked = sorted(stats.items(), key=lambda kv: kv[1]["total_time"], reverse=True)

    print(f"Slow query log: {log_path}")
    print(f"Total slow-query entries: {entry_count}   Distinct patterns: {len(stats)}")
    print()
    print(f"Top {min(top_n, len(ranked))} patterns by total time:")
    print("-" * 90)

    for pattern, s in ranked[:top_n]:
        avg_time = s["total_time"] / s["count"]
        print(f"count={s['count']:<5} total={s['total_time']:.2f}s  avg={avg_time:.2f}s  max={s['max_time']:.2f}s")
        display_query = pattern if len(pattern) <= 150 else pattern[:150] + "..."
        print(f"  {display_query}")
        print()


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)