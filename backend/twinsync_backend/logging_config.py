from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path


def default_log_dir() -> Path:
    configured = os.environ.get("TWINSYNC_LOG_DIR")
    if configured:
        return Path(configured)
    if os.name == "nt":
        root = os.environ.get("LOCALAPPDATA")
        if root:
            return Path(root) / "TwinSyncAudio" / "logs"
    return Path.cwd() / "logs"


def configure_logging() -> Path:
    log_dir = default_log_dir()
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        log_dir = Path.cwd() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "twinsync-backend.log"
    handler = RotatingFileHandler(log_path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s", handlers=[handler])
    return log_path
