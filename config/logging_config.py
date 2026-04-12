"""Logging configuration using loguru."""

import sys

from loguru import logger

from config.settings import settings


def setup_logging() -> None:
    logger.remove()

    # Stderr (coloreado) — DEBUG para ver comportamiento del modelo
    logger.add(
        sys.stderr,
        level="DEBUG",
        format="<green>{time:HH:mm:ss}</green> | <level>{level:<7}</level> | <cyan>{name}</cyan> — {message}",
    )

    # Archivo rotativo
    logger.add(
        str(settings.logs_dir / "jarvis.log"),
        level="DEBUG",
        rotation="10 MB",
        retention="30 days",
        compression="gz",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level:<7} | {name}:{function}:{line} — {message}",
    )
