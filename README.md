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

`api` waits for `migrate` to complete successfully, which waits for `db` to be
healthy — so a single `up` always lands on a fully migrated database.

- http://localhost:8000/health — liveness + DB reachability
- http://localhost:8000/explorer — read-only DB explorer
- http://localhost:8000/docs — OpenAPI

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

## Layout

```
migrations/          numbered SQL, applied in order, never edited after apply
vibelive/
  config.py          settings (env / .env)
  db.py              centralized asyncpg pool + query helpers
  migrate.py         migration runner
  api/
    main.py          FastAPI app + lifespan-owned pool
    routers/         health, explorer
    static/          explorer.html
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
