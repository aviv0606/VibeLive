"""Read-only DB explorer.

Ported from the original sync-psycopg `backend/app.py`. Only mounted when
`settings.enable_explorer` is on, because `/api/explorer/query` runs arbitrary
SQL — a read-only transaction stops writes, but not a cartesian join that eats
the box. Localhost only.
"""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

import asyncpg
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from vibelive import db
from vibelive.config import get_settings

router = APIRouter(prefix="/api/explorer", tags=["explorer"])

ROW_LIMIT = 200


def jsonable(v: Any) -> Any:
    """Postgres types the JSON encoder doesn't handle natively."""
    if isinstance(v, datetime):
        return v.isoformat(sep=" ", timespec="seconds")
    if isinstance(v, (date, time)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (bytes, memoryview)):
        return f"<{len(bytes(v))} bytes>"
    if v is None or isinstance(v, (str, int, float, bool, dict, list)):
        return v
    return str(v)


def quote_ident(name: str) -> str:
    """Quote an identifier. Only ever called with a whitelisted table name."""
    return '"' + name.replace('"', '""') + '"'


def quote_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


async def table_names(conn: asyncpg.Connection) -> list[str]:
    rows = await conn.fetch(
        """
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
        ORDER BY table_name
        """
    )
    return [r["table_name"] for r in rows]


@router.get("/overview")
async def overview() -> dict:
    """Stat tiles + per-table row counts."""
    try:
        async with db.read_only_tx() as conn:
            names = await table_names(conn)

            counts: dict[str, int] = {}
            if names:
                # One round trip for every table's exact count.
                union = " UNION ALL ".join(
                    f"SELECT {quote_literal(n)} AS t, count(*) AS c FROM {quote_ident(n)}"
                    for n in names
                )
                counts = {r["t"]: r["c"] for r in await conn.fetch(union)}

            meta = await conn.fetchrow(
                "SELECT pg_size_pretty(pg_database_size(current_database())) AS size,"
                " current_database() AS dbname, version() AS version"
            )

        return {
            "connected": True,
            "database": meta["dbname"],
            "server": meta["version"].split(" on ")[0],
            "size": meta["size"],
            "tables": [{"name": n, "rows": counts.get(n, 0)} for n in names],
            "total_rows": sum(counts.values()),
        }
    except Exception as e:  # surfaced in the UI status pill
        return {"connected": False, "error": str(e), "tables": [], "total_rows": 0}


@router.get("/tables/{name}")
async def table_detail(name: str) -> dict:
    """Columns + a page of rows for one table."""
    async with db.read_only_tx() as conn:
        if name not in await table_names(conn):  # whitelist before interpolating
            raise HTTPException(404, f"no such table: {name}")

        columns = [
            {
                "name": r["column_name"],
                "type": r["data_type"],
                "nullable": r["is_nullable"] == "YES",
                "default": r["column_default"],
            }
            for r in await conn.fetch(
                """
                SELECT column_name, data_type, is_nullable, column_default
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = $1
                ORDER BY ordinal_position
                """,
                name,
            )
        ]

        rows = await conn.fetch(
            f"SELECT * FROM {quote_ident(name)} ORDER BY 1 LIMIT $1", ROW_LIMIT
        )

    fields = list(rows[0].keys()) if rows else [c["name"] for c in columns]
    return {
        "name": name,
        "columns": columns,
        "fields": fields,
        "rows": [[jsonable(v) for v in r.values()] for r in rows],
        "limit": ROW_LIMIT,
    }


class Query(BaseModel):
    sql: str


@router.post("/query")
async def run_query(q: Query) -> dict:
    """Ad-hoc SQL on a read-only transaction with a statement timeout."""
    settings = get_settings()
    try:
        async with db.read_only_tx(settings.explorer_statement_timeout_ms) as conn:
            stmt = await conn.prepare(q.sql)
            attrs = stmt.get_attributes()
            if not attrs:
                # No result set (DDL/DML). Execute anyway so the read-only
                # transaction gets its say and the user sees the real error.
                await stmt.fetch()
                return {
                    "fields": [],
                    "rows": [],
                    "message": "Statement returned no result set.",
                }
            # A cursor is the only way to cap rows — stmt.fetch(n) would bind
            # n as query parameter $1, not a row limit.
            cursor = await stmt.cursor()
            rows = await cursor.fetch(ROW_LIMIT)
            fields = [a.name for a in attrs]
    except Exception as e:
        raise HTTPException(400, str(e))

    return {
        "fields": fields,
        "rows": [[jsonable(v) for v in r.values()] for r in rows],
        "message": None,
    }
