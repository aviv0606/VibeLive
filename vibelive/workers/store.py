"""Reference-data lookups and the one write path into human_activity.

Everything an ingest worker needs to turn a provider payload into rows, kept
out of the provider modules so adding a second provider does not mean copying
the insert.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from vibelive import db

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Observation:
    """One number, from one source, about one location, at one instant."""

    location_id: int
    category_id: int
    source_id: int
    category_name: str
    source_name: str
    metric: str
    unit: str | None
    value: float
    observed_at: datetime
    raw: dict

    @property
    def dedup_key(self) -> str:
        """`source:location:category:metric:observation_epoch` — see 0004.

        Keyed on the instant the *provider* observed, not on when we polled.
        That is the whole point: polling a 15-minute feed every 10 minutes
        re-reads the same observation, and storing it twice would inflate every
        average computed downstream with a sample that never happened.
        """
        epoch = int(self.observed_at.timestamp())
        return f"{self.source_name}:{self.location_id}:{self.category_name}:{self.metric}:{epoch}"


async def active_locations() -> list[dict]:
    return db.to_dicts(
        await db.fetch(
            "SELECT id, name, lat, lng FROM locations WHERE is_active ORDER BY id"
        )
    )


async def category_id(name: str) -> int | None:
    return await db.fetchval("SELECT id FROM categories WHERE name = $1", name)


async def active_source_id(name: str) -> int | None:
    """None when the source is missing or deactivated.

    `is_active` is the kill switch for an entire provider — a worker that finds
    its source inactive does nothing rather than ingesting anyway. That is what
    keeps the simulated_* sources deactivated in 0010 from being writable.
    """
    return await db.fetchval(
        "SELECT id FROM activity_sources WHERE name = $1 AND is_active", name
    )


async def insert_observations(observations: list[Observation]) -> int:
    """Insert readings, skipping ones already stored. Returns the new-row count.

    One statement via `unnest` rather than a loop: the batch is small but this
    is one round trip instead of N, and `execute` hands back the real inserted
    count, which is what distinguishes "the provider refreshed" from "we polled
    faster than the provider updates".
    """
    if not observations:
        return 0

    result = await db.execute(
        """
        INSERT INTO human_activity
            (location_id, category_id, source_id, metric, unit, value, observed_at, dedup_key, raw_json)
        SELECT * FROM unnest(
            $1::int[], $2::int[], $3::int[], $4::varchar[], $5::varchar[],
            $6::float8[], $7::timestamptz[], $8::text[], $9::jsonb[]
        )
        ON CONFLICT (dedup_key) WHERE dedup_key IS NOT NULL DO NOTHING
        """,
        [o.location_id for o in observations],
        [o.category_id for o in observations],
        [o.source_id for o in observations],
        [o.metric for o in observations],
        [o.unit for o in observations],
        [o.value for o in observations],
        [o.observed_at for o in observations],
        [o.dedup_key for o in observations],
        [o.raw for o in observations],
    )
    # asyncpg returns the command tag, e.g. "INSERT 0 17".
    try:
        return int(result.split()[-1])
    except (ValueError, IndexError):
        logger.warning("could not parse insert result %r", result)
        return 0
