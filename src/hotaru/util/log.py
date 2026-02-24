"""Structured logging system with file output and log rotation.

Provides a logger interface similar to the TypeScript implementation,
with support for tagged logging, timing contexts, and automatic log file rotation.
"""

import json
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional, Protocol, TextIO

from ..core.global_paths import GlobalPath


class LogLevel(str, Enum):
    """Log severity levels."""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"

    @classmethod
    def parse(cls, value: str | None) -> "LogLevel":
        if value is None:
            return cls.INFO
        text = value.strip().lower()
        if text == "debug":
            return cls.DEBUG
        if text == "info":
            return cls.INFO
        if text in {"warn", "warning"}:
            return cls.WARN
        if text == "error":
            return cls.ERROR
        raise ValueError(f"invalid log level: {value}")


class LogFormat(str, Enum):
    """Log output format."""

    KV = "kv"
    JSON = "json"
    PRETTY = "pretty"

    @classmethod
    def parse(cls, value: str | None) -> "LogFormat":
        if value is None:
            return cls.KV
        text = value.strip().lower()
        if text == "kv":
            return cls.KV
        if text == "json":
            return cls.JSON
        if text == "pretty":
            return cls.PRETTY
        raise ValueError(f"invalid log format: {value}")


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
    format: LogFormat = LogFormat.KV
    console: bool = False
    file: bool = False
    log_file_path: Optional[str] = None
    _file_handle: Optional[TextIO] = None


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

    def _format_error(self, error: Exception, depth: int = 0) -> str:
        """Format error with cause chain."""
        result = str(error)
        if error.__cause__ and depth < 10:
            result += " Caused by: " + self._format_error(error.__cause__, depth + 1)
        return result

    def _normalize(self, value: Any) -> Any:
        if isinstance(value, Exception):
            return self._format_error(value)
        if isinstance(value, (dict, list, tuple)):
            return value
        if isinstance(value, (int, float, bool)):
            return value
        if value is None:
            return None
        return str(value)

    def _value(self, value: Any) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (int, float)):
            return str(value)
        if isinstance(value, (dict, list, tuple)):
            return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        text = str(value)
        if text == "" or any(ch.isspace() for ch in text) or "=" in text:
            return json.dumps(text, ensure_ascii=False)
        return text

    def _build_payload(
        self,
        level: LogLevel,
        message: Any,
        extra: Optional[Dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Build normalized payload for a log event."""
        global _last_timestamp

        now = time.time()
        delta_ms = int((now - _last_timestamp) * 1000)
        _last_timestamp = now

        tags = {**self.tags, **(extra or {})}
        data = {k: self._normalize(v) for k, v in tags.items() if v is not None}

        return {
            "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "delta_ms": delta_ms,
            "level": level.value.lower(),
            "msg": self._normalize(message),
            **data,
        }

    def _build_message(
        self,
        level: LogLevel,
        message: Any,
        extra: Optional[Dict[str, Any]] = None,
    ) -> str:
        payload = self._build_payload(level, message, extra)
        if _config.format == LogFormat.JSON:
            return json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"

        pairs = " ".join(
            f"{k}={self._value(v)}"
            for k, v in payload.items()
            if k not in {"time", "delta_ms", "level", "msg"}
        )
        if _config.format == LogFormat.PRETTY:
            text = str(payload.get("msg") or "")
            if pairs:
                return (
                    f"{payload['time']} {level.value} {text} ({pairs}) +{payload['delta_ms']}ms\n"
                )
            return f"{payload['time']} {level.value} {text} +{payload['delta_ms']}ms\n"

        parts = [
            str(payload["time"]),
            f"+{payload['delta_ms']}ms",
            f"level={payload['level']}",
            f"msg={self._value(payload.get('msg'))}",
            pairs,
        ]
        return " ".join(part for part in parts if part) + "\n"

    def _write(self, message: str) -> None:
        """Write message to configured output."""
        if _config.console:
            sys.stderr.write(message)
            sys.stderr.flush()
        if _config.file and _config._file_handle:
            _config._file_handle.write(message)
            _config._file_handle.flush()

    def debug(self, message: Any = None, extra: Optional[Dict[str, Any]] = None) -> None:
        """Log debug message."""
        if self._should_log(LogLevel.DEBUG):
            self._write(self._build_message(LogLevel.DEBUG, message, extra))

    def info(self, message: Any = None, extra: Optional[Dict[str, Any]] = None) -> None:
        """Log info message."""
        if self._should_log(LogLevel.INFO):
            self._write(self._build_message(LogLevel.INFO, message, extra))

    def warn(self, message: Any = None, extra: Optional[Dict[str, Any]] = None) -> None:
        """Log warning message."""
        if self._should_log(LogLevel.WARN):
            self._write(self._build_message(LogLevel.WARN, message, extra))

    def warning(self, message: Any = None, extra: Optional[Dict[str, Any]] = None) -> None:
        """Compatibility alias for warn()."""
        self.warn(message, extra)

    def error(self, message: Any = None, extra: Optional[Dict[str, Any]] = None) -> None:
        """Log error message."""
        if self._should_log(LogLevel.ERROR):
            self._write(self._build_message(LogLevel.ERROR, message, extra))

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
            print_to_stderr: Backward compatibility alias for console output.
            dev: If True, use dev.log instead of timestamped file
            level: Minimum log level to output
        """
        if level:
            _config.level = level

        _config.console = print_to_stderr
        _config.file = not print_to_stderr
        cls.close()
        if not _config.file:
            _config.log_file_path = None
            return

        cls._cleanup_logs(GlobalPath.log())
        log_dir = Path(GlobalPath.log())
        log_dir.mkdir(parents=True, exist_ok=True)
        if dev:
            log_path = log_dir / "dev.log"
        else:
            timestamp = datetime.now().isoformat().split(".")[0].replace(":", "")
            log_path = log_dir / f"{timestamp}.log"

        _config.log_file_path = str(log_path)
        _config._file_handle = log_path.open("w", encoding="utf-8")

    @classmethod
    def configure(
        cls,
        *,
        level: LogLevel | None = None,
        format: LogFormat | None = None,
        console: bool | None = None,
        file: bool | None = None,
        dev: bool = False,
    ) -> None:
        """Configure logging sinks and output format."""
        if level is not None:
            _config.level = level
        if format is not None:
            _config.format = format
        if console is None:
            console = _config.console
        _config.console = console
        if file is None:
            file = True
        _config.file = file

        cls.close()
        if not _config.file:
            _config.log_file_path = None
            return

        cls._cleanup_logs(GlobalPath.log())
        log_dir = Path(GlobalPath.log())
        log_dir.mkdir(parents=True, exist_ok=True)
        if dev:
            log_path = log_dir / "dev.log"
        else:
            stamp = datetime.now().isoformat().split(".")[0].replace(":", "")
            log_path = log_dir / f"{stamp}.log"

        _config.log_file_path = str(log_path)
        _config._file_handle = log_path.open("w", encoding="utf-8")

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

        for old_file in log_files[:-10]:
            if old_file.exists():
                old_file.unlink()

    @classmethod
    def close(cls) -> None:
        """Close the log file handle if open."""
        if _config._file_handle:
            _config._file_handle.close()
            _config._file_handle = None


# Create default logger instance
Default = Log.default()
