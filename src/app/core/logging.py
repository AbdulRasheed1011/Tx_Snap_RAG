from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"

def get_logger(name: str, log_dir: str = "artifacts/logs", level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(level)
    Path(log_dir).mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(LOG_FORMAT)

    sh = logging.StreamHandler()
    sh.setFormatter(formatter)
    logger.addHandler(sh)

    fh = RotatingFileHandler(Path(log_dir) / "app.log", maxBytes=2_000_000, backupCount=5)
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    logger.propagate = False
    return logger