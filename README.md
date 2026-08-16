# VibeLive

Real-time urban activity intelligence: ingest external signals (traffic, crowd,
noise, weather, pollution), normalize into PostgreSQL, analyze trends, summarize
with AI, expose insights over REST.

## Running

```bash
docker compose up -d --build
```

| Service | Role | URL |
|---|---|---|
| `db` | Postgres 15 | `localhost:5432` |
| `migrate` | Applies pending migrations, then exits | — |
| `api` | FastAPI backend | http://localhost:8000 |
| `worker` | Polls providers, writes observations | — |

`api` and `worker` both wait for `migrate` to complete successfully, which waits
for `db` to be healthy — so a single `up` always lands on a fully migrated
database.

- http://localhost:8000/ — operator dashboard
- http://localhost:8000/health — liveness + DB reachability
- http://localhost:8000/explorer — read-only DB explorer
- http://localhost:8000/docs — OpenAPI

## Read API

| Endpoint | Returns |
|---|---|
| `GET /api/locations` | Active locations |
| `GET /api/coverage?hours=` | Every category, including empty ones. `live` is computed from observations that actually arrived, not from config — an enabled-but-failing worker reads as not live |
| `GET /api/readings?location_id=&hours=` | Every metric for one location: latest, change over the window, and the full series for sparklines |

`/api/readings` answers a whole dashboard in one call, because splitting it
would mean one request per metric and fifteen metrics per location. `hours` is
capped at 168.

The dashboard renders change over the span **actually covered by the data**,
not the window requested — with 30 minutes of history a "24h" window holds one
hour of observations, and labelling that change "over 24h" would overstate it.

Connection string: `postgresql://vibelive:secret@localhost:5432/vibelive`

## Migrations

Schema lives **only** in `migrations/`. There is no `schema.sql` and no
`docker-entrypoint-initdb.d` — that path silently ignored edits once the data
directory existed.

```bash
docker compose run --rm migrate python -m vibelive.migrate status
docker compose run --rm migrate python -m vibelive.migrate up
docker compose run --rm migrate python -m vibelive.migrate new add_something
```

Rules the runner enforces:

- **Migrations are immutable.** Each file's sha256 is recorded when applied;
  editing an applied file makes the next `up` fail loudly instead of silently
  doing nothing.
- **One migrator at a time.** A Postgres advisory lock wraps the run, so
  concurrent containers can't double-apply.
- `baseline` adopts a pre-migration database by recording `0001`/`0002` as
  applied without executing them.

Full reset (destroys all data):

```bash
docker compose down -v && docker compose up -d --build
```

## Data sources

Every number in the database is a real measurement. Nothing is generated.

| Category | Source | Status |
|---|---|---|
| `weather` | Open-Meteo Forecast | **Live** — temp, feels-like, humidity, precip, cloud, wind, gusts, pressure |
| `pollution` | Open-Meteo Air Quality | **Live** — European AQI, PM2.5, PM10, NO₂, SO₂, O₃, CO |
| `traffic` | TomTom | Not wired — needs a free API key |
| `crowd` | — | **Empty.** No free source exists |
| `noise` | — | **Empty.** No free source exists |

Open-Meteo needs no API key and no account. `crowd` and `noise` stay empty
rather than being filled with synthetic data that would be indistinguishable
from real data three weeks from now. The `simulated_*` sources from `0009` are
deactivated in `0010` for that reason; `is_active = false` means no worker can
write through them.

### What this data honestly is

- **Open-Meteo is a model on a ~1–11 km grid, not a sensor at your coordinate.**
  The response echoes the grid point it snapped to, and it goes into
  `raw_json.grid_lat` / `grid_lng`. All three seeded Yehud locations snap to the
  same cell (32.0625, 34.875) and return identical values — real measurements,
  but not independent per-location observations. Only `pressure_hpa` differs,
  because it is elevation-adjusted.
- **Air quality refreshes hourly upstream, weather roughly every 15 minutes.**
  Intervals match those cadences. Polling faster returns the same observation,
  which `dedup_key` discards — so a short pollution window will often hold one
  sample or none.
- **There is no backfill.** These endpoints serve current conditions only, so
  history exists only for the time the worker has been running. Downtime is a
  permanent hole. Take dumps.
- **The free tier is non-commercial** (CC-BY-4.0). Commercial use needs a paid
  plan, or switching to the `openweather` source, which `0010` left in place and
  inactive for exactly that.

## Workers

```bash
docker compose logs -f worker
docker compose exec db psql -U vibelive -d vibelive -c \
  "SELECT worker_name, level, message, created_at FROM worker_logs ORDER BY id DESC LIMIT 20;"
```

`ENABLED_WORKERS` selects which run; empty disables ingestion. Each worker gets
startup jitter, exponential backoff on consecutive failures (reset by one
success), and a drift-corrected interval. SIGTERM lets the current cycle finish.

## Layout

```
migrations/          numbered SQL, applied in order, never edited after apply
vibelive/
  config.py          settings (env / .env)
  db.py              centralized asyncpg pool + query helpers
  migrate.py         migration runner
  api/
    main.py          FastAPI app + lifespan-owned pool
    routers/         health, readings, explorer
    static/          dashboard.html, explorer.html
  workers/
    __main__.py      `python -m vibelive.workers`
    base.py          Worker ABC, scheduling, backoff, worker_logs
    runner.py        process entrypoint, registry, signal handling
    store.py         reference lookups + the one write path
    open_meteo.py    weather + air quality ingest
```

## Local development

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt          # Windows
.venv/Scripts/python -m uvicorn vibelive.api.main:app --reload
```

Copy `.env.example` to `.env` to override anything.

## Notes

- `ENABLE_EXPLORER` gates `/explorer` and `/api/explorer/*`. The query endpoint
  runs arbitrary SQL against a read-only transaction with a statement timeout —
  fine on localhost, **set it false before exposing this host**.
- Postgres data lives in the `pgdata` named volume, not a bind mount. Use
  `pg_dump` for portability.
