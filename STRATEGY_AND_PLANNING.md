# Strategy and Planning — Solar Cloud Coverage Forecaster

_Last updated: 2026-05-09_

This document captures an audit of the current state of the project, the issues
found, and a prioritised action plan for improving reliability, correctness,
performance, and maintainability.

It is the working document for branch `claude/action-plan-improvements-uDKkQ`.

---

## 1. Current state (as audited)

The repository implements the full P1–P8 pipeline described in the README plus
improvements A–F (scheduler, feature worker, Optuna tuning, health endpoint,
nocturnal fallback). However, an end-to-end review reveals a **broken data
pipeline**, several **correctness bugs in the API**, a few **performance
foot-guns**, and the **complete absence of automated tests**.

### 1.1 Bugs found

| # | Severity | Location | Problem |
|---|----------|----------|---------|
| B1 | **Critical** | `scraper/sat24_scraper.py` | The scraper writes JPEGs and JSON sidecars to disk but never calls `ingest_satellite_metadata`. As a result, the `satellite_images` table is always empty, the feature worker finds nothing to process, training has no data, and the forecast endpoint returns 404 for every zone. The whole production pipeline is broken end-to-end. |
| B2 | High | `output/forecast_api.py:202` | `GET /forecast/{zone}/{horizon}` always returns the first point in the list, ignoring the requested `horizon_h`. |
| B3 | High | `db/ingestion.py:151` `load_latest_forecasts` | Orders by `valid_at DESC` and returns the last 48 rows without filtering on `produced_at`. After a few prediction runs, the API returns an inconsistent mix of forecast rows produced at different timestamps. |
| B4 | Medium | DB schema | No uniqueness constraint on `(captured_at, channel, tile_x1, tile_y1)`. Re-running the scraper at the same timestamp duplicates rows. |
| B5 | Medium | `features/pipeline_worker.py` | A new SQLAlchemy session is opened, used, and closed for **every single feature row** (one per zone per image). For 8 zones × 4 tiles × 2 channels per slot, that is 64 sessions per slot. |
| B6 | Medium | `db/ingestion.py:53` `ingest_weather_dataframe` | Iterates row-by-row with `df.iterrows()` and `session.add()` instead of using SQLAlchemy bulk insertion. |
| B7 | Low | `main.py:28` `_load_training_data` | `import pandas as pd` appears twice in the same function. |
| B8 | Low | `docker-compose.yml` | Postgres password (`solar_secret`) is hard-coded in the file checked into git. |
| B9 | Low | `requirements.txt` | Lists `schedule>=1.2`, but the codebase only uses `APScheduler`. |
| B10 | Low | `features/pipeline_worker.py:127` | `record.cloud_index = compute_cloud_index(img_path, (0, 0, 999, 999))["mean"]` uses an arbitrary "very large" bbox to mean "whole image". This is fragile (if a tile ever exceeds 999 px the bbox stops covering the whole image). |
| B11 | Low | `output/forecast_api.py` | The `/forecast/trigger` route uses `latest = cf_df.iloc[-1]` without distinguishing VIS from IR rows; `cloud_index` and `cloud_index_ir` come from the most recent row of either channel which is rarely both. |

### 1.2 Missing engineering practices

- **No automated tests.** No `tests/` directory, no `pytest` configuration, no
  CI. Every change is currently verified by hand.
- **No CI workflow** in `.github/workflows/`.
- **No structured logging or log rotation.**
- **No type-checking.** A quick `mypy` pass would surface several `None`
  unions that are silently ignored.
- **No README mention of the `/health`, scheduler, worker, and tune commands**
  even though the code supports them.

---

## 2. Action plan

The plan is sequenced for maximum return on effort: the broken pipeline is
fixed first so the rest of the stack can be exercised end-to-end.

### Phase A — Restore the data pipeline (this PR)

Goal: a single `python main.py scheduler` invocation must produce ingested
satellite metadata, derived cloud features, and forecast rows that the API
can serve.

| ID | Task | Files |
|----|------|-------|
| A1 | Persist tile metadata after every successful tile fetch (fixes B1) | `scraper/sat24_scraper.py`, `db/ingestion.py` |
| A2 | Make `/forecast/{zone}/{horizon}` return the requested horizon (fixes B2) | `output/forecast_api.py` |
| A3 | Filter `load_latest_forecasts` to a single `produced_at` run (fixes B3) | `db/ingestion.py` |
| A4 | Add a unique index on `(captured_at, channel, zoom_level, tile_x1, tile_y1)` and an idempotent insert helper (fixes B4) | `db/schema.sql`, `db/models.py`, `db/ingestion.py` |
| A5 | Reuse a single session in the feature worker; commit per image, not per row (fixes B5) | `features/pipeline_worker.py`, `db/ingestion.py` |
| A6 | Bulk-insert weather rows with `Session.bulk_insert_mappings` (fixes B6) | `db/ingestion.py` |
| A7 | Cleanups: remove duplicate import (B7), externalise Postgres password (B8), drop unused `schedule` dep (B9) | `main.py`, `docker-compose.yml`, `requirements.txt` |

### Phase B — Test coverage and CI (this PR)

| ID | Task | Files |
|----|------|-------|
| B1 | Add `tests/` directory with `pytest` configuration | `pyproject.toml` or `pytest.ini` |
| B2 | Unit-test pure functions: `build_timestamp`, `is_daytime`, `cyclical_time_features`, `extrapolate_cloud_motion`, `compute_cloud_index` | `tests/` |
| B3 | Unit-test the API horizon-selection logic | `tests/` |
| B4 | Unit-test the temporal split | `tests/` |

### Phase C — Quality of life (follow-up PRs)

These are tracked here for visibility but are out of scope for this branch.

- GitHub Actions workflow running `pytest` and `ruff check` on every push.
- Replace `print(metrics.to_string(...))` in `cmd_train` with structured
  logging.
- Add `alembic` migrations (the dependency is already declared but unused).
- Add Prometheus metrics (`scrape_age_seconds`, `weather_age_seconds`,
  `forecast_runs_total`) emitted from the scheduler and surfaced in `/health`.
- Replace pickle model serialisation with a versioned format (`xgboost`'s
  `.save_model` JSON) — pickle is not safe across `xgboost` upgrades.
- Add an `mlflow` or simple JSON registry to track model versions and metrics
  over time.

### Phase D — Modelling improvements (Phase 7 from the README)

- Implement the ConvLSTM hybrid model once 90 days of real data have been
  collected.
- Add residual-correction over the NWP baseline so the model only learns the
  delta, which is a much smaller target distribution.
- Investigate quantile regression (`xgboost`'s `quantile` objective) to emit
  proper P10 / P50 / P90 confidence intervals instead of the current ad-hoc
  `confidence = max(0.3, 1.0 - h / 48.0)`.

---

## 3. Acceptance criteria for this PR

- `pytest` runs from a clean checkout with no DB or network and passes.
- The scraper inserts a row into `satellite_images` for every tile it saves.
- `GET /forecast/{zone}/{horizon}` returns the requested horizon, not the
  first row.
- `load_latest_forecasts` returns rows from a single forecast run only.
- `requirements.txt` no longer lists `schedule`.
- `docker-compose.yml` reads the Postgres password from an environment
  variable.

---

## 4. Out of scope

- Any change to the deep-learning model (Phase 7).
- Any change to the geographic calibration of `TILES` or `ZONE_PIXEL_BBOXES`.
  These are placeholders and need real tile inspection to calibrate.
- Any change to the public REST contract beyond fixing the horizon-selection
  bug (B2).
