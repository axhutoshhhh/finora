"""Repeatable Phase 3 performance baseline across 0, 100, 1k, and 10k datasets."""

from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.migrations.runner import initialize_database
from app.services import (
    advisory_service,
    analytics_service,
    backup_service,
    goal_service,
    overview_service,
    recurring_service,
)
from benchmarks.baseline_phase2 import _bulk_seed_transactions, _time_calls


def run_benchmark() -> dict[str, Any]:
    results: dict[str, Any] = {"datasets": {}}
    for size in (0, 100, 1_000, 10_000):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "bench3.sqlite3"
            initialize_database(db_path)
            _bulk_seed_transactions(db_path, size)
            m = {
                "overview_load": _time_calls(
                    lambda p=db_path: overview_service.get_overview(p, month="2026-11"),
                    iterations=8,
                ),
                "analytics_report": _time_calls(
                    lambda p=db_path: analytics_service.get_full_analytics_report(
                        p, preset="all_time"
                    ),
                    iterations=8,
                ),
                "advisory_eval": _time_calls(
                    lambda p=db_path: advisory_service.evaluate_advisories(p, month="2026-11"),
                    iterations=5,
                ),
                "goals_list": _time_calls(
                    lambda p=db_path: goal_service.list_goals(p), iterations=8
                ),
                "recurring_list": _time_calls(
                    lambda p=db_path: recurring_service.list_rules(p), iterations=8
                ),
            }
            t_b = time.perf_counter()
            backup_service.create_workspace_backup(Path(td), db_path)
            m["backup_create_ms"] = round((time.perf_counter() - t_b) * 1000.0, 2)
            results["datasets"][str(size)] = m
    return results


if __name__ == "__main__":
    print(json.dumps(run_benchmark(), indent=2))
