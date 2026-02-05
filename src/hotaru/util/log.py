"""Structured logging system with file output and log rotation.

Provides a logger interface similar to the TypeScript implementation,
with support for tagged logging, timing contexts, and automatic log file rotation.
"""

import sys
import time
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional, Protocol
from dataclasses import dataclass, field

from ..core.global_paths import GlobalPath


class LogLevel(str, Enum):
    """Log severity levels."""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"


LEVEL_PRIORITY = {
    LogLevel.DEBUG: 0,
    LogLevel.INFO: 1,
    LogLevel.WARN: 2,
    LogLevel.ERROR: 3,
}


@dataclass
class LogConfig:
    """Global logging configuration."""
    level: LogLevel = LogLevel.INFO
    print_to_stderr: bool = False
    log_file_path: Optional[str] = None
    _file_handle: Optional[Any] = None


_config = LogConfig()
_last_timestamp = time.time()


class Timer(Protocol):
    """Protocol for timer context managers."""
    def stop(self) -> None: ...


@dataclass
class LogTimer:
    """Timer for measuring operation duration."""
    logger: 'Logger'
    message: str
    extra: Dict[str, Any]
    start_time: float = field(default_factory=time.time)

    def stop(self) -> None:
        """Stop the timer and log completion."""
        duration_ms = int((time.time() - self.start_time) * 1000)
        self.logger.info(self.message, {**self.extra, "status": "completed", "duration": duration_ms})

    def __enter__(self) -> 'LogTimer':
        return self

    def __exit__(self, *args) -> None:
        self.stop()


class Logger:
    """Structured logger with support for tagging and timing."""

    def __init__(self, tags: Optional[Dict[str, Any]] = None):
        self.tags = tags or {}

    def _should_log(self, level: LogLevel) -> bool:
        """Check if this log level should be output."""
        return LEVEL_PRIORITY[level] >= LEVEL_PRIORITY[_config.level]

    def _build_message(self, level: LogLevel, message: Any, extra: Optional[Dict[str, Any]] = None) -> str:
        """Build a formatted log message."""
        global _last_timestamp

        # Merge tags and extra data
        all_tags = {**self.tags, **(extra or {})}

        # Format tag string
        tag_parts = []
        for key, value in all_tags.items():
            if value is None:
                continue

            prefix = f"{key}="
            if isinstance(value, Exception):
                tag_parts.append(prefix + self._format_error(value))
            elif isinstance(value, dict):
                import json
                tag_parts.append(prefix + json.dumps(value))
            else:
                tag_parts.append(prefix + str(value))

        tag_str = " ".join(tag_parts)

        # Calculate time delta
        now = time.time()
        delta_ms = int((now - _last_timestamp) * 1000)
        _last_timestamp = now

        # Build final message
        timestamp = datetime.now().isoformat().split('.')[0]
        parts = [timestamp, f"+{delta_ms}ms", tag_str, str(message)]

        return " ".join(p for p in parts if p) + "\n"

    def _format_error(self, error: Exception, depth: int = 0) -> str:
        """Format error with cause chain."""
        result = str(error)
        if hasattr(error, '__cause__') and error.__cause__ and depth < 10:
            result += " Caused by: " + self._format_error(error.__cause__, depth + 1)
        return result

    def _write(self, message: str) -> None:
        """Write message to configured output."""
        if _config.print_to_stderr:
            sys.stderr.write(message)
            sys.stderr.flush()
        elif _config._file_handle:
            _config._file_handle.write(message)
            _config._file_handle.flush()

    def debug(self, message: Any = None, extra: Optional[Dict[str, Any]] = None) -> None:
        """Log debug message."""
        if self._should_log(LogLevel.DEBUG):
            self._write("DEBUG " + self._build_message(LogLevel.DEBUG, message, extra))

    def info(self, message: Any = None, extra: Optional[Dict[str, Any]] = None) -> None:
        """Log info message."""
        if self._should_log(LogLevel.INFO):
            self._write("INFO  " + self._build_message(LogLevel.INFO, message, extra))

    def warn(self, message: Any = None, extra: Optional[Dict[str, Any]] = None) -> None:
        """Log warning message."""
        if self._should_log(LogLevel.WARN):
            self._write("WARN  " + self._build_message(LogLevel.WARN, message, extra))

    def error(self, message: Any = None, extra: Optional[Dict[str, Any]] = None) -> None:
        """Log error message."""
        if self._should_log(LogLevel.ERROR):
            self._write("ERROR " + self._build_message(LogLevel.ERROR, message, extra))

    def tag(self, key: str, value: Any) -> 'Logger':
        """Add a tag to this logger instance."""
        self.tags[key] = value
        return self

    def clone(self) -> 'Logger':
        """Create a copy of this logger with the same tags."""
        return Logger(tags=self.tags.copy())

    def time(self, message: str, extra: Optional[Dict[str, Any]] = None) -> LogTimer:
        """Create a timer context for measuring operation duration."""
        extra = extra or {}
        self.info(message, {**extra, "status": "started"})
        return LogTimer(logger=self, message=message, extra=extra)


