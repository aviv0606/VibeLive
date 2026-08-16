"""Centralized asyncpg access: one pool per process, plus thin query helpers.

Both the FastAPI app and the worker runner import this module and call
`init_pool()` once during their own startup. Two processes means two pools;
that is intended.

Three asyncpg behaviours worth knowing before editing anything here:

* **Placeholders are ``$1``, ``$2`` — not ``%s``.** asyncpg speaks the native
  protocol, so psycopg-style placeholders are a syntax error.
* **JSONB decodes to ``str`` unless you register a codec.** `_init_connection`
  below does that, so `raw_json` and `event_data` arrive as dicts.
* **Multi-statement SQL only works without arguments.** ``conn.execute(text)``
  with no args uses the simple query protocol and happily runs a whole file;
  add even one argument and it switches to the extended protocol, which permits
  exactly one statement. The migration runner depends on the former.
"""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

import asyncpg

from vibelive.config import get_settings

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None
_lock = asyncio.Lock()


async def _init_connection(conn: asyncpg.Connection) -> None:
    """Runs for every new pooled connection. Teaches asyncpg to decode JSON."""
    for typename in ("json", "jsonb"):
        await conn.set_type_codec(
            typename,
            encoder=json.dumps,
            decoder=json.loads,
            schema="pg_catalog",
        )


async def init_pool(
    dsn: str | None = None,
    *,
    min_size: int = 1,
    max_size: int | None = None,
) -> asyncpg.Pool:
    """Create the process-wide pool. Safe to call more than once."""
    global _pool
    async with _lock:
        if _pool is not None:
            return _pool
        settings = get_settings()
        _pool = await asyncpg.create_pool(
            dsn=dsn or settings.database_url,
            min_size=min_size,
            max_size=max_size or settings.api_pool_max,
            command_timeout=settings.db_command_timeout,
            init=_init_connection,
        )
        logger.info(
            "db pool ready (min=%s max=%s)", min_size, max_size or settings.api_pool_max
        )
        return _pool


async def close_pool() -> None:
    global _pool
    async with _lock:
        if _pool is not None:
            await _pool.close()
            _pool = None
            logger.info("db pool closed")


def pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("db pool not initialized — call init_pool() at startup")
    return _pool


# --- query helpers -------------------------------------------------------

async def fetch(query: str, *args: Any, timeout: float | None = None) -> list[asyncpg.Record]:
    return await pool().fetch(query, *args, timeout=timeout)


async def fetchrow(query: str, *args: Any, timeout: float | None = None) -> asyncpg.Record | None:
    return await pool().fetchrow(query, *args, timeout=timeout)


async def fetchval(query: str, *args: Any, timeout: float | None = None) -> Any:
    return await pool().fetchval(query, *args, timeout=timeout)


async def execute(query: str, *args: Any, timeout: float | None = None) -> str:
    return await pool().execute(query, *args, timeout=timeout)


async def executemany(query: str, args_iter: Any, *, timeout: float | None = None) -> None:
    await pool().executemany(query, args_iter, timeout=timeout)


# --- scopes --------------------------------------------------------------

@asynccontextmanager
async def connection() -> AsyncIterator[asyncpg.Connection]:
    async with pool().acquire() as conn:
        yield conn


@asynccontextmanager
async def transaction() -> AsyncIterator[asyncpg.Connection]:
    """Everything inside commits together, or not at all."""
    async with pool().acquire() as conn, conn.transaction():
        yield conn


@asynccontextmanager
async def read_only_tx(statement_timeout_ms: int | None = None) -> AsyncIterator[asyncpg.Connection]:
    """A transaction Postgres itself refuses to let write.

    This is the explorer's write protection. `readonly=True` issues
    SET TRANSACTION READ ONLY, so a stray INSERT errors at the server rather
    than relying on the application to behave.
    """
    async with pool().acquire() as conn, conn.transaction(readonly=True):
        if statement_timeout_ms:
            await conn.execute(f"SET LOCAL statement_timeout = {int(statement_timeout_ms)}")
        yield conn


# --- misc ----------------------------------------------------------------

async def healthcheck(timeout: float = 2.0) -> bool:
    try:
        return await pool().fetchval("SELECT 1", timeout=timeout) == 1
    except Exception:
        logger.warning("db healthcheck failed", exc_info=True)
        return False


def to_dict(record: asyncpg.Record | None) -> dict[str, Any] | None:
    return dict(record) if record is not None else None


def to_dicts(records: list[asyncpg.Record]) -> list[dict[str, Any]]:
    return [dict(r) for r in records]
