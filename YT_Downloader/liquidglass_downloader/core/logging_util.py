from __future__ import annotations
import logging, sys
from logging.handlers import RotatingFileHandler
from .config import CONFIG

def get_logger(name: str = "liquidglass") -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    handler = RotatingFileHandler(CONFIG.log_dir / "app.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    fmt = logging.Formatter("[%(asctime)s] %(levelname)s %(name)s: %(message)s")
    handler.setFormatter(fmt)
    logger.addHandler(handler)
    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(fmt)
    logger.addHandler(stream)
    return logger
