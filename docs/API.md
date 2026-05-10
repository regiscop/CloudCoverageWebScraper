# HTTP API reference

FastAPI app served by `python main.py serve`. Default base URL:
`http://localhost:8000`. Interactive Swagger docs at `/docs`,
ReDoc at `/redoc`, OpenAPI JSON at `/openapi.json`.

All timestamps are ISO-8601 UTC with explicit `Z` or `+00:00` offsets.
All responses are JSON.

---

## 1. `GET /health`

System health and data freshness. See [`OPERATIONS.md`](OPERATIONS.md#3-health-and-monitoring).

**Status codes:** 200 always.

**Response:** `HealthStatus`

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
  "zones_with_recent_forecasts": ["brussels", "lille"]
}
```

`status ∈ {"ok", "degraded", "unavailable"}`.

---

## 2. `GET /zones`

List of configured zone names (sorted).

```bash
curl http://localhost:8000/zones
```

```json
["amsterdam", "brussels", "cologne", "ghent",
 "lille", "liege", "luxembourg", "paris_nord"]
```

---

## 3. `GET /forecast/{zone}`

Latest forecast run for `zone`, ordered chronologically by `valid_at`.
Returns up to 48 points covering H+1 … H+48.

**Path params:**
- `zone` — one of `/zones`. Returns 404 if unknown.

**Status codes:**
- 200 — forecast available.
- 404 — unknown zone, or no forecast has been triggered yet.

**Response:** `ZoneForecast`

```json
{
  "produced_at": "2026-05-09T14:05:00Z",
  "zone": "brussels",
  "forecast": [
    {
      "valid_at": "2026-05-09T15:00:00Z",
      "cloud_cover": 0.42,
      "ghi_w_m2": 320.5,
      "confidence": 0.98
    },
    {
      "valid_at": "2026-05-09T17:00:00Z",
      "cloud_cover": 0.51,
      "ghi_w_m2": 245.0,
      "confidence": 0.94
    }
  ]
}
```

**Field semantics:**

| Field | Type | Range / unit | Notes |
|-------|------|--------------|-------|
| `produced_at` | ISO-8601 UTC | — | When the inference run was kicked off. All points in `forecast` come from this single run. |
| `valid_at` | ISO-8601 UTC | — | Target time of the prediction. |
| `cloud_cover` | float | `[0.0, 1.0]` | Predicted cloud index. **Not** the same scale as Open-Meteo's `cloud_cover` (which is `[0, 100]` %). |
| `ghi_w_m2` | float \| null | W/m² | Predicted global horizontal irradiance, derived as `ghi_clearsky × (1 − 0.75 × cloud_cover)`. |
| `confidence` | float \| null | `[0, 1]` | Heuristic; decays linearly with horizon (`max(0.3, 1 − h/48)`). Treat as advisory until quantile regression lands. |

---

## 4. `GET /forecast/{zone}/{horizon_h}`

Single forecast point for the requested lead time.

**Path params:**
- `zone` — see above.
- `horizon_h` — integer hours. Must be one of `FORECAST_HORIZONS_H`
  (default `[1, 3, 6, 12, 24, 48]`).

**Status codes:**
- 200 — forecast available.
- 400 — unsupported horizon.
- 404 — unknown zone or no forecast available.

**Response:** `ForecastPoint` (same shape as one element of `ZoneForecast.forecast`).

```bash
curl http://localhost:8000/forecast/brussels/24
```

```json
{
  "valid_at": "2026-05-10T14:00:00Z",
  "cloud_cover": 0.62,
  "ghi_w_m2": 180.3,
  "confidence": 0.5
}
```

The endpoint returns the point whose `valid_at` is **closest to**
`produced_at + horizon_h` from the latest run, so a slightly off-grid
inference time still resolves cleanly.

---

## 5. `POST /forecast/trigger`

Run a fresh inference pass over every configured zone using the latest
features and weather. Persists rows into `solar_forecasts`. Idempotent in
the sense that a new `produced_at` is created on every call — older runs
remain in the DB but are ignored by the read endpoints.

**Body:** none.

**Status codes:**
- 200 — at least one zone updated.
- 503 — no trained model on disk (`models/xgboost_v1.pkl`).

**Response:** `TriggerResponse`

```json
{
  "status": "ok",
  "zones_updated": ["brussels", "ghent", "lille"],
  "produced_at": "2026-05-09T14:05:00Z"
}
```

Zones with no recent cloud features are silently skipped (logged on the
server side).

> **Note:** This endpoint is currently **unauthenticated** and runs an
> O(zones × horizons) inference loop. Put it behind a private network or an
> auth proxy in production. Adding rate-limit + auth is tracked as a
> follow-up in `STRATEGY_AND_PLANNING.md`.

---

## 6. Error format

FastAPI default. Errors look like:

```json
{ "detail": "Zone 'tokyo' not found. Available: ['amsterdam', 'brussels', …]" }
```

Validation errors (e.g. non-integer `horizon_h`) follow the standard FastAPI
422 format with a `detail` array.

---

## 7. Versioning

`app.version = "0.1.0"` and the OpenAPI schema is the contract. Backwards-
incompatible changes will bump the minor version pre-1.0 and the major
version after.
