# Architecture

This document describes the runtime architecture of the Solar Cloud Coverage
Forecaster. For a step-by-step setup see [`OPERATIONS.md`](OPERATIONS.md); for
public HTTP contract see [`API.md`](API.md).

---

## 1. Data flow

```
   ┌───────────────┐                          ┌───────────────┐
   │   sat24.com   │                          │  Open-Meteo   │
   │  tile API     │                          │  forecast +   │
   │  (Infoplaza)  │                          │  archive APIs │
   └──────┬────────┘                          └───────┬───────┘
          │ JPEG tiles                                │ JSON
          │ every 15 min                              │ every 60 min
          ▼                                           ▼
   ┌─────────────────────┐                 ┌─────────────────────┐
   │  scraper.sat24      │                 │  open_meteo.fetcher │
   │  • rate-limited GET │                 │  • cached + retry   │
   │  • night-time skip  │                 │  • per grid point   │
   │  • saves to DATA_DIR│                 │                     │
   │  • inserts metadata │                 │                     │
   └────────┬────────────┘                 └─────────┬───────────┘
            │                                        │
            ▼                                        ▼
   ┌──────────────────────────────────────────────────────────────┐
   │             PostgreSQL + TimescaleDB hypertables             │
   │ satellite_images · cloud_features · weather_data · forecasts │
   └────────┬───────────────────────────────────────────┬─────────┘
            │ unprocessed                               │
            ▼                                           │
   ┌─────────────────────┐                              │
   │ features.pipeline_  │                              │
   │ worker              │  cloud index, std,           │
   │ • per-zone bbox     │  optical flow                │
   │ • Farneback flow    │                              │
   └────────┬────────────┘                              │
            │                                           │
            ▼                                           │
   ┌────────────────────────────────────────────────────┴────────┐
   │  model.trainer (offline) → models/xgboost_v1.pkl            │
   │  • multi-horizon XGBoost (H+1 … H+48)                       │
   │  • Optuna walk-forward tuning                               │
   └────────┬────────────────────────────────────────────────────┘
            │ inference
            ▼
   ┌─────────────────────┐         ┌─────────────────────────┐
   │ output.forecast_api │ ───────▶│  REST clients / Grafana │
   │  (FastAPI)          │         │                         │
   └─────────────────────┘         └─────────────────────────┘
```

All recurring jobs (scrape, weather fetch, feature worker, forecast trigger)
are coordinated by `scheduler.pipeline` via APScheduler.

---

## 2. Module responsibilities

| Path | Responsibility | Key entry points |
|------|---------------|------------------|
| `config.py` | Single source of truth for runtime config: tile coverage, zones, env-driven settings. | `GRID_POINTS`, `TILES`, `OPEN_METEO_VARIABLES`, `FORECAST_HORIZONS_H` |
| `scraper/sat24_scraper.py` | Rate-limited fetch of sat24 tiles. Skips VIS at night via `pvlib`. Saves JPEG + JSON sidecar to `DATA_DIR` and persists DB metadata. | `scrape_once`, `scrape_loop` |
| `open_meteo/fetcher.py` | NWP fetch (forecast + 90-day backfill). Cached + auto-retried HTTP session. | `fetch_all_forecasts`, `backfill_90_days` |
| `db/models.py` | SQLAlchemy ORM. Mirror of `db/schema.sql`. | `SatelliteImage`, `CloudFeature`, `WeatherData`, `SolarForecast` |
| `db/ingestion.py` | DB read/write helpers, idempotent inserts, bulk inserts. | `ingest_satellite_metadata`, `ingest_weather_dataframe`, `ingest_cloud_features_bulk`, `load_latest_forecasts` |
| `features/image_processor.py` | Pure image-feature primitives (cloud index, optical flow, solar geometry, time encoding). | `compute_cloud_index`, `compute_optical_flow`, `solar_position_features`, `cyclical_time_features` |
| `features/pipeline_worker.py` | Batch worker: turns unprocessed `satellite_images` into `cloud_features` rows. | `process_pending_images` |
| `model/trainer.py` | Multi-horizon XGBoost training, evaluation against an NWP-persistence baseline, Optuna walk-forward tuning. | `run_training_pipeline`, `run_optuna_tuning`, `extrapolate_cloud_motion` |
| `output/forecast_api.py` | FastAPI app. Serves stored forecasts, triggers inference, exposes `/health`. | `app`, `trigger_forecast`, `health_check` |
| `scheduler/pipeline.py` | APScheduler glue running scrape/fetch/worker/trigger on UTC cron+interval triggers. | `start_scheduler` |
| `main.py` | CLI router. One sub-command per top-level action. | `main` |

---

## 3. Storage layout

### 3.1 Filesystem (`DATA_DIR`, default `data/raw/`)

```
data/raw/
  visible/
    202605091430/
      z5_16_10.jpg
      z5_16_10.json    # metadata sidecar (ts, channel, tile coords, saved_at)
      z5_17_10.jpg
      z5_17_10.json
      …
  infrared/
    202605091430/
      …
```

Files on disk are the **source of truth**. If the DB is wiped, a re-ingestion
pass over `DATA_DIR` rebuilds `satellite_images` (the unique index makes the
operation idempotent).

### 3.2 Database (TimescaleDB)

Four hypertables, all partitioned on `captured_at` (or `produced_at` for
`solar_forecasts`):

- `satellite_images` — one row per fetched tile.
  Unique index `(captured_at, channel, zoom_level, tile_x1, tile_y1)`
  prevents duplicates on retry.
- `cloud_features` — one row per zone per image.
- `weather_data` — one row per zone per hour, tagged `source = forecast | archive`.
- `solar_forecasts` — one row per (zone, horizon) per inference run.
  `produced_at` identifies the run; `valid_at` is the target time.

The full DDL is in [`db/schema.sql`](../db/schema.sql).

---

## 4. Time discipline

- **All timestamps are UTC** end-to-end. The scrape timestamp is floored to
  the nearest 15-minute slot via `floor_to_slot` so that re-runs and the
  unique index agree on the same key.
- **Temporal split, never random shuffle.** The trainer reserves the last
  `test_days` of data for test, the preceding `val_days` for validation. The
  Optuna tuner does walk-forward CV with `n_folds` consecutive windows.
- **Schedule alignment** — APScheduler uses `IntervalTrigger` for the scrape
  and feature worker (every `SCRAPE_INTERVAL_MINUTES`) and `CronTrigger` for
  the hourly weather fetch (minute 0) and forecast trigger (minute 5, after
  weather lands).

---

## 5. Failure model

| Failure | Behaviour |
|--------|-----------|
| sat24 tile 4xx/5xx | `fetch_tile` logs and returns `None`. Scrape round continues with the next tile. |
| DB outage during scrape | Files are still written to `DATA_DIR`. The metadata insert raises and is logged but does not stop the loop. Re-running the worker after recovery re-ingests. |
| Open-Meteo outage | `retry_requests` retries 5× with backoff. Persistent failure surfaces as an exception in the scheduler's `job_fetch_weather`, which catches and logs. |
| No model file | `/forecast/trigger` returns 503. Scheduler skips the trigger job with a warning. |
| Re-run at the same 15-min slot | Idempotent insert skips the duplicate (B4 fix). |
| Race between two schedulers | The unique index ensures only one row wins; the other gets `IntegrityError` and is treated as a no-op. |

---

## 6. Public surface

The only stable public surface is the HTTP API in
[`output/forecast_api.py`](../output/forecast_api.py); see [`API.md`](API.md)
for the full contract. Everything else (DB schema, file layout, CLI flags) is
considered an implementation detail.
