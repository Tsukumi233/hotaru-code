import httpx
import pytest

from hotaru.api_client import HotaruAPIClient


@pytest.mark.anyio
async def test_api_client_calls_expected_v1_contract_endpoints() -> None:
    calls: list[tuple[str, str]] = []

    stream_payload = (
        'data: {"type":"message.created","data":{"id":"message_1"}}\n\n'
        'data: {"type":"message.completed","data":{"id":"message_1","finish":"stop"}}\n\n'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        route = (request.method, request.url.path)

        if route == ("POST", "/v1/session"):
            return httpx.Response(200, json={"id": "session_1"})
        if route == ("GET", "/v1/session"):
            return httpx.Response(200, json=[{"id": "session_1"}])
        if route == ("GET", "/v1/session/session_1"):
            return httpx.Response(200, json={"id": "session_1"})
        if route == ("POST", "/v1/session/session_1/message:stream"):
            return httpx.Response(
                200,
                text=stream_payload,
                headers={"content-type": "text/event-stream"},
            )
        if route == ("POST", "/v1/session/session_1/compact"):
            return httpx.Response(200, json={"ok": True})
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
    )

    await client.create_session({"agent": "build"})
    await client.list_sessions()
    await client.get_session("session_1")
    events = [event async for event in client.stream_session_message("session_1", {"content": "hello"})]
    await client.compact_session("session_1")
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

    assert [evt["type"] for evt in events] == ["message.created", "message.completed"]
    assert {
        ("POST", "/v1/session"),
        ("GET", "/v1/session"),
        ("GET", "/v1/session/session_1"),
        ("POST", "/v1/session/session_1/message:stream"),
        ("POST", "/v1/session/session_1/compact"),
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
async def test_api_client_uses_legacy_fallback_when_v1_route_missing() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/v1/provider":
            return httpx.Response(404, json={"error": "missing"})
        if request.url.path == "/provider":
            return httpx.Response(200, json=[{"id": "demo", "name": "Demo"}])
        return httpx.Response(404, json={"error": "unexpected route"})

    client = HotaruAPIClient(
        base_url="http://hotaru.test",
        transport=httpx.MockTransport(handler),
    )
    result = await client.list_providers()
    await client.aclose()

    assert result == [{"id": "demo", "name": "Demo"}]
    assert calls == ["/v1/provider", "/provider"]
