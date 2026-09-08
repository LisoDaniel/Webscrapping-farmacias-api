import logging
import sys
from rich.logging import RichHandler


def setup_logger(name: str = "webscrapping") -> logging.Logger:
    """Configura e retorna um logger formatado com Rich."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        handler = RichHandler(
            rich_tracebacks=True,
            show_time=True,
            show_path=False
        )
        formatter = logging.Formatter("%(message)s")
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    return logger


logger = setup_logger()
