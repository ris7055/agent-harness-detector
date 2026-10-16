"""Analytics sink (SPEC section 8.3).

One row per decision lands in BigQuery ``harness_detector.session_features``
(cloud) or in ``data/analytics/session_features.jsonl`` (local). Best-effort
and off the request path: calls never raise into request handlers.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .config import get_settings

log = logging.getLogger("analytics")

_SESSION_FEATURES_TABLE = "session_features"


class AnalyticsSink:
    """Best-effort per-decision feature snapshot writer."""

    def write_session_features(self, row: dict[str, Any]) -> None:  # pragma: no cover
        raise NotImplementedError


class JsonlSink(AnalyticsSink):
    """Local sink: appends JSON lines under ``data/analytics/``."""

    def __init__(self, base_dir: str | Path = "data/analytics"):
        self._dir = Path(base_dir)

    def write_session_features(self, row: dict[str, Any]) -> None:
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            with (self._dir / f"{_SESSION_FEATURES_TABLE}.jsonl").open(
                "a", encoding="utf-8"
            ) as fh:
                fh.write(json.dumps(row, default=str) + "\n")
        except Exception:  # noqa: BLE001 - never raise into request handlers
            log.warning("JsonlSink write failed", exc_info=True)


class BigQuerySink(AnalyticsSink):
    """Cloud sink: insert_rows_json into <project>.<dataset>.session_features."""

    def __init__(self, project: str, dataset: str):
        self._table = f"{project}.{dataset}.{_SESSION_FEATURES_TABLE}"
        self._client = None

    def _get_client(self):
        if self._client is None:
            from google.cloud import bigquery  # lazy: only when sink selected

            self._client = bigquery.Client(project=self._table.split(".")[0])
        return self._client

    def write_session_features(self, row: dict[str, Any]) -> None:
        try:
            errors = self._get_client().insert_rows_json(self._table, [row])
            if errors:
                log.warning("BigQuery insert_rows_json errors: %s", errors)
        except Exception:  # noqa: BLE001 - never raise into request handlers
            log.warning("BigQuerySink write failed", exc_info=True)


def get_sink() -> AnalyticsSink:
    """Choose the sink from ANALYTICS_SINK (jsonl|bigquery)."""
    settings = get_settings()
    if settings.analytics_sink == "bigquery":
        return BigQuerySink(settings.gcp_project, settings.bq_dataset)
    return JsonlSink()
