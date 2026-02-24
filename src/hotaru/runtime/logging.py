"""Runtime logging bootstrap helpers."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Literal, Optional

from ..core.config import ConfigManager
from ..util.log import Log, LogFormat, LogLevel

LogMode = Literal["cli", "run", "tui", "web"]


@dataclass(frozen=True)
class LogSettings:
    level: LogLevel
    format: LogFormat
    console: bool
    file: bool
    access_log: bool
    dev_file: bool


def _mode_console(mode: LogMode) -> bool:
    if mode == "web":
        return True
    return False


def _mode_access(mode: LogMode) -> bool:
    if mode == "web":
        return True
    return False


async def _resolve(
    *,
    mode: LogMode,
    level: Optional[str],
    format: Optional[str],
    access_log: Optional[bool],
    console: Optional[bool],
    file: Optional[bool],
    dev_file: Optional[bool],
) -> LogSettings:
    cfg = await ConfigManager.get()
    log = cfg.logging

    lv_text = level or (log.level if log else None) or cfg.log_level
    fm_text = format or (log.format if log else None)
    lv = LogLevel.parse(lv_text)
    fm = LogFormat.parse(fm_text)

    use_console = console
    if use_console is None:
        use_console = log.console if log and log.console is not None else _mode_console(mode)

    use_file = file
    if use_file is None:
        use_file = log.file if log and log.file is not None else True

    use_access = access_log
    if use_access is None:
        use_access = log.access_log if log and log.access_log is not None else _mode_access(mode)

    use_dev = dev_file
    if use_dev is None:
        use_dev = log.dev_file if log and log.dev_file is not None else False

    return LogSettings(
        level=lv,
        format=fm,
        console=use_console,
        file=use_file,
        access_log=use_access,
        dev_file=use_dev,
    )


def bootstrap_logging(
    *,
    mode: LogMode,
    level: Optional[str] = None,
    format: Optional[str] = None,
    access_log: Optional[bool] = None,
    console: Optional[bool] = None,
    file: Optional[bool] = None,
    dev_file: Optional[bool] = None,
) -> LogSettings:
    """Resolve config and initialize the process logger."""
    settings = asyncio.run(
        _resolve(
            mode=mode,
            level=level,
            format=format,
            access_log=access_log,
            console=console,
            file=file,
            dev_file=dev_file,
        )
    )
    Log.configure(
        level=settings.level,
        format=settings.format,
        console=settings.console,
        file=settings.file,
        dev=settings.dev_file,
    )
    return settings
