import json
from pathlib import Path

import pytest

from hotaru.app_services.preference_service import PreferenceService
from hotaru.core.global_paths import GlobalPath


@pytest.mark.anyio
async def test_preference_service_reads_current_from_model_json(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(GlobalPath, "state", classmethod(lambda cls: str(tmp_path)))
    (tmp_path / "model.json").write_text(
        json.dumps(
            {
                "current": {"provider_id": "moonshot", "model_id": "kimi-k2.5"},
                "agent": "build",
            }
        ),
        encoding="utf-8",
    )

    current = await PreferenceService.get_current()
    assert current == {
        "provider_id": "moonshot",
        "model_id": "kimi-k2.5",
        "agent": "build",
    }


@pytest.mark.anyio
async def test_preference_service_updates_current_and_recent(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(GlobalPath, "state", classmethod(lambda cls: str(tmp_path)))
    (tmp_path / "model.json").write_text(
        json.dumps(
            {
                "current": {"provider_id": "openai", "model_id": "gpt-5"},
                "recent": [{"provider_id": "openai", "model_id": "gpt-5"}],
                "favorite": [],
            }
        ),
        encoding="utf-8",
    )

    updated = await PreferenceService.update_current(
        {
            "provider_id": "moonshot",
            "model_id": "kimi-k2.5",
            "agent": "build",
        }
    )

    assert updated == {
        "provider_id": "moonshot",
        "model_id": "kimi-k2.5",
        "agent": "build",
    }

    data = json.loads((tmp_path / "model.json").read_text(encoding="utf-8"))
    assert data["current"] == {"provider_id": "moonshot", "model_id": "kimi-k2.5"}
    assert data["recent"][0] == {"provider_id": "moonshot", "model_id": "kimi-k2.5"}
    assert data["recent"][1] == {"provider_id": "openai", "model_id": "gpt-5"}


@pytest.mark.anyio
async def test_preference_service_rejects_partial_model_update(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(GlobalPath, "state", classmethod(lambda cls: str(tmp_path)))

    with pytest.raises(ValueError, match="provider_id"):
        await PreferenceService.update_current({"provider_id": "openai"})
