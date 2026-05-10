# Operations

How to deploy, run, and troubleshoot the forecaster in production-ish
environments. For local dev, see [`DEVELOPMENT.md`](DEVELOPMENT.md).

---

## 1. Deployment options

### 1.1 docker-compose (recommended)

```bash
cp .env.example .env
# Edit .env — at minimum set POSTGRES_PASSWORD
docker compose up -d --build
```

This brings up three services:

- `db`     — TimescaleDB with `db/schema.sql` auto-applied at first boot.
- `scheduler` — runs `python main.py scheduler` (scrape, weather, worker, trigger).
- `api`    — runs `python main.py serve` on port 8000.

Volumes:

- `pgdata`  — Postgres datadir (persistent).
- `rawdata` — `/app/data/raw` (the JPEG tiles).
- `models`  — `/app/models` (the trained pickle/JSON model files).

### 1.2 Bare metal / venv

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# DB
psql -U solar -d solar_forecast -f db/schema.sql      # TimescaleDB
# OR
python main.py init-db                                # plain Postgres

# Backfill 90 days of NWP for training
python main.py backfill

# Run the integrated scheduler in one process
python main.py scheduler        # blocking

# Or run components separately, e.g. under systemd
python main.py scrape           # blocking scrape loop
python main.py worker           # one-shot feature pass (loop with cron/systemd)
python main.py serve            # FastAPI on $API_HOST:$API_PORT
```

---

## 2. First-run checklist

The full pipeline needs **>= a few hours of data** before the API can return
anything useful. The bootstrap order is:

1. **Init DB.** `psql -f db/schema.sql` (or `init-db`).
2. **Backfill weather.** `python main.py backfill` — populates 90 days of
   archive rows. Required for training.
3. **Start collecting tiles.** `python main.py scheduler` (or `scrape`).
   Wait at least one full day so optical flow has prior frames.
4. **Run the worker** (the scheduler will do this every 15 min).
   Confirm rows in `cloud_features`.
5. **Train.** `python main.py train`. Check the printed metrics; skill
   score should be >= 0 vs the NWP baseline once data is sufficient.
6. **Trigger forecasts.** Either wait for the hourly cron job or
   `curl -XPOST localhost:8000/forecast/trigger`.
7. **Sanity-check.** `curl localhost:8000/health` should report `"ok"`.

---

## 3. Health and monitoring

### 3.1 `/health`

Returns one of:

- `ok` — scrape < 30 min old AND weather < 90 min old AND model present.
- `degraded` — model present but at least one data freshness threshold breached.
- `unavailable` — no model OR no scrape data.

Sample response:

```json
{
  "status": "ok",
  "checked_at": "2026-05-09T14:31:02Z",
  "last_scrape_at": "2026-05-09T14:30:00Z",
  "scrape_age_minutes": 1.0,
  "last_weather_at": "2026-05-09T14:00:00Z",
  "weather_age_minutes": 31.0,
  "model_available": true,
  "model_version": "v1",
  "zones_with_recent_forecasts": ["brussels", "lille", "ghent", …]
}
```

Use it as a Docker healthcheck and a Kubernetes readiness probe. The compose
file already wires it as a healthcheck on the `api` service.

### 3.2 Logs

All modules use the standard `logging` module. The CLI configures level
`INFO` and a single-line format. For JSON logs in production, override
`logging.basicConfig` in your entry point or use a wrapping process manager
(e.g. `supervisord` with `stdout_logfile`).

### 3.3 What to alert on

- `health.status == "unavailable"` for > 5 min.
- `scrape_age_minutes > 30` for > 15 min.
- `weather_age_minutes > 90` for > 30 min.
- Repeated `Tile fetch failed` warnings for the same tile (sat24 issue).
- Disk usage on the `rawdata` volume — tiles accumulate quickly.

---

## 4. Data retention

Nothing is deleted automatically. Two strategies:

- **Keep 90 days raw, downsample older.** Compute features from raw tiles
  during the 90-day window, then drop the JPEGs but keep `cloud_features`
  rows.
- **TimescaleDB retention policies.** `add_retention_policy('satellite_images',
  INTERVAL '90 days')` on the hypertable. Pair with a cron that prunes
  matching files under `DATA_DIR`.

Both are out of scope for the current code; track in `STRATEGY_AND_PLANNING.md`.

---

## 5. Troubleshooting

### 5.1 `/forecast/{zone}` returns 404 with "No forecast available"

The trigger has not run successfully. Check, in order:

1. `/health` — does it say `unavailable`?
2. `python main.py train` — has a model been trained? `models/xgboost_v1.pkl`
   must exist.
3. Are there rows in `cloud_features`? If not, the worker has nothing to
   process — verify rows exist in `satellite_images` first.
4. Manually `curl -XPOST /forecast/trigger` and read the response.

### 5.2 Scraper logs "Tile fetch failed" repeatedly

- 4xx → check `SAT24_BASE_URL` and the tile coordinates in `config.TILES`.
- 5xx → Infoplaza is down; the loop will recover automatically.
- DNS errors → check the container's egress.

### 5.3 `IntegrityError` on satellite_images insert

Expected and harmless — the unique index is doing its job. The idempotent
helper `ingest_satellite_metadata` swallows the error and returns `False`.

### 5.4 Worker finds 0 unprocessed images

- Confirm the scraper is calling `ingest_satellite_metadata` (it should, post
  this PR — check `scraper/sat24_scraper.py`).
- `SELECT COUNT(*) FROM satellite_images WHERE processed = FALSE;`

### 5.5 Skill score is negative

The XGBoost model is worse than the NWP persistence baseline. Likely causes:

- Too little training data (need >= 30 days).
- `ZONE_PIXEL_BBOXES` is uncalibrated (the per-zone cloud index is noise).
- Tile geo-referencing in `TILES` does not match your zones.

Run `python main.py tune --horizon 1 --trials 100` to see if Optuna can
recover, but the underlying fix is calibration.

---

## 6. Backup

- **Postgres:** `pg_dump` the `solar_forecast` DB. The features and
  forecasts can be regenerated from raw tiles + Open-Meteo, but only within
  the 90-day archive window.
- **Tiles** (`DATA_DIR`): rsync to cold storage. Once gone, they cannot be
  recovered (sat24 only serves recent timestamps).
- **Models** (`models/`): re-trainable, but keep the last few versions for
  rollback.
