"""Active scoring model for the scorer (SPEC section 7.3).

``MODEL_URI`` resolution:
  - empty            -> rules baseline
  - local directory  -> <dir>/model.json + <dir>/model_meta.json
  - *.json pointer   -> JSON with {"model": <uri>, "meta": <uri>} (the
    latest.json format written by ml/train.py --upload; the alternate keys
    "model_uri"/"meta_uri" are accepted too)
  - anything else    -> treated as a directory/prefix (also works for
    gs://bucket/prefix)

The booster is only loaded when the meta's feature_names match
harnessguard_core.features.FEATURE_NAMES; any failure falls back to rules
with a loud log so the service always starts.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from harnessguard_core.features import FEATURE_NAMES
from harnessguard_core.rules import score_rules

log = logging.getLogger("scorer.model")

RULES_VERSION = "rules"


def _read_uri(uri: str) -> bytes:
    if uri.startswith("gs://"):
        from google.cloud import storage  # lazy: only for gs:// URIs

        bucket_name, _, blob_name = uri[5:].partition("/")
        client = storage.Client()
        return client.bucket(bucket_name).blob(blob_name).download_as_bytes()
    return Path(uri).read_bytes()


def _is_not_found(exc: BaseException) -> bool:
    """True for a missing local file or a GCS 404 (no model trained yet)."""
    if isinstance(exc, FileNotFoundError):
        return True
    return type(exc).__name__ == "NotFound" or getattr(exc, "code", None) == 404


def _sibling(uri: str, name: str) -> str:
    """<dir>/<name> next to ``uri`` (works for local paths and gs://)."""
    return uri.rsplit("/", 1)[0].rstrip("/") + "/" + name


def _resolve(uri: str) -> tuple[str, str]:
    """MODEL_URI -> (model_uri, meta_uri)."""
    if not uri.startswith("gs://") and Path(uri).is_dir():
        p = Path(uri)
        return str(p / "model.json"), str(p / "model_meta.json")
    if uri.endswith(".json"):
        pointer = json.loads(_read_uri(uri))
        model_uri = pointer.get("model") or pointer.get("model_uri")
        if not model_uri:
            raise ValueError(f"pointer file {uri} has no 'model' key")
        meta_uri = (
            pointer.get("meta")
            or pointer.get("meta_uri")
            or _sibling(model_uri, "model_meta.json")
        )
        return model_uri, meta_uri
    base = uri.rstrip("/")
    return f"{base}/model.json", f"{base}/model_meta.json"


class Scorer:
    """Scores a feature dict. XGBoost when a valid model is loaded, else rules."""

    def __init__(self) -> None:
        self._booster: Any = None
        self._feature_names: list[str] | None = None
        self.meta: dict[str, Any] = {}
        self.version = RULES_VERSION

    @property
    def mode(self) -> str:
        return "xgboost" if self._booster is not None else "rules"

    def load(self, model_uri: str) -> None:
        if not model_uri:
            log.info("MODEL_URI empty: using rules baseline")
            return
        try:
            m_uri, meta_uri = _resolve(model_uri)
            meta = json.loads(_read_uri(meta_uri))
            names = meta.get("feature_names")
            if names != FEATURE_NAMES:
                raise ValueError(
                    f"model feature_names mismatch (model has "
                    f"{len(names or [])} names, expected {len(FEATURE_NAMES)})"
                )
            import xgboost as xgb  # lazy: only when a model is configured

            booster = xgb.Booster()
            booster.load_model(bytearray(_read_uri(m_uri)))
            self._booster = booster
            self._feature_names = names
            self.meta = meta
            self.version = str(meta.get("version") or "xgboost")
            log.info("loaded XGBoost model version=%s from %s", self.version, m_uri)
        except Exception as exc:  # noqa: BLE001 - always start, on rules
            if _is_not_found(exc):
                # Expected until a model is trained (D6): no scary traceback.
                log.warning(
                    "no model at MODEL_URI=%s yet; using rules baseline", model_uri
                )
            else:
                log.exception(
                    "MODEL_URI=%s failed to load; falling back to rules", model_uri
                )
            self._booster = None
            self._feature_names = None
            self.meta = {}
            self.version = RULES_VERSION

    def score(self, features: dict[str, float]) -> tuple[float, list[dict[str, Any]]]:
        if self._booster is None:
            return score_rules(features)
        import xgboost as xgb

        # meta.feature_names was validated against FEATURE_NAMES at load
        # time. Pass the names explicitly: a booster trained from a named
        # DMatrix/DataFrame refuses unnamed input.
        row = [[features.get(n, -1.0) for n in self._feature_names]]
        try:
            dmat = xgb.DMatrix(row, feature_names=self._feature_names)
            prob = float(self._booster.predict(dmat)[0])
            contribs = self._booster.predict(dmat, pred_contribs=True)[0]
        except Exception:  # noqa: BLE001 - a bad model must not take decisions down
            log.exception("model scoring failed; using rules for this request")
            return score_rules(features)
        reasons = sorted(
            (
                {"feature": n, "value": row[0][i], "contribution": round(float(contribs[i]), 4)}
                for i, n in enumerate(self._feature_names)
                if contribs[i] > 0
            ),
            key=lambda r: r["contribution"],
            reverse=True,
        )[:5]
        return prob, reasons
