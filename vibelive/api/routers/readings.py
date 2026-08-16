"""Read endpoints over the observation record.

Deliberately read-only and deliberately honest: a category with no source
returns an empty series and says which source it is waiting for, rather than
being omitted from the response. A caller that renders only what it receives
would otherwise show four healthy categories and quietly drop the two that have
no data — which is exactly the impression the project is trying not to give.

The heavy lifting stays in SQL; grouping into series happens here because the
volume is small by construction (one location over 24h is roughly 950 rows) and
a round trip per metric would not be.
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from vibelive import db

router = APIRouter(prefix="/api", tags=["readings"])

logger = logging.getLogger(__name__)

DEFAULT_HOURS = 24
MAX_HOURS = 168  # a week; beyond this the response stops being sparkline-sized


@router.get("/locations")
async def locations() -> list[dict]:
    """Active locations, in a stable order."""
    return db.to_dicts(
        await db.fetch(
            """
            SELECT id, name, lat, lng, radius_m, nearest_town
            FROM locations
            WHERE is_active
            ORDER BY id
            """
        )
    )


@router.get("/coverage")
async def coverage(
    hours: int = Query(DEFAULT_HOURS, ge=1, le=MAX_HOURS),
) -> list[dict]:
    """Every category, including the ones with nothing in them.

    `live` is computed from whether observations actually arrived in the
    window, not from configuration. A worker that is enabled but failing
    reports as not live, which is the useful reading of the word.
    """
    rows = await db.fetch(
        """
        SELECT
            c.id,
            c.name,
            c.description,
            count(h.id)                                   AS samples,
            count(DISTINCT h.metric)                      AS metrics,
            max(h.observed_at)                            AS latest,
            array_remove(array_agg(DISTINCT s.name), NULL) AS sources
        FROM categories c
        LEFT JOIN human_activity h
               ON h.category_id = c.id
              AND h.observed_at >= now() - make_interval(hours => $1)
        LEFT JOIN activity_sources s ON s.id = h.source_id
        GROUP BY c.id, c.name, c.description
        ORDER BY c.name
        """,
        hours,
    )

    out = []
    for r in rows:
        out.append(
            {
                "category": r["name"],
                "description": r["description"],
                "samples": r["samples"],
                "metrics": r["metrics"],
                "latest": r["latest"].isoformat() if r["latest"] else None,
                "sources": list(r["sources"]),
                "live": r["samples"] > 0,
            }
        )
    return out


@router.get("/readings")
async def readings(
    location_id: int,
    hours: int = Query(DEFAULT_HOURS, ge=1, le=MAX_HOURS),
) -> dict:
    """Every metric for one location over a window: latest, change, and series.

    One call returns what a dashboard needs to draw a full screen — the card
    values and the sparkline behind each of them — because splitting them would
    mean one request per metric and fifteen metrics per location.
    """
    location = await db.fetchrow(
        "SELECT id, name, lat, lng, nearest_town FROM locations WHERE id = $1",
        location_id,
    )
    if location is None:
        raise HTTPException(404, f"no such location: {location_id}")

    rows = await db.fetch(
        """
        SELECT
            c.name AS category,
            h.metric,
            h.unit,
            h.value,
            h.observed_at,
            s.name AS source,
            h.raw_json
        FROM human_activity h
        JOIN categories c        ON c.id = h.category_id
        LEFT JOIN activity_sources s ON s.id = h.source_id
        WHERE h.location_id = $1
          AND h.observed_at >= now() - make_interval(hours => $2)
        ORDER BY c.name, h.metric, h.observed_at
        """,
        location_id,
        hours,
    )

    # Rows arrive already ordered by (category, metric, observed_at), so a
    # single pass builds every series in order without sorting again.
    series: "OrderedDict[tuple[str, str], dict[str, Any]]" = OrderedDict()
    for r in rows:
        key = (r["category"], r["metric"])
        entry = series.get(key)
        if entry is None:
            entry = {
                "category": r["category"],
                "metric": r["metric"],
                "unit": r["unit"],
                "source": r["source"],
                "points": [],
            }
            raw = r["raw_json"] or {}
            # Which model grid cell answered. Two locations sharing this are
            # not independent observations, and the UI says so.
            if raw.get("grid_lat") is not None:
                entry["grid"] = {"lat": raw.get("grid_lat"), "lng": raw.get("grid_lng")}
            series[key] = entry
        entry["points"].append([r["observed_at"].isoformat(), r["value"]])

    metrics = []
    for entry in series.values():
        points = entry["points"]
        first_value = points[0][1]
        last_value = points[-1][1]
        delta = last_value - first_value

        # Percent change is only meaningful against a non-zero baseline, and
        # several of these metrics legitimately sit at zero (precipitation).
        delta_pct = (delta / abs(first_value) * 100) if first_value else None

        metrics.append(
            {
                **entry,
                "latest": last_value,
                "latest_at": points[-1][0],
                "first": first_value,
                "first_at": points[0][0],
                "delta": delta,
                "delta_pct": delta_pct,
                "samples": len(points),
            }
        )

    return {
        "location": db.to_dict(location),
        "hours": hours,
        "metrics": metrics,
        "generated_at": (await db.fetchval("SELECT now()")).isoformat(),
    }
