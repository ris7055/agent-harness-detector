# D6 — Dataset, model training, BigQuery ML, benchmark

**Branch:** `feat/d6-ml` · **Depends on:** D2, D4 merged (real data from humans + red team) · **Target:** day 4 (Oct 18)
**Spec sections:** §10, §7.3, §8.3

## Build
1. `ml/requirements.txt` (xgboost, scikit-learn, pandas, pyarrow, matplotlib, google-cloud-bigquery, google-cloud-storage, psycopg).
2. `ml/build_dataset.py --source postgres|bigquery [--database-url ...]` per §10.1: labelled sessions only; features via `harnessguard_core.features.compute_features` up to the first decision's `last_seq` (fallback: all events); drop sessions with < 10 events and log how many; grouped split (`train`/`test`, ~70/30) by collector (humans) and by run batch (agents), deterministic seed; also a `split_variant` column marking one held-out agent variant (default `llm_headless`) for the held-out-variant experiment. Output `data/training_features.parquet` and, if `--to-bigquery`, the `training_features` table. Print a dataset summary table (sessions per label/variant/split).
3. `ml/train.py [--exclude-variant llm_headless] [--feature-set full|fingerprint|behaviour] [--upload gs://BUCKET/models/]` per §10.2. `model_meta.json` includes `version`, `feature_names`, `feature_set`, `trained_at`, train/test sizes, metrics, and per-feature human `median`/`p25`/`p75` from the train split. `--upload` writes `model.json`, `model_meta.json` and updates `latest.json` → `{ "model": "gs://.../<version>/model.json", "meta": "gs://.../<version>/model_meta.json" }`. Scorer loader must accept this pointer format (adjust scorer if needed).
4. `ml/bqml/train.sql` and `ml/bqml/evaluate.sql` per §10.3 (parameterised dataset name via a tiny `ml/run_bqml.py` that substitutes `${BQ_DATASET}` and runs them with the BigQuery client, then writes `ML.PREDICT` results for the test split to `data/bqml_predictions.parquet`).
5. `ml/benchmark.py` per §10.4 → `data/benchmark.json` (schema below), PNG charts in `data/charts/` (ROC, per-variant detection, early detection, feature importance), optional `--upload` to `gs://BUCKET/benchmark/benchmark.json` and `--to-bigquery`.

### benchmark.json schema (console D5 reads this)
```json
{
  "generated_at": "ISO-8601",
  "dataset": {"sessions": 0, "human": 0, "agent": 0, "by_variant": {"llm_headless": 0, "script_fill": 0}, "train": 0, "test": 0},
  "models": [
    {"name": "rules_baseline|xgb_fingerprint|xgb_behaviour|xgb_full|bqml_boosted_tree",
     "precision": 0.0, "recall": 0.0, "f1": 0.0, "roc_auc": 0.0, "human_fpr": 0.0,
     "detection_by_variant": {"script_fill": 0.0, "llm_headless": 0.0},
     "roc": {"fpr": [], "tpr": []}}
  ],
  "held_out_variant": {"variant": "llm_headless", "xgb_full_recall": 0.0, "xgb_fingerprint_recall": 0.0},
  "early_detection": {"seconds": [5, 10, 20, 30], "xgb_full_f1": [], "rules_baseline_f1": []},
  "latency_ms": {"p50": 0, "p95": 0, "n": 0},
  "top_features": [{"feature": "click_no_premove_ratio", "importance": 0.0}]
}
```
Commit `tests/fixtures/benchmark.sample.json` following this schema (D5 uses it).

## Acceptance criteria
- [ ] End-to-end on local data: `build_dataset → train → benchmark` runs with no manual edits and produces the JSON + charts.
- [ ] No session appears in both train and test (assert in code).
- [ ] Scorer loads the uploaded/locally saved model and `model_version` shows in decisions.
- [ ] BQML scripts are syntactically valid (`bq query --dry_run` instructions in `ml/README.md`).
- [ ] `ml/README.md` explains the exact command sequence for cloud and local.
