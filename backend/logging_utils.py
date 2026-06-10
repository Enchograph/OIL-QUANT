from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from threading import RLock


DEFAULT_LOG_DIR = Path(__file__).resolve().parent / "data" / "logs"
_LOGGER_NAMES = ("backend", "backend.tasks", "api.access", "api.error", "werkzeug")


class DailyLogFileHandler(logging.Handler):
    def __init__(self, log_dir: Path) -> None:
        super().__init__()
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._current_date = ""
        self._stream = None
        self._lock = RLock()

    def emit(self, record: logging.LogRecord) -> None:
        message = self.format(record)
        with self._lock:
            stream = self._get_stream_for_today()
            stream.write(f"{message}\n")
            stream.flush()

    def close(self) -> None:
        with self._lock:
            if self._stream is not None:
                self._stream.close()
                self._stream = None
        super().close()

    def _get_stream_for_today(self):
        current_date = datetime.now().strftime("%Y-%m-%d")
        if self._stream is None or self._current_date != current_date:
            if self._stream is not None:
                self._stream.close()
            self._current_date = current_date
            path = self.log_dir / f"{current_date}.log"
            self._stream = path.open("a", encoding="utf-8")
        return self._stream


def configure_backend_logging() -> logging.Logger:
    logger = logging.getLogger("backend")
    if getattr(logger, "_backend_logging_configured", False):
        return logger

    formatter = logging.Formatter("[%(asctime)s] %(levelname)s %(name)s %(message)s", "%Y-%m-%d %H:%M:%S")
    daily_handler = DailyLogFileHandler(DEFAULT_LOG_DIR)
    daily_handler.setFormatter(formatter)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    for logger_name in _LOGGER_NAMES:
        named_logger = logging.getLogger(logger_name)
        named_logger.setLevel(logging.INFO)
        named_logger.propagate = False
        named_logger.handlers = []
        named_logger.addHandler(daily_handler)
        named_logger.addHandler(console_handler)

    logger._backend_logging_configured = True
    return logger
