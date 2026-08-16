"""Liveness/readiness. Used by the compose healthcheck and the dashboard pill."""

from fastapi import APIRouter

from vibelive import __version__, db

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    """Always 200 so the API can report a degraded DB instead of vanishing."""
    db_ok = await db.healthcheck()
    return {
        "status": "ok" if db_ok else "degraded",
        "db": "ok" if db_ok else "unreachable",
        "version": __version__,
    }
