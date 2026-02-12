from pathlib import Path

from hotaru.provider.auth import ProviderAuth


def test_provider_auth_store_roundtrip(monkeypatch, tmp_path: Path) -> None:
    auth_file = tmp_path / "provider-auth.json"
    monkeypatch.setattr(
        ProviderAuth,
        "_filepath",
        classmethod(lambda cls: auth_file),
    )

    ProviderAuth.set("demo", "secret-key")
    assert ProviderAuth.get("demo") == "secret-key"

    ProviderAuth.remove("demo")
    assert ProviderAuth.get("demo") is None


def test_provider_auth_handles_missing_file(monkeypatch, tmp_path: Path) -> None:
    auth_file = tmp_path / "missing.json"
    monkeypatch.setattr(
        ProviderAuth,
        "_filepath",
        classmethod(lambda cls: auth_file),
    )

    assert ProviderAuth.all() == {}
