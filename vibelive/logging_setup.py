"""Stdlib logging config, shared by the API and the worker runner."""

import logging
import sys


def setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)-7s %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # asyncpg logs every acquire at DEBUG; keep it quiet unless we ask.
    logging.getLogger("asyncpg").setLevel(logging.WARNING)
