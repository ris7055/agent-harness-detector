"""Scorer model loading tests (SPEC section 7.3, task D2).

MODEL_URI resolution: empty -> rules; local directory; latest.json pointer
({"model": ..., "meta": ...} per ml/train.py --upload); feature-name mismatch
-> rules fallback.
"""

from __future__ import annotations

import json

import pytest

from harnessguard_core.features import FEATURE_NAMES

import scorer_app.model as model_mod


def test_empty_uri_uses_rules():
    s = model_mod.Scorer()
    s.load("")
    assert s.mode == "rules" and s.version == "rules"
    score, reasons = s.score({"fp_webdriver": 1.0})
    # webdriver=true alone clears the step-up threshold
    assert 0.5 < score < 1.0 and reasons


def test_missing_uri_falls_back_to_rules(tmp_path):
    s = model_mod.Scorer()
    s.load(str(tmp_path / "does-not-exist"))
    assert s.mode == "rules" and s.version == "rules"


def test_feature_name_mismatch_falls_back(tmp_path):
    (tmp_path / "model.json").write_text("{}")
    (tmp_path / "model_meta.json").write_text(json.dumps({
        "version": "v1", "feature_names": ["wrong_one", "wrong_two"],
    }))
    s = model_mod.Scorer()
    s.load(str(tmp_path))
    assert s.mode == "rules" and s.version == "rules"


def test_latest_json_pointer_resolution(tmp_path):
    model_dir = tmp_path / "20261016T000000Z"
    model_dir.mkdir()
    (model_dir / "model.json").write_text("{}")
    (model_dir / "model_meta.json").write_text("{}")
    pointer = tmp_path / "latest.json"
    pointer.write_text(json.dumps({
        "model": str(model_dir / "model.json"),
        "meta": str(model_dir / "model_meta.json"),
    }))
    m, meta = model_mod._resolve(str(pointer))
    assert m.endswith("model.json") and meta.endswith("model_meta.json")
    assert "20261016T000000Z" in m


def test_real_xgboost_model_loads_and_scores(tmp_path):
    try:
        import xgboost as xgb
    except Exception as exc:  # OpenMP runtime missing on this machine
        pytest.skip(f"xgboost unavailable: {exc}")
    import numpy as np

    rng = np.random.Random(0)
    X = rng.rand(40, len(FEATURE_NAMES))
    y = np.array([0, 1] * 20)
    clf = xgb.XGBClassifier(n_estimators=5, max_depth=2)
    clf.fit(X, y)
    clf.get_booster().save_model(str(tmp_path / "model.json"))
    (tmp_path / "model_meta.json").write_text(json.dumps({
        "version": "test-v1", "feature_names": FEATURE_NAMES,
        "trained_at": "2026-10-16T00:00:00Z", "metrics": {},
    }))

    s = model_mod.Scorer()
    s.load(str(tmp_path))
    assert s.mode == "xgboost" and s.version == "test-v1"
    score, reasons = s.score({n: 0.5 for n in FEATURE_NAMES})
    assert 0.0 <= score <= 1.0 and len(reasons) <= 5
