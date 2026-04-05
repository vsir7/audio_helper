"""应用日志：文件滚动 + 控制台，便于跟踪 ASR / DeepSeek / 高德 各节点。"""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from config import settings

_BACKEND_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _BACKEND_DIR.parent

_LOG = logging.getLogger("audio_helper.logging_setup")


def setup_logging() -> None:
    """配置名为 audio_helper 及其子 logger 的输出。"""
    log_dir = Path(settings.log_dir)
    if not log_dir.is_absolute():
        log_dir = _PROJECT_ROOT / log_dir
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / settings.log_filename

    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    root = logging.getLogger("audio_helper")
    root.handlers.clear()
    root.setLevel(level)
    root.propagate = False

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    fh = RotatingFileHandler(
        log_path,
        maxBytes=settings.log_max_bytes,
        backupCount=settings.log_backup_count,
        encoding="utf-8",
    )
    fh.setLevel(level)
    fh.setFormatter(fmt)
    root.addHandler(fh)

    sh = logging.StreamHandler(sys.stderr)
    sh.setLevel(level)
    sh.setFormatter(fmt)
    root.addHandler(sh)

    _LOG.info("日志已初始化，文件: %s", log_path)
