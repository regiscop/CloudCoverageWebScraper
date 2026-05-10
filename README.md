# Solar Cloud Coverage Forecaster

Predicts solar production over the next 24–48 hours for Belgium and neighbouring countries by combining satellite cloud imagery (sat24.com) with NWP data from Open-Meteo.

**Geographic scope:** Belgium · Netherlands · Northern France · Luxembourg · Western Germany
**Forecast horizons:** H+1, H+3, H+6, H+12, H+24, H+48
**Execution mode:** 100% local on a single SPM B2B BE workstation — SQLite by default, no Postgres or Docker required. PostgreSQL/TimescaleDB and Docker remain available as optional advanced modes.

> 📖 **Full bilingual (FR/EN) usage guide:** see [`README.html`](README.html)
> 📊 **Project audit / summary:** see [`PROJECT_SUMMARY.html`](PROJECT_SUMMARY.html)

---

> **Docs:**
> [Architecture](docs/ARCHITECTURE.md) ·
> [Configuration](docs/CONFIGURATION.md) ·
> [Operations](docs/OPERATIONS.md) ·
> [API](docs/API.md) ·
> [Development](docs/DEVELOPMENT.md) ·
> [Strategy & planning](STRATEGY_AND_PLANNING.md)

## Architecture

```
Module 1 — Scraper      sat24 tile API  →  JPEG tiles + JSON metadata
Module 2 — Open-Meteo   NWP API         →  cloud cover, GHI, wind, temp
Module 3 — Storage      PostgreSQL/TimescaleDB (or Delta Lake)
Module 4 — Features     cloud index, optical flow, pvlib clear-sky, time encoding
Module 5 — Model        optical-flow baseline + XGBoost multi-horizon
Module 6 — Output       FastAPI REST endpoint
```

---

## Quick start (local mode — recommended)

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Copy environment file (defaults are local-first, no edits required)
cp .env.example .env

# 3. Create the local SQLite database
python main.py init-db

# 4. Backfill 90 days of NWP data
python main.py backfill

# 5. Run the all-in-one scheduler (scrape + features + forecast)
python main.py scheduler &

# 6. Start the local forecast API
python main.py serve
# → http://127.0.0.1:8000/docs

# 7. After a few days of data collection, train the model
python main.py train
```

For full bilingual instructions and screenshots, open [`README.html`](README.html) in a browser.

### Optional: PostgreSQL / TimescaleDB mode

```bash
psql -U <user> -d <db> -f db/schema.sql
# Then set DATABASE_URL=postgresql://… in .env
```

---

## CLI commands

| Command           | Description                                        |
|-------------------|----------------------------------------------------|
| `scrape`          | Blocking loop — fetch sat24 tiles every 15 min     |
| `scrape-once`     | Single scrape round (useful for testing/cron)      |
| `fetch-weather`   | Pull latest Open-Meteo forecasts into DB           |
| `backfill`        | Fetch last 90 days of NWP archive data             |
| `train`           | Train XGBoost models from collected features       |
| `serve`           | Start FastAPI server (default: port 8000)          |
| `init-db`         | Create tables via SQLAlchemy (non-TimescaleDB)     |
| `worker`          | Process pending images into cloud features          |
| `scheduler`       | Run the integrated APScheduler pipeline             |
| `tune`            | Optuna walk-forward hyperparameter search           |

---

## API endpoints

| Method | Path                         | Description                          |
|--------|------------------------------|--------------------------------------|
| GET    | `/zones`                     | List configured zones                |
| GET    | `/forecast/{zone}`           | Latest 48-h forecast for a zone      |
| GET    | `/forecast/{zone}/{horizon}` | Single horizon point (hours ahead)   |
| POST   | `/forecast/trigger`          | Trigger a fresh prediction run       |

Interactive docs: `http://localhost:8000/docs`

---

## Project structure

```
.
├── config.py                 # All runtime configuration
├── main.py                   # CLI entry point
├── requirements.txt
├── .env.example
├── scraper/
│   └── sat24_scraper.py      # Module 1 — tile fetcher
├── open_meteo/
│   └── fetcher.py            # Module 2 — NWP enrichment
├── db/
│   ├── schema.sql            # Module 3 — TimescaleDB DDL
│   ├── models.py             # SQLAlchemy ORM models
│   └── ingestion.py          # Read/write helpers
├── features/
│   └── image_processor.py   # Module 4 — cloud index, optical flow, pvlib
├── model/
│   └── trainer.py            # Module 5 — XGBoost trainer + evaluation
└── output/
    └── forecast_api.py       # Module 6 — FastAPI REST API
```

---

## ⚠️ Legal & technical notes

- The sat24.com tile API is **not a public documented API** (operated by Infoplaza).  
  Check sat24.com Terms of Service before commercial use.
- Rate limiting: **minimum 5 s between tile requests** (configurable via `SAT24_MIN_REQUEST_INTERVAL_S`).
- For commercial or high-volume use, prefer the official **Eumetsat SEVIRI/MSG API**.
- VIS imagery is unusable at night — the model falls back to IR + NWP for nocturnal horizons.
- Tile geo-referencing uses the SlippyMap/TMS convention — calibrate `TILES` in `config.py` for your exact area.

---

## Development phases (§9)

| Phase | Status   | Description                              |
|-------|----------|------------------------------------------|
| P1    | ✅ Done   | API exploration & URL validation         |
| P2    | ✅ Done   | Scraper MVP                              |
| P3    | ✅ Done   | DB schema & ingestion pipeline           |
| P4    | ✅ Done   | Open-Meteo collection & backfill         |
| P5    | ✅ Done   | Feature engineering                      |
| P6    | ✅ Done   | Optical flow baseline + XGBoost          |
| P7    | 🔜 Later  | ConvLSTM / hybrid NWP (needs 90d data)   |
| P8    | ✅ Done   | REST API output                          |
