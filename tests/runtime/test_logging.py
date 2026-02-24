from __future__ import annotations

from hotaru.core.config import Config, LoggingConfig
from hotaru.runtime.logging import bootstrap_logging


def test_bootstrap_logging_uses_web_defaults(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    async def fake_get(cls):
        return Config()

    seen: dict[str, object] = {}

    def fake_configure(
        cls,
        *,
        level,
        format,
        console,
        file,
        dev,
    ) -> None:
        seen["level"] = level
        seen["format"] = format
        seen["console"] = console
        seen["file"] = file
        seen["dev"] = dev

    monkeypatch.setattr("hotaru.runtime.logging.ConfigManager.get", classmethod(fake_get))
    monkeypatch.setattr("hotaru.runtime.logging.Log.configure", classmethod(fake_configure))

    settings = bootstrap_logging(mode="web")

    assert settings.console is True
    assert settings.file is True
    assert settings.access_log is True
    assert seen["console"] is True
    assert seen["file"] is True


def test_bootstrap_logging_prefers_logging_config(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    async def fake_get(cls):
        return Config(
            log_level="warn",
            logging=LoggingConfig(
                level="debug",
                format="json",
                console=False,
                file=False,
                access_log=False,
                dev_file=True,
            ),
        )

    seen: dict[str, object] = {}

    def fake_configure(
        cls,
        *,
        level,
        format,
        console,
        file,
        dev,
    ) -> None:
        seen["level"] = level
        seen["format"] = format
        seen["console"] = console
        seen["file"] = file
        seen["dev"] = dev

    monkeypatch.setattr("hotaru.runtime.logging.ConfigManager.get", classmethod(fake_get))
    monkeypatch.setattr("hotaru.runtime.logging.Log.configure", classmethod(fake_configure))

    settings = bootstrap_logging(mode="web")

    assert settings.console is False
    assert settings.file is False
    assert settings.access_log is False
    assert settings.dev_file is True
    assert seen["dev"] is True
