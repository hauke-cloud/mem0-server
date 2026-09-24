"""Entry point: `mem0-server` / `python -m mem0_server`."""

from __future__ import annotations

import logging
import os

import uvicorn

from .app import create_app
from .config import Settings


def main() -> None:
    # mem0 reports usage to PostHog unless told otherwise. Set before mem0 is
    # imported (lazily, on the first request), since it reads this at import.
    os.environ.setdefault("MEM0_TELEMETRY", "false")

    settings = Settings.from_env()
    settings.validate()
    logging.basicConfig(level=settings.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
        proxy_headers=True,
        forwarded_allow_ips="*",
    )


if __name__ == "__main__":
    main()
