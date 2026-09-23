"""
pipeline_run_report.py

Queries Dagster's own run history (via the DagsterInstance API, reading
from DAGSTER_HOME) to report recent pipeline runs and surface details
for any that failed.

WHY GO THROUGH DagsterInstance INSTEAD OF READING DAGSTER_HOME DIRECTLY:
Dagster already persists every run's status, timing, and event log to a
database under DAGSTER_HOME. DagsterInstance is Dagster's own supported
API for querying that history -- it insulates this script from the
internal storage format, which isn't part of Dagster's public contract
and could change between versions.

USAGE:
    python etl/pipeline_run_report.py [limit] [--failures-only]

    limit            optional, defaults to 20 (how many recent runs to show)
    --failures-only  optional flag, show only failed runs
"""

import os
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DAGSTER_HOME = Path(os.environ.get("DAGSTER_HOME", PROJECT_ROOT / "dagster_home"))
DAGSTER_HOME.mkdir(parents=True, exist_ok=True)
os.environ["DAGSTER_HOME"] = str(DAGSTER_HOME)

from dagster import DagsterEventType, DagsterInstance, DagsterRunStatus


def format_timestamp(ts: float | None) -> str:
    if ts is None:
        return "--"
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def get_failure_messages(instance: DagsterInstance, run_id: str) -> list[str]:
    """Pulls the actual error message(s) for a failed run from its event log,
    rather than just reporting the bare FAILURE status."""
    records = instance.all_logs(run_id, of_type=DagsterEventType.STEP_FAILURE)
    messages = []
    for record in records:
        error = record.dagster_event.event_specific_data.error
        if error and error.message:
            # Keep just the first line -- full tracebacks are long and the
            # first line is almost always the actual exception summary.
            messages.append(error.message.strip().splitlines()[0])
    return messages


def main() -> None:
    args = sys.argv[1:]
    failures_only = "--failures-only" in args
    numeric_args = [a for a in args if a != "--failures-only"]
    limit = int(numeric_args[0]) if numeric_args else 20

    instance = DagsterInstance.get()
    runs = instance.get_runs(limit=limit)

    if not runs:
        print("No runs found in Dagster's run history yet.")
        return

    success_count = sum(1 for r in runs if r.status == DagsterRunStatus.SUCCESS)
    failure_count = sum(1 for r in runs if r.status == DagsterRunStatus.FAILURE)

    print(f"Showing last {len(runs)} run(s)   Success: {success_count}   Failure: {failure_count}")
    print("=" * 90)

    for run in runs:
        if failures_only and run.status != DagsterRunStatus.FAILURE:
            continue

        stats = instance.get_run_stats(run.run_id)
        start = stats.start_time
        end = stats.end_time
        duration = f"{end - start:.1f}s" if start and end else "--"

        job_label = run.job_name or "(unnamed job)"
        print(f"[{run.status.value:>10}] {job_label}  run_id={run.run_id[:8]}")
        print(f"    started={format_timestamp(start)}  duration={duration}")

        if run.status == DagsterRunStatus.FAILURE:
            messages = get_failure_messages(instance, run.run_id)
            if messages:
                for msg in messages:
                    print(f"    ERROR: {msg}")
            else:
                print("    (No step-level failure message found -- check the Dagster UI for full traceback.)")
        print()


if __name__ == "__main__":
    main()