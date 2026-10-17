"""Emit BigQuery JSON schemas for the HarnessGuard tables (SPEC section 8.3).

The feature columns are generated from the single FEATURE_NAMES contract so the
BigQuery schema can never drift from the scorer. Usage:

    python3 deploy/bq_schema.py session_features    > /tmp/session_features.json
    python3 deploy/bq_schema.py training_features   > /tmp/training_features.json
    python3 deploy/bq_schema.py raw_event_batches    > /tmp/raw_event_batches.json
    python3 deploy/bq_schema.py benchmark_results    > /tmp/benchmark_results.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from harnessguard_core.features import FEATURE_NAMES  # noqa: E402


def _f(name: str, ftype: str, mode: str = "NULLABLE") -> dict:
    return {"name": name, "type": ftype, "mode": mode}


def _features() -> list[dict]:
    return [_f(n, "FLOAT64") for n in FEATURE_NAMES]


SCHEMAS = {
    # Written by the Pub/Sub BigQuery subscription (table schema, not the
    # topic schema): the default columns a BQ subscription delivers.
    "raw_event_batches": [
        _f("subscription_name", "STRING"),
        _f("message_id", "STRING"),
        _f("publish_time", "TIMESTAMP"),
        _f("data", "STRING"),
        _f("attributes", "STRING"),
    ],
    # One row per decision (the scorer's analytics sink).
    "session_features": [
        _f("session_id", "STRING"),
        _f("decided_at", "TIMESTAMP"),
        _f("action", "STRING"),
        _f("model_version", "STRING"),
        _f("score", "FLOAT64"),
        _f("decision", "STRING"),
        *_features(),
    ],
    # Training rows written by ml/build_dataset.py (D6).
    "training_features": [
        _f("session_id", "STRING"),
        _f("label", "INT64"),
        _f("variant", "STRING"),
        _f("collector", "STRING"),
        _f("task_id", "STRING"),
        _f("split", "STRING"),
        _f("split_variant", "STRING"),
        *_features(),
    ],
    # One row per (model, metric, slice) from the benchmark (D6).
    "benchmark_results": [
        _f("generated_at", "TIMESTAMP"),
        _f("model", "STRING"),
        _f("metric", "STRING"),
        _f("slice", "STRING"),
        _f("value", "FLOAT64"),
    ],
}


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[1] not in SCHEMAS:
        sys.stderr.write(f"usage: {argv[0]} <{'|'.join(SCHEMAS)}>\n")
        return 2
    json.dump(SCHEMAS[argv[1]], sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
