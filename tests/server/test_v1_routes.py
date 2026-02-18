import json
from typing import Any, AsyncIterator

from starlette.testclient import TestClient

from hotaru.server.server import Server


def test_v1_session_routes_delegate_to_session_service(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    captured: dict[str, Any] = {}

    async def fake_create(cls, payload: dict[str, Any], cwd: str):
        captured["create"] = {"payload": payload, "cwd": cwd}
        return {"id": "ses_1", "project_id": payload.get("project_id", "proj_1")}

    async def fake_list(cls, project_id: str):
        captured["list"] = project_id
        return [{"id": "ses_1", "project_id": project_id}]

    async def fake_get(cls, session_id: str):
        captured["get"] = session_id
        return {"id": session_id, "project_id": "proj_1"}

    async def fake_update(cls, session_id: str, payload: dict[str, Any]):
        captured["update"] = {"session_id": session_id, "payload": payload}
        return {"id": session_id, "title": payload.get("title", "Untitled")}

    async def fake_list_messages(cls, session_id: str):
        captured["list_messages"] = session_id
        return [{"id": "msg_1", "role": "assistant"}]

    async def fake_delete_messages(cls, session_id: str, payload: dict[str, Any]):
        captured["delete_messages"] = {"session_id": session_id, "payload": payload}
        return {"deleted": 2}

    async def fake_restore_messages(cls, session_id: str, payload: dict[str, Any]):
        captured["restore_messages"] = {"session_id": session_id, "payload": payload}
        return {"restored": 1}

    async def fake_compact(cls, session_id: str, payload: dict[str, Any], cwd: str):
        captured["compact"] = {"session_id": session_id, "payload": payload, "cwd": cwd}
        return {"ok": True}

    monkeypatch.setattr("hotaru.app_services.session_service.SessionService.create", classmethod(fake_create))
    monkeypatch.setattr("hotaru.app_services.session_service.SessionService.list", classmethod(fake_list))
    monkeypatch.setattr("hotaru.app_services.session_service.SessionService.get", classmethod(fake_get))
    monkeypatch.setattr("hotaru.app_services.session_service.SessionService.update", classmethod(fake_update))
    monkeypatch.setattr("hotaru.app_services.session_service.SessionService.list_messages", classmethod(fake_list_messages))
    monkeypatch.setattr("hotaru.app_services.session_service.SessionService.delete_messages", classmethod(fake_delete_messages))
    monkeypatch.setattr("hotaru.app_services.session_service.SessionService.restore_messages", classmethod(fake_restore_messages))
    monkeypatch.setattr("hotaru.app_services.session_service.SessionService.compact", classmethod(fake_compact))

    app = Server._create_app()
    with TestClient(app) as client:
        created = client.post("/v1/session", json={"project_id": "proj_1"})
        assert created.status_code == 200
        assert created.json()["id"] == "ses_1"

        listed = client.get("/v1/session", params={"project_id": "proj_1"})
        assert listed.status_code == 200
        assert listed.json()[0]["project_id"] == "proj_1"

        fetched = client.get("/v1/session/ses_1")
        assert fetched.status_code == 200
        assert fetched.json()["id"] == "ses_1"

        updated = client.patch("/v1/session/ses_1", json={"title": "Renamed"})
        assert updated.status_code == 200
        assert updated.json()["title"] == "Renamed"

        messages = client.get("/v1/session/ses_1/message")
        assert messages.status_code == 200
        assert messages.json()[0]["id"] == "msg_1"

        deleted = client.post("/v1/session/ses_1/message:delete", json={"message_ids": ["m1", "m2"]})
        assert deleted.status_code == 200
        assert deleted.json()["deleted"] == 2

        restored = client.post(
            "/v1/session/ses_1/message:restore",
            json={"messages": [{"info": {"id": "m1", "session_id": "ses_1"}}]},
        )
        assert restored.status_code == 200
        assert restored.json()["restored"] == 1

        compacted = client.post("/v1/session/ses_1/compact", json={"auto": True})
        assert compacted.status_code == 200
        assert compacted.json()["ok"] is True

    assert captured["create"]["payload"]["project_id"] == "proj_1"
    assert captured["list"] == "proj_1"
    assert captured["get"] == "ses_1"
    assert captured["update"]["payload"]["title"] == "Renamed"
    assert captured["list_messages"] == "ses_1"
    assert captured["delete_messages"]["payload"]["message_ids"] == ["m1", "m2"]
    assert captured["restore_messages"]["payload"]["messages"][0]["info"]["id"] == "m1"
    assert captured["compact"]["payload"]["auto"] is True


def test_v1_session_message_stream_returns_sse_envelope(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    captured: dict[str, Any] = {}

    async def fake_stream(
        cls,
        session_id: str,
        payload: dict[str, Any],
        cwd: str,
    ) -> AsyncIterator[dict[str, Any]]:
        captured["stream"] = {"session_id": session_id, "payload": payload, "cwd": cwd}
        yield {"type": "message.created", "data": {"id": "msg_1"}}
        yield {"type": "message.completed", "data": {"id": "msg_1", "finish": "stop"}}

    monkeypatch.setattr("hotaru.app_services.session_service.SessionService.stream_message", classmethod(fake_stream))

    app = Server._create_app()
    with TestClient(app) as client:
        with client.stream("POST", "/v1/session/ses_1/message:stream", json={"content": "hello"}) as response:
            assert response.status_code == 200
            lines = [line for line in response.iter_lines() if line]

    assert len(lines) >= 2
    payload_1 = json.loads(lines[0].removeprefix("data: "))
    payload_2 = json.loads(lines[1].removeprefix("data: "))

    assert payload_1["type"] == "message.created"
    assert payload_1["data"] == {"id": "msg_1"}
    assert payload_1["session_id"] == "ses_1"
    assert isinstance(payload_1["timestamp"], int)

    assert payload_2["type"] == "message.completed"
    assert payload_2["data"]["finish"] == "stop"

    assert captured["stream"]["session_id"] == "ses_1"
    assert captured["stream"]["payload"]["content"] == "hello"


def test_v1_provider_and_agent_routes_delegate_to_services(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    captured: dict[str, Any] = {}

    async def fake_list_providers(cls):
        captured["provider_list"] = True
        return [{"id": "moonshot", "name": "Moonshot"}]

    async def fake_list_models(cls, provider_id: str):
        captured["provider_models"] = provider_id
        return [{"id": "kimi-k2.5"}]

    async def fake_connect(cls, payload: dict[str, Any]):
        captured["provider_connect"] = payload
        return {"ok": True, "provider_id": payload["provider_id"]}

    async def fake_list_agents(cls):
        captured["agent_list"] = True
        return [{"name": "build"}]

    monkeypatch.setattr("hotaru.app_services.provider_service.ProviderService.list", classmethod(fake_list_providers))
    monkeypatch.setattr("hotaru.app_services.provider_service.ProviderService.list_models", classmethod(fake_list_models))
    monkeypatch.setattr("hotaru.app_services.provider_service.ProviderService.connect", classmethod(fake_connect))
    monkeypatch.setattr("hotaru.app_services.agent_service.AgentService.list", classmethod(fake_list_agents))

    app = Server._create_app()
    with TestClient(app) as client:
        providers = client.get("/v1/provider")
        assert providers.status_code == 200
        assert providers.json()[0]["id"] == "moonshot"

        models = client.get("/v1/provider/moonshot/model")
        assert models.status_code == 200
        assert models.json()[0]["id"] == "kimi-k2.5"

        connected = client.post(
            "/v1/provider/connect",
            json={"provider_id": "moonshot", "api_key": "secret", "config": {"type": "openai", "models": {}}},
        )
        assert connected.status_code == 200
        assert connected.json()["ok"] is True

        agents = client.get("/v1/agent")
        assert agents.status_code == 200
        assert agents.json()[0]["name"] == "build"

    assert captured["provider_list"] is True
    assert captured["provider_models"] == "moonshot"
    assert captured["provider_connect"]["provider_id"] == "moonshot"
    assert captured["agent_list"] is True


def test_v1_permission_question_and_event_routes_delegate_to_services(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    captured: dict[str, Any] = {}

    async def fake_permission_list(cls):
        return [{"id": "per_1"}]

    async def fake_permission_reply(cls, request_id: str, payload: dict[str, Any]):
        captured["permission_reply"] = {"request_id": request_id, "payload": payload}
        return True

    async def fake_question_list(cls):
        return [{"id": "q_1"}]

    async def fake_question_reply(cls, request_id: str, payload: dict[str, Any]):
        captured["question_reply"] = {"request_id": request_id, "payload": payload}
        return True

    async def fake_question_reject(cls, request_id: str):
        captured["question_reject"] = request_id
        return True

    async def fake_events(cls) -> AsyncIterator[dict[str, Any]]:
        yield {"type": "server.connected", "data": {"healthy": True}}

    monkeypatch.setattr("hotaru.app_services.permission_service.PermissionService.list", classmethod(fake_permission_list))
    monkeypatch.setattr("hotaru.app_services.permission_service.PermissionService.reply", classmethod(fake_permission_reply))
    monkeypatch.setattr("hotaru.app_services.question_service.QuestionService.list", classmethod(fake_question_list))
    monkeypatch.setattr("hotaru.app_services.question_service.QuestionService.reply", classmethod(fake_question_reply))
    monkeypatch.setattr("hotaru.app_services.question_service.QuestionService.reject", classmethod(fake_question_reject))
    monkeypatch.setattr("hotaru.app_services.event_service.EventService.stream", classmethod(fake_events))

    app = Server._create_app()
    with TestClient(app) as client:
        permissions = client.get("/v1/permission")
        assert permissions.status_code == 200
        assert permissions.json()[0]["id"] == "per_1"

        permission_reply = client.post("/v1/permission/per_1/reply", json={"reply": "once"})
        assert permission_reply.status_code == 200
        assert permission_reply.json() is True

        questions = client.get("/v1/question")
        assert questions.status_code == 200
        assert questions.json()[0]["id"] == "q_1"

        question_reply = client.post("/v1/question/q_1/reply", json={"answers": [["Yes"]]})
        assert question_reply.status_code == 200
        assert question_reply.json() is True

        question_reject = client.post("/v1/question/q_1/reject")
        assert question_reject.status_code == 200
        assert question_reject.json() is True

        with client.stream("GET", "/v1/event") as response:
            assert response.status_code == 200
            lines = [line for line in response.iter_lines() if line]

    assert len(lines) >= 1
    envelope = json.loads(lines[0].removeprefix("data: "))
    assert envelope["type"] == "server.connected"
    assert envelope["data"] == {"healthy": True}
    assert "timestamp" in envelope

    assert captured["permission_reply"]["request_id"] == "per_1"
    assert captured["permission_reply"]["payload"]["reply"] == "once"
    assert captured["question_reply"]["request_id"] == "q_1"
    assert captured["question_reject"] == "q_1"