class Log:
    """Global logging interface and factory."""

    _loggers: Dict[str, Logger] = {}
    _default: Optional[Logger] = None

    @classmethod
    def create(cls, tags: Optional[Dict[str, Any]] = None) -> Logger:
        """Create or retrieve a cached logger instance.

        If tags contain a 'service' key, the logger is cached by service name.
        """
        tags = tags or {}
        service = tags.get("service")

        if service and isinstance(service, str):
            if service in cls._loggers:
                return cls._loggers[service]

            logger = Logger(tags=tags)
            cls._loggers[service] = logger
            return logger

        return Logger(tags=tags)

    @classmethod
    def default(cls) -> Logger:
        """Get the default logger instance."""
        if cls._default is None:
            cls._default = cls.create({"service": "default"})
        return cls._default

    @classmethod
    def init(cls, print_to_stderr: bool = False, dev: bool = False, level: Optional[LogLevel] = None) -> None:
        """Initialize global logging configuration.

        Args:
            print_to_stderr: If True, log to stderr instead of file
            dev: If True, use dev.log instead of timestamped file
            level: Minimum log level to output
        """
        if level:
            _config.level = level

        # Cleanup old log files
        cls._cleanup_logs(GlobalPath.log)

        if print_to_stderr:
            _config.print_to_stderr = True
            return

        # Create log file
        log_dir = Path(GlobalPath.log)
        if dev:
            log_path = log_dir / "dev.log"
        else:
            timestamp = datetime.now().isoformat().split('.')[0].replace(':', '')
            log_path = log_dir / f"{timestamp}.log"

        _config.log_file_path = str(log_path)

        # Truncate if exists
        if log_path.exists():
            log_path.unlink()

        # Open for writing
        _config._file_handle = open(log_path, 'w', encoding='utf-8')

    @classmethod
    def file(cls) -> str:
        """Get the current log file path."""
        return _config.log_file_path or ""

    @classmethod
    def _cleanup_logs(cls, log_dir: str) -> None:
        """Remove old log files, keeping only the most recent 10."""
        log_path = Path(log_dir)
        if not log_path.exists():
            return

        # Find timestamped log files
        log_files = sorted(
            [f for f in log_path.glob("????-??-??T??????.log")],
            key=lambda p: p.stat().st_mtime
        )

        if len(log_files) <= 10:
            return

        # Delete oldest files
        for old_file in log_files[:-10]:
            try:
                old_file.unlink()
            except Exception:
                pass

    @classmethod
    def close(cls) -> None:
        """Close the log file handle if open."""
        if _config._file_handle:
            _config._file_handle.close()
            _config._file_handle = None


# Create default logger instance
Default = Log.default()
