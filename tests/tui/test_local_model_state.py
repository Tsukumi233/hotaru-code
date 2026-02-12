import json
from pathlib import Path

from hotaru.tui.context import local as local_module
from hotaru.tui.context.local import ModelSelection, ModelState


def _providers():
    return [
        {
            "id": "provider-a",
            "models": {
                "model-1": {"id": "model-1"},
                "model-2": {"id": "model-2"},
            },
        },
        {
            "id": "provider-b",
            "models": {
                "model-x": {"id": "model-x"},
            },
        },
    ]


def test_model_state_persists_current_selection(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(local_module.GlobalPath, "state", str(tmp_path), raising=False)

    state = ModelState(_providers())
    state.set(ModelSelection(provider_id="provider-a", model_id="model-2"), add_to_recent=True)

    reloaded = ModelState(_providers())
    current = reloaded.current()
    assert current is not None
    assert (current.provider_id, current.model_id) == ("provider-a", "model-2")
    assert reloaded.recent()[0].model_id == "model-2"


def test_model_state_bootstraps_from_recent_when_current_missing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(local_module.GlobalPath, "state", str(tmp_path), raising=False)

    model_file = tmp_path / "model.json"
    model_file.write_text(
        json.dumps(
            {
                "recent": [{"provider_id": "provider-b", "model_id": "model-x"}],
                "favorite": [],
            }
        ),
        encoding="utf-8",
    )

    state = ModelState(_providers())
    current = state.current()
    assert current is not None
    assert (current.provider_id, current.model_id) == ("provider-b", "model-x")


def test_model_state_first_available_returns_fallback_model(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(local_module.GlobalPath, "state", str(tmp_path), raising=False)

    state = ModelState(_providers())
    fallback = state.first_available()
    assert fallback is not None
    assert (fallback.provider_id, fallback.model_id) == ("provider-a", "model-1")
