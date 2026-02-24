from __future__ import annotations

import json
from pathlib import Path

from hotaru.core.global_paths import GlobalPath
from hotaru.util.log import Log, LogFormat, LogLevel


def test_log_writes_console_and_file(monkeypatch, tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(GlobalPath, "log", classmethod(lambda cls: str(tmp_path)))
    Log.configure(level=LogLevel.INFO, format=LogFormat.KV, console=True, file=True, dev=True)

    log = Log.create({"service": "test.log"})
    log.info("hello", {"value": 7})
    Log.close()

    stderr = capsys.readouterr().err
    text = (tmp_path / "dev.log").read_text(encoding="utf-8")

    assert "msg=hello" in stderr
    assert "service=test.log" in stderr
    assert "value=7" in text


def test_log_supports_json_format(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(GlobalPath, "log", classmethod(lambda cls: str(tmp_path)))
    Log.configure(level=LogLevel.INFO, format=LogFormat.JSON, console=False, file=True, dev=True)

    log = Log.create({"service": "test.json"})
    log.info("hello world", {"meta": {"k": "v"}})
    Log.close()

    line = (tmp_path / "dev.log").read_text(encoding="utf-8").strip()
    payload = json.loads(line)

    assert payload["level"] == "info"
    assert payload["msg"] == "hello world"
    assert payload["service"] == "test.json"
    assert payload["meta"] == {"k": "v"}
