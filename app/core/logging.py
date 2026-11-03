import logging

from app.core.config import settings


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO if settings.is_prod else logging.DEBUG,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # Keep third-party noise down.
    logging.getLogger("httpx").setLevel(logging.WARNING)
