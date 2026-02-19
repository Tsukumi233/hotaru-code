import json

import httpx
import pytest

from hotaru.api_client import ApiClientError, HotaruAPIClient


@pytest.mark.anyio
async def test_api_client_calls_expected_v1_contract_endpoints() -> None:
    calls: list[tuple[str, str]] = []
    directory_headers: list[str] = []

    event_payload = 'data: {"type":"server.connected","data":{}}\n\n'

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.path.startswith("/v1/"):
            directory_headers.append(request.headers.get("x-hotaru-directory", ""))
        route = (request.method, request.url.path)

        if route == ("POST", "/v1/session"):
            return httpx.Response(200, json={"id": "session_1"})
        if route == ("GET", "/v1/session"):
            return httpx.Response(200, json=[{"id": "session_1"}])
        if route == ("GET", "/v1/session/session_1"):
            return httpx.Response(200, json={"id": "session_1"})
        if route == ("PATCH", "/v1/session/session_1"):
            return httpx.Response(200, json={"id": "session_1", "title": "Renamed"})
        if route == ("GET", "/v1/session/session_1/message"):
            return httpx.Response(200, json=[{"id": "message_1"}])
        if route == ("POST", "/v1/session/session_1/message:delete"):
            return httpx.Response(200, json={"deleted": 1})
        if route == ("POST", "/v1/session/session_1/message:restore"):
            return httpx.Response(200, json={"restored": 1})
        if route == ("POST", "/v1/session/session_1/message"):
            return httpx.Response(200, json={"ok": True, "assistant_message_id": "message_1", "status": "stop"})
        if route == ("POST", "/v1/session/session_1/interrupt"):
            return httpx.Response(200, json={"ok": True, "interrupted": True})
        if route == ("POST", "/v1/session/session_1/compact"):
            return httpx.Response(200, json={"ok": True})
        if route == ("GET", "/v1/path"):
            return httpx.Response(200, json={"home": "/tmp", "state": "/tmp", "config": "/tmp", "cwd": "/tmp"})
        if route == ("GET", "/v1/event"):
            return httpx.Response(
                200,
                text=event_payload,
                headers={"content-type": "text/event-stream"},
            )
        if route == ("GET", "/v1/provider"):
            return httpx.Response(200, json=[{"id": "openai", "name": "OpenAI", "models": {}}])
        if route == ("GET", "/v1/provider/openai/model"):
            return httpx.Response(200, json=[{"id": "gpt-5", "name": "GPT-5"}])
        if route == ("POST", "/v1/provider/connect"):
            return httpx.Response(200, json={"ok": True})
        if route == ("GET", "/v1/agent"):
            return httpx.Response(200, json=[{"name": "build", "mode": "primary"}])
        if route == ("GET", "/v1/permission"):
            return httpx.Response(200, json=[{"id": "perm_1"}])
        if route == ("POST", "/v1/permission/perm_1/reply"):
            return httpx.Response(200, json=True)
        if route == ("GET", "/v1/question"):
            return httpx.Response(200, json=[{"id": "question_1"}])
        if route == ("POST", "/v1/question/question_1/reply"):
            return httpx.Response(200, json=True)
        if route == ("POST", "/v1/question/question_1/reject"):
            return httpx.Response(200, json=True)
        return httpx.Response(404, json={"error": "unexpected route"})

    client = HotaruAPIClient(
        base_url="http://hotaru.test",
        transport=httpx.MockTransport(handler),
        directory="/tmp/workspace",
    )

    await client.create_session({"agent": "build"})
    await client.list_sessions()
    await client.get_session("session_1")
    await client.update_session("session_1", {"title": "Renamed"})
    await client.list_messages("session_1")
    await client.delete_messages("session_1", {"message_ids": ["message_1"]})
    await client.restore_messages("session_1", {"messages": [{"id": "message_1"}]})
    message_result = await client.send_session_message("session_1", {"content": "hello"})
    await client.interrupt_session("session_1")
    await client.compact_session("session_1")
    await client.get_paths()
    global_events = [event async for event in client.stream_events()]
    await client.list_providers()
    await client.list_provider_models("openai")
    await client.connect_provider(
        {
            "provider_id": "openai",
            "provider_type": "openai",
            "provider_name": "OpenAI",
            "base_url": "https://api.openai.com/v1",
            "api_key": "sk-test",
            "model_ids": ["gpt-5"],
        }
    )
    await client.list_agents()
    await client.list_permissions()
    await client.reply_permission("perm_1", "once")
    await client.list_questions()
    await client.reply_question("question_1", [["Yes"]])
    await client.reject_question("question_1")
    await client.aclose()

    assert message_result["ok"] is True
    assert [evt["type"] for evt in global_events] == ["server.connected"]
    assert all(value == "/tmp/workspace" for value in directory_headers)
    assert {
        ("POST", "/v1/session"),
        ("GET", "/v1/session"),
        ("GET", "/v1/session/session_1"),
        ("PATCH", "/v1/session/session_1"),
        ("GET", "/v1/session/session_1/message"),
        ("POST", "/v1/session/session_1/message:delete"),
        ("POST", "/v1/session/session_1/message:restore"),
        ("POST", "/v1/session/session_1/message"),
        ("POST", "/v1/session/session_1/interrupt"),
        ("POST", "/v1/session/session_1/compact"),
        ("GET", "/v1/path"),
        ("GET", "/v1/event"),
        ("GET", "/v1/provider"),
        ("GET", "/v1/provider/openai/model"),
        ("POST", "/v1/provider/connect"),
        ("GET", "/v1/agent"),
        ("GET", "/v1/permission"),
        ("POST", "/v1/permission/perm_1/reply"),
        ("GET", "/v1/question"),
        ("POST", "/v1/question/question_1/reply"),
        ("POST", "/v1/question/question_1/reject"),
    }.issubset(set(calls))


@pytest.mark.anyio
async def test_api_client_does_not_fallback_to_legacy_paths() -> None:
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.path == "/v1/provider":
            return httpx.Response(404, json={"error": "missing"})
        return httpx.Response(404, json={"error": "unexpected route"})

    client = HotaruAPIClient(
        base_url="http://hotaru.test",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ApiClientError):
        await client.list_providers()
    await client.aclose()

    assert calls == [("GET", "/v1/provider")]


@pytest.mark.anyio
async def test_connect_provider_does_not_normalize_legacy_camel_case_fields() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/provider/connect":
            captured["body"] = json.loads(request.content.decode("utf-8"))
            return httpx.Response(400, json={"error": {"message": "bad request"}})
        return httpx.Response(404, json={"error": "unexpected route"})

    client = HotaruAPIClient(
        base_url="http://hotaru.test",
        transport=httpx.MockTransport(handler),
    )

    payload = {
        "providerID": "openai",
        "providerType": "openai",
        "providerName": "OpenAI",
        "baseURL": "https://api.openai.com/v1",
        "apiKey": "sk-test",
        "modelIDs": ["gpt-5"],
    }

    with pytest.raises(ApiClientError):
        await client.connect_provider(payload)
    await client.aclose()

    assert captured["body"] == payload
