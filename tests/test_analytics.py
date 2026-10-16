"""Analytics sink tests (SPEC section 8.3, task D2)."""

from __future__ import annotations

import json

from harnessguard_core.analytics import BigQuerySink, JsonlSink, get_sink


def test_jsonl_sink_writes_row(tmp_path):
    sink = JsonlSink(tmp_path)
    row = {"session_id": "abc", "decision": "allow", "fp_webdriver": 0.0}
    sink.write_session_features(row)
    sink.write_session_features(row)
    lines = (tmp_path / "session_features.jsonl").read_text().splitlines()
    assert len(lines) == 2 and json.loads(lines[0]) == row


def test_get_sink_defaults_to_jsonl():
    assert isinstance(get_sink(), JsonlSink)


def test_get_sink_bigquery(monkeypatch):
    monkeypatch.setenv("ANALYTICS_SINK", "bigquery")
    monkeypatch.setenv("GCP_PROJECT", "demo-project")
    sink = get_sink()
    assert isinstance(sink, BigQuerySink)
    # no credentials locally: writes are swallowed, never raise
    sink.write_session_features({"session_id": "x"})


def test_jsonl_sink_never_raises(tmp_path):
    blocker = tmp_path / "a-file-not-a-dir"
    blocker.write_text("x")
    JsonlSink(blocker / "sub").write_session_features({"a": 1})  # must not raise
