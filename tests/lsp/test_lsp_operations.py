from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import quote

import pytest

from hotaru.lsp.lsp import LSP


def _file_uri(path: Path) -> str:
    return "file://" + quote(str(path.resolve()).replace("\\", "/"), safe="/:.")


class _FakeClient:
    def __init__(self, server_id: str, responses: dict[str, Any]) -> None:
        self.server_id = server_id
        self.responses = responses
        self.requests: list[tuple[str, dict[str, Any]]] = []

    def _path_to_uri(self, path: str) -> str:
        return _file_uri(Path(path))

    async def _send_request(self, method: str, params: dict[str, Any]) -> Any:
        self.requests.append((method, params))
        response = self.responses.get(method)
        if isinstance(response, Exception):
            raise response
        return response


@pytest.mark.anyio
async def test_implementation_merges_results(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    lsp = LSP()
    file_path = tmp_path / "main.py"
    client_one = _FakeClient("one", {"textDocument/implementation": [{"uri": "one"}]})
    client_two = _FakeClient("two", {"textDocument/implementation": {"uri": "two"}})

    async def fake_get_clients(self, file: str):
        del self
        assert file == str(file_path)
        return [client_one, client_two]

    monkeypatch.setattr(LSP, "_get_clients", fake_get_clients)

    result = await lsp.implementation(str(file_path), 2, 3)

    assert result == [{"uri": "one"}, {"uri": "two"}]


@pytest.mark.anyio
async def test_prepare_call_hierarchy_filters_falsy(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    lsp = LSP()
    file_path = tmp_path / "main.py"
    client = _FakeClient("one", {"textDocument/prepareCallHierarchy": [None, {"name": "callable"}]})

    async def fake_get_clients(self, _file: str):
        del self
        return [client]

    monkeypatch.setattr(LSP, "_get_clients", fake_get_clients)

    result = await lsp.prepare_call_hierarchy(str(file_path), 4, 5)

    assert result == [{"name": "callable"}]


@pytest.mark.anyio
async def test_incoming_calls_uses_first_hierarchy_item(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    lsp = LSP()
    file_path = tmp_path / "main.py"
    primary = {"name": "foo", "uri": _file_uri(file_path)}
    client = _FakeClient(
        "one",
        {
            "textDocument/prepareCallHierarchy": [primary, {"name": "ignored"}],
            "callHierarchy/incomingCalls": [{"from": {"name": "caller"}}],
        },
    )

    async def fake_get_clients(self, _file: str):
        del self
        return [client]

    monkeypatch.setattr(LSP, "_get_clients", fake_get_clients)

    result = await lsp.incoming_calls(str(file_path), 1, 1)

    assert result == [{"from": {"name": "caller"}}]
    assert client.requests[1][0] == "callHierarchy/incomingCalls"
    assert client.requests[1][1] == {"item": primary}


@pytest.mark.anyio
async def test_outgoing_calls_skips_clients_without_hierarchy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    lsp = LSP()
    file_path = tmp_path / "main.py"
    empty_client = _FakeClient("empty", {"textDocument/prepareCallHierarchy": []})
    ok_client = _FakeClient(
        "ok",
        {
            "textDocument/prepareCallHierarchy": [{"name": "root"}],
            "callHierarchy/outgoingCalls": [{"to": {"name": "callee"}}],
        },
    )

    async def fake_get_clients(self, _file: str):
        del self
        return [empty_client, ok_client]

    monkeypatch.setattr(LSP, "_get_clients", fake_get_clients)

    result = await lsp.outgoing_calls(str(file_path), 3, 7)

    assert result == [{"to": {"name": "callee"}}]
    assert [method for method, _ in empty_client.requests] == ["textDocument/prepareCallHierarchy"]
