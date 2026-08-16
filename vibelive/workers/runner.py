"""Worker process entrypoint: `python -m vibelive.workers`.

One process, one asyncpg pool, N supervised workers as sibling tasks. Separate
from the API process on purpose — a poll that wedges on a slow provider must
not be able to starve request handling.

Shutdown is explicit. `docker compose stop` sends SIGTERM, and without a
handler that becomes a 10-second wait and then SIGKILL mid-insert. Setting the
stop event lets every worker finish the cycle it is in, then exit.
"""

from __future__ import annotations

import asyncio
import logging
import signal

from vibelive import db
from vibelive.config import get_settings
from vibelive.logging_setup import setup_logging
from vibelive.workers.base import Worker, record, supervise
from vibelive.workers.open_meteo import AirQualityWorker, WeatherWorker

logger = logging.getLogger(__name__)


def build_workers() -> list[Worker]:
    """Instantiate the workers named in ENABLED_WORKERS, in that order."""
    settings = get_settings()
    registry = {
        "open_meteo_weather": lambda: WeatherWorker(settings.weather_interval_seconds),
        "open_meteo_pollution": lambda: AirQualityWorker(settings.pollution_interval_seconds),
    }

    workers: list[Worker] = []
    for name in settings.enabled_worker_list:
        factory = registry.get(name)
        if factory is None:
            raise SystemExit(
                f"unknown worker {name!r} in ENABLED_WORKERS. "
                f"Known: {', '.join(sorted(registry))}"
            )
        workers.append(factory())
    return workers


def _install_signal_handlers(stop: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()

    def request_stop() -> None:
        if not stop.is_set():
            logger.info("shutdown signal received — finishing current cycles")
            stop.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, request_stop)
        except NotImplementedError:
            # Windows: the event-loop API is POSIX-only, so fall back to the
            # threaded handler. Enough for local development; containers get
            # the real one.
            signal.signal(sig, lambda *_: request_stop())


async def main_async() -> int:
    settings = get_settings()
    setup_logging(settings.log_level)

    workers = build_workers()
    if not workers:
        logger.warning("ENABLED_WORKERS is empty — nothing to run")
        return 0

    await db.init_pool(max_size=settings.worker_pool_max)
    stop = asyncio.Event()
    _install_signal_handlers(stop)

    names = ", ".join(w.name for w in workers)
    logger.info("worker process up: %s", names)
    await record("runner", f"started with {len(workers)} workers: {names}", "INFO")

    try:
        await asyncio.gather(
            *(supervise(w, stop, max_backoff=settings.worker_max_backoff_seconds) for w in workers)
        )
    finally:
        await record("runner", "shutting down", "INFO")
        await db.close_pool()

    logger.info("worker process stopped")
    return 0


def main() -> int:
    try:
        return asyncio.run(main_async())
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
