"""Migration runner: numbered .sql files, applied once, in order.

    python -m vibelive.migrate up        apply everything pending
    python -m vibelive.migrate status    show applied / pending
    python -m vibelive.migrate baseline  adopt an existing DB without re-running
    python -m vibelive.migrate new NAME  scaffold the next file

Deliberately not Alembic: there is no ORM here, so autogenerate has nothing to
diff against, and the existing hand-written schema.sql becomes 0001 verbatim
instead of being transcribed by hand.

Two properties that matter in a compose stack:

* **An advisory lock wraps the whole run.** `api` and `worker` start together;
  without the lock they would race to apply the same migration.
* **Checksums are recorded on apply.** Editing an already-applied file is an
  error rather than a silent no-op — which is exactly the trap the old
  docker-entrypoint-initdb.d setup had.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import asyncpg

from vibelive.config import get_settings

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"
ADVISORY_LOCK_KEY = 8571234
FILENAME_RE = re.compile(r"^(\d{4})_([a-z0-9_]+)\.sql$")

# Migrations that `baseline` marks as already-applied, because a pre-migration
# database was created by db/schema.sql + db/seeds.sql running via
# docker-entrypoint-initdb.d.
BASELINE_VERSIONS = ("0001", "0002")


@dataclass(frozen=True)
class Migration:
    version: str
    name: str
    path: Path

    @property
    def sql(self) -> str:
        return self.path.read_text(encoding="utf-8")

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.sql.encode("utf-8")).hexdigest()


def discover() -> list[Migration]:
    if not MIGRATIONS_DIR.is_dir():
        raise SystemExit(f"no migrations directory at {MIGRATIONS_DIR}")

    found: dict[str, Migration] = {}
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        m = FILENAME_RE.match(path.name)
        if not m:
            raise SystemExit(f"bad migration filename: {path.name} (want NNNN_lower_snake.sql)")
        version, name = m.group(1), m.group(2)
        if version in found:
            raise SystemExit(f"duplicate migration version {version}: {found[version].path.name} and {path.name}")
        found[version] = Migration(version=version, name=name, path=path)

    return [found[v] for v in sorted(found)]


async def ensure_table(conn: asyncpg.Connection) -> None:
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version     TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            checksum    TEXT NOT NULL,
            applied_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            duration_ms INTEGER
        )
        """
    )


async def applied_map(conn: asyncpg.Connection) -> dict[str, str]:
    rows = await conn.fetch("SELECT version, checksum FROM schema_migrations")
    return {r["version"]: r["checksum"] for r in rows}


def verify_checksums(migrations: list[Migration], applied: dict[str, str]) -> None:
    for m in migrations:
        recorded = applied.get(m.version)
        if recorded is not None and recorded != m.checksum:
            raise SystemExit(
                f"migration {m.version}_{m.name}.sql changed after it was applied.\n"
                f"  recorded sha256: {recorded}\n"
                f"  current  sha256: {m.checksum}\n"
                "Migrations are immutable — add a new one instead of editing this."
            )


async def cmd_up(conn: asyncpg.Connection) -> int:
    await ensure_table(conn)
    migrations = discover()

    await conn.execute("SELECT pg_advisory_lock($1)", ADVISORY_LOCK_KEY)
    try:
        applied = await applied_map(conn)
        verify_checksums(migrations, applied)

        pending = [m for m in migrations if m.version not in applied]
        if not pending:
            print(f"up to date ({len(applied)} applied)")
            return 0

        for m in pending:
            started = time.monotonic()
            async with conn.transaction():
                # No arguments -> simple protocol -> a whole multi-statement
                # file runs in one call. Adding an argument would break this.
                await conn.execute(m.sql)
                await conn.execute(
                    "INSERT INTO schema_migrations (version, name, checksum, duration_ms)"
                    " VALUES ($1, $2, $3, $4)",
                    m.version,
                    m.name,
                    m.checksum,
                    int((time.monotonic() - started) * 1000),
                )
            print(f"applied {m.version}_{m.name}  ({int((time.monotonic() - started) * 1000)}ms)")

        print(f"done ({len(pending)} applied)")
        return 0
    finally:
        await conn.execute("SELECT pg_advisory_unlock($1)", ADVISORY_LOCK_KEY)


async def cmd_status(conn: asyncpg.Connection) -> int:
    await ensure_table(conn)
    applied = await applied_map(conn)
    migrations = discover()
    for m in migrations:
        mark = "applied" if m.version in applied else "PENDING"
        drift = ""
        if m.version in applied and applied[m.version] != m.checksum:
            drift = "  <-- CHECKSUM MISMATCH"
        print(f"  [{mark:>7}] {m.version}_{m.name}{drift}")
    orphans = set(applied) - {m.version for m in migrations}
    for v in sorted(orphans):
        print(f"  [ orphan] {v} recorded in DB but no file on disk")
    return 0


async def cmd_baseline(conn: asyncpg.Connection) -> int:
    """Adopt a database created by the old docker-entrypoint-initdb.d path.

    Records 0001/0002 as applied WITHOUT executing them, so an existing volume
    with real data is picked up instead of being wiped and rebuilt.
    """
    await ensure_table(conn)
    if await conn.fetchval("SELECT count(*) FROM schema_migrations") > 0:
        print("already tracked — nothing to baseline")
        return 0

    exists = await conn.fetchval("SELECT to_regclass('public.human_activity') IS NOT NULL")
    if not exists:
        print("empty database — no baseline needed, just run: migrate up")
        return 0

    by_version = {m.version: m for m in discover()}
    async with conn.transaction():
        for version in BASELINE_VERSIONS:
            m = by_version.get(version)
            if m is None:
                raise SystemExit(f"cannot baseline: migration {version} missing from disk")
            await conn.execute(
                "INSERT INTO schema_migrations (version, name, checksum, duration_ms)"
                " VALUES ($1, $2, $3, 0)",
                m.version,
                m.name,
                m.checksum,
            )
            print(f"baselined {m.version}_{m.name} (not executed)")
    return 0


def cmd_new(name: str) -> int:
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    if not slug:
        raise SystemExit("give the migration a name")
    existing = discover()
    nxt = f"{(int(existing[-1].version) + 1) if existing else 1:04d}"
    path = MIGRATIONS_DIR / f"{nxt}_{slug}.sql"
    path.write_text(f"-- {nxt}_{slug}\n\n", encoding="utf-8")
    print(f"created {path}")
    return 0


async def _with_conn(fn) -> int:
    conn = await asyncpg.connect(get_settings().database_url)
    try:
        return await fn(conn)
    finally:
        await conn.close()


def main(argv: list[str] | None = None) -> int:
    args = (argv if argv is not None else sys.argv[1:]) or ["status"]
    cmd, rest = args[0], args[1:]

    if cmd == "new":
        return cmd_new(" ".join(rest))
    if cmd == "up":
        return asyncio.run(_with_conn(cmd_up))
    if cmd == "status":
        return asyncio.run(_with_conn(cmd_status))
    if cmd == "baseline":
        return asyncio.run(_with_conn(cmd_baseline))

    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
