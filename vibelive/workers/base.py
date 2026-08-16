"""Worker framework: a scheduled coroutine with jitter, backoff, and a log trail.

A worker is one `run_once()` that does a unit of work and returns a one-line
summary. Everything else — when to run it, what to do when it throws, how to
stop it — is `supervise()`'s problem, so an ingest worker contains only the
logic specific to its provider.

Three behaviours worth knowing:

* **Startup jitter.** Every worker starts at the same instant in a compose
  stack. Without a random offset they would all fire together, every cycle,
  forever — a self-inflicted thundering herd against the provider and the pool.
* **Backoff is on consecutive failures only.** One success resets it. A
  provider outage therefore decays from `interval` toward `max_backoff`
  instead of hammering a dead endpoint every cycle.
* **Cadence is drift-corrected.** The next delay subtracts however long the run
  actually took, so a 10-minute worker stays on a 10-minute cadence rather than
  sliding to 10-minutes-plus-runtime.
"""

from __future__ import annotations

import asyncio
import logging
import random
from abc import ABC, abstractmethod

from vibelive import db

logger = logging.getLogger(__name__)

# Failure count past which the exponential term stops growing. 2**6 = 64x the
# interval, which max_backoff clamps long before it matters; the cap exists so
# a worker failing for a week cannot overflow the shift.
_MAX_EXPONENT = 6


class Worker(ABC):
    """One scheduled job. Subclasses implement `run_once`."""

    name: str = "worker"
    interval_seconds: float = 600.0

    @abstractmethod
    async def run_once(self) -> str:
        """Do one unit of work. Return a one-line summary for the log."""

    async def setup(self) -> None:
        """Called once before the first run."""

    async def teardown(self) -> None:
        """Called once after the loop exits, including on failure."""


async def record(worker_name: str, message: str, level: str = "INFO") -> None:
    """Append to worker_logs. Never raises — a log write must not kill a worker.

    The database is also the thing most likely to be down when there is
    something worth logging, so a failure here degrades to the stdout logger
    rather than propagating.
    """
    try:
        await db.execute(
            "INSERT INTO worker_logs (worker_name, message, level) VALUES ($1, $2, $3)",
            worker_name[:100],
            message[:4000],
            level[:20],
        )
    except Exception:
        logger.warning("could not write worker_logs for %s: %s", worker_name, message)


async def supervise(
    worker: Worker,
    stop: asyncio.Event,
    *,
    max_backoff: float = 900.0,
) -> None:
    """Run `worker` on its interval until `stop` is set."""
    loop = asyncio.get_running_loop()

    # Spread the fleet out before the first run rather than after it.
    jitter = random.uniform(0, min(worker.interval_seconds, 30.0))
    logger.info("%s starting in %.1fs (interval=%ss)", worker.name, jitter, worker.interval_seconds)
    if await _sleep_or_stop(stop, jitter):
        return

    try:
        await worker.setup()
    except Exception:
        logger.exception("%s setup failed", worker.name)
        await record(worker.name, "setup failed — worker not started", "ERROR")
        return

    failures = 0
    try:
        while not stop.is_set():
            started = loop.time()
            try:
                summary = await worker.run_once()
                elapsed = loop.time() - started
                failures = 0
                logger.info("%s ok in %.2fs: %s", worker.name, elapsed, summary)
                await record(worker.name, f"{summary} ({elapsed:.2f}s)", "INFO")
                # Hold the cadence: a run that took 40s waits interval-40s.
                delay = max(1.0, worker.interval_seconds - elapsed)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                failures += 1
                delay = min(max_backoff, worker.interval_seconds * (2 ** min(failures, _MAX_EXPONENT)))
                logger.exception("%s failed (%d consecutive)", worker.name, failures)
                await record(
                    worker.name,
                    f"{type(exc).__name__}: {exc} — retry in {delay:.0f}s "
                    f"({failures} consecutive failures)",
                    "ERROR",
                )

            if await _sleep_or_stop(stop, delay):
                return
    finally:
        try:
            await worker.teardown()
        except Exception:
            logger.exception("%s teardown failed", worker.name)


async def _sleep_or_stop(stop: asyncio.Event, seconds: float) -> bool:
    """Sleep, but wake immediately on shutdown. True means "stop was set"."""
    try:
        await asyncio.wait_for(stop.wait(), timeout=seconds)
        return True
    except asyncio.TimeoutError:
        return False
