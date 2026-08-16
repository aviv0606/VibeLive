"""FastAPI application. Owns one asyncpg pool for its process lifetime."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse

from vibelive import __version__, db
from vibelive.api.routers import explorer, health
from vibelive.config import get_settings
from vibelive.logging_setup import setup_logging

STATIC = Path(__file__).parent / "static"
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_logging(settings.log_level)
    await db.init_pool(max_size=settings.api_pool_max)
    logger.info("api ready (explorer=%s)", settings.enable_explorer)
    yield
    await db.close_pool()


settings = get_settings()

app = FastAPI(title="VibeLive", version=__version__, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)

if settings.enable_explorer:
    app.include_router(explorer.router)

    @app.get("/explorer", response_class=HTMLResponse, include_in_schema=False)
    async def explorer_page() -> str:
        return (STATIC / "explorer.html").read_text(encoding="utf-8")


@app.get("/", include_in_schema=False)
async def index():
    """Replaced by the operator dashboard in phase 4."""
    return RedirectResponse("/explorer" if settings.enable_explorer else "/docs")
