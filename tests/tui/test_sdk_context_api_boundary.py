import pytest

from hotaru.tui.context.sdk import SDKContext


class _FakeApiClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []

    async def stream_session_message(self, session_id: str, payload: dict):
        self.calls.append(("stream_session_message", (session_id,), {"payload": payload}))
        yield {"type": "message.created", "data": {"id": "message_1"}}
        yield {"type": "message.completed", "data": {"id": "message_1", "finish": "stop"}}

    async def create_session(self, payload: dict):
        self.calls.append(("create_session", tuple(), {"payload": payload}))
        return {"id": "session_1", "title": payload.get("title"), "agent": payload.get("agent")}

    async def list_sessions(self, project_id: str | None = None):
        self.calls.append(("list_sessions", tuple(), {"project_id": project_id}))
        return [{"id": "session_1", "agent": "build", "time": {"created": 1, "updated": 2}}]

    async def get_session(self, session_id: str):
        self.calls.append(("get_session", (session_id,), {}))
        return {"id": session_id, "agent": "build", "time": {"created": 1, "updated": 2}}

    async def update_session(self, session_id: str, payload: dict):
        self.calls.append(("update_session", (session_id,), {"payload": payload}))
        return {"id": session_id, "title": payload.get("title", "Untitled"), "time": {"created": 1, "updated": 2}}

    async def compact_session(self, session_id: str, payload: dict | None = None):
        self.calls.append(("compact_session", (session_id,), {"payload": payload or {}}))
        return {"status": "stop"}

    async def delete_messages(self, session_id: str, payload: dict):
        self.calls.append(("delete_messages", (session_id,), {"payload": payload}))
        return 2

    async def restore_messages(self, session_id: str, payload: dict):
        self.calls.append(("restore_messages", (session_id,), {"payload": payload}))
        return 1

    async def list_providers(self):
        self.calls.append(("list_providers", tuple(), {}))
        return [{"id": "openai", "name": "OpenAI"}]

    async def list_provider_models(self, provider_id: str):
        self.calls.append(("list_provider_models", (provider_id,), {}))
        return [{"id": "gpt-5", "name": "GPT-5"}]

    async def list_agents(self):
        self.calls.append(("list_agents", tuple(), {}))
        return [{"name": "build", "mode": "primary"}]

    async def list_permissions(self):
        self.calls.append(("list_permissions", tuple(), {}))
        return [{"id": "permission_1"}]

    async def reply_permission(self, request_id: str, reply: str, message: str | None = None):
        self.calls.append(
            ("reply_permission", (request_id,), {"reply": reply, "message": message}),
        )
        return True

    async def list_questions(self):
        self.calls.append(("list_questions", tuple(), {}))
        return [{"id": "question_1"}]

    async def reply_question(self, request_id: str, answers: list[list[str]]):
        self.calls.append(("reply_question", (request_id,), {"answers": answers}))
        return True

    async def reject_question(self, request_id: str):
        self.calls.append(("reject_question", (request_id,), {}))
        return True


@pytest.mark.anyio
async def test_send_message_uses_api_client_stream_contract(tmp_path) -> None:
    api = _FakeApiClient()
    sdk = SDKContext(cwd=str(tmp_path), api_client=api)

    events = [
        event
        async for event in sdk.send_message(
            session_id="session_1",
            content="hello",
            agent="build",
            model="openai/gpt-5",
            files=[{"path": "README.md"}],
        )
    ]

    assert [event["type"] for event in events] == ["message.created", "message.completed"]
    assert api.calls[0] == (
        "stream_session_message",
        ("session_1",),
        {
            "payload": {
                "content": "hello",
                "agent": "build",
                "model": "openai/gpt-5",
                "files": [{"path": "README.md"}],
            }
        },
    )


@pytest.mark.anyio
async def test_session_provider_and_agent_queries_delegate_to_api_client(tmp_path) -> None:
    api = _FakeApiClient()
    sdk = SDKContext(cwd=str(tmp_path), api_client=api)

    created = await sdk.create_session(agent="build", model="openai/gpt-5", title="New Session")
    sessions = await sdk.list_sessions(project_id="project_1")
    session = await sdk.get_session("session_1")
    compact_result = await sdk.compact_session("session_1", model="openai/gpt-5")
    providers = await sdk.list_providers()
    agents = await sdk.list_agents()

    assert created["id"] == "session_1"
    assert sessions[0]["id"] == "session_1"
    assert session is not None and session["id"] == "session_1"
    assert compact_result["status"] == "stop"
    assert providers[0]["id"] == "openai"
    assert "gpt-5" in providers[0]["models"]
    assert agents[0]["name"] == "build"
    assert ("list_provider_models", ("openai",), {}) in api.calls


@pytest.mark.anyio
async def test_permission_and_question_calls_delegate_to_api_client(tmp_path) -> None:
    api = _FakeApiClient()
    sdk = SDKContext(cwd=str(tmp_path), api_client=api)

    permissions = await sdk.list_permissions()
    await sdk.reply_permission("permission_1", "once", "Allow this")
    questions = await sdk.list_questions()
    await sdk.reply_question("question_1", [["Yes"]])
    await sdk.reject_question("question_1")

    assert permissions == [{"id": "permission_1"}]
    assert questions == [{"id": "question_1"}]
    assert ("reply_permission", ("permission_1",), {"reply": "once", "message": "Allow this"}) in api.calls
    assert ("reply_question", ("question_1",), {"answers": [["Yes"]]}) in api.calls
    assert ("reject_question", ("question_1",), {}) in api.calls


@pytest.mark.anyio
async def test_session_mutation_calls_delegate_to_api_client(tmp_path) -> None:
    api = _FakeApiClient()
    sdk = SDKContext(cwd=str(tmp_path), api_client=api)

    updated = await sdk.update_session("session_1", title="Renamed")
    deleted = await sdk.delete_messages("session_1", ["m1", "m2"])
    restored = await sdk.restore_messages("session_1", [{"info": {"id": "m1", "session_id": "session_1"}}])

    assert updated is not None and updated["title"] == "Renamed"
    assert deleted == 2
    assert restored == 1
    assert ("update_session", ("session_1",), {"payload": {"title": "Renamed"}}) in api.calls
    assert ("delete_messages", ("session_1",), {"payload": {"message_ids": ["m1", "m2"]}}) in api.calls
    assert ("restore_messages", ("session_1",), {"payload": {"messages": [{"info": {"id": "m1", "session_id": "session_1"}}]}}) in api.calls
