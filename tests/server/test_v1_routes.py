import json
from typing import Any, AsyncIterator

from fastapi.testclient import TestClient

from hotaru.agent.agent import AgentInfo, AgentMode
from hotaru.server.server import Server


def test_v1_session_routes_delegate_to_session_service(monkeypatch, app_ctx) -> None:  # type: ignore[no-untyped-def]
    captured: dict[str, Any] = {}

    async def fake_create(cls, payload: dict[str, Any], cwd: str, **_kw):
        captured["create"] = {"payload": payload, "cwd": cwd}
        return {"id": "ses_1", "project_id": payload.get("project_id", "proj_1")}

    async def fake_list(cls, project_id: str | None, cwd: str):
        captured["list"] = {"project_id": project_id, "cwd": cwd}
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

    async def fake_interrupt(cls, session_id: str, **_kwargs):
        captured["interrupt"] = session_id
        return {"ok": True, "interrupted": True}

    async def fake_delete_messages(cls, session_id: str, payload: dict[str, Any]):
        captured["delete_messages"] = {"session_id": session_id, "payload": payload}
        return {"deleted": 2}

    async def fake_restore_messages(cls, session_id: str, payload: dict[str, Any]):
        captured["restore_messages"] = {"session_id": session_id, "payload": payload}
        return {"restored": 1}

    async def fake_compact(cls, session_id: str, payload: dict[str, Any], cwd: str, **_kwargs):
        captured["compact"] = {"session_id": session_id, "payload": payload, "cwd": cwd}
        return {"ok": True}

    monkeypatch.setattr("hotaru.app_services.session_service.SessionService.create", classmethod(fake_create))
    monkeypatch.setattr("hotaru.app_services.session_service.SessionService.list", classmethod(fake_list))
    monkeypatch.setattr("hotaru.app_services.session_service.SessionService.get", classmethod(fake_get))
    monkeypatch.setattr("hotaru.app_services.session_service.SessionService.update", classmethod(fake_update))
    monkeypatch.setattr("hotaru.app_services.session_service.SessionService.list_messages", classmethod(fake_list_messages))
    monkeypatch.setattr("hotaru.app_services.session_service.SessionService.interrupt", classmethod(fake_interrupt))
    monkeypatch.setattr("hotaru.app_services.session_service.SessionService.delete_messages", classmethod(fake_delete_messages))
    monkeypatch.setattr("hotaru.app_services.session_service.SessionService.restore_messages", classmethod(fake_restore_messages))
    monkeypatch.setattr("hotaru.app_services.session_service.SessionService.compact", classmethod(fake_compact))

    app = Server._create_app(app_ctx)
    with TestClient(app) as client:
        created = client.post("/v1/sessions", json={"project_id": "proj_1"})
        assert created.status_code == 200
        assert created.json()["id"] == "ses_1"

        listed = client.get("/v1/sessions", params={"project_id": "proj_1"})
        assert listed.status_code == 200
        assert listed.json()[0]["project_id"] == "proj_1"

        fetched = client.get("/v1/sessions/ses_1")
        assert fetched.status_code == 200
        assert fetched.json()["id"] == "ses_1"

        updated = client.patch("/v1/sessions/ses_1", json={"title": "Renamed"})
        assert updated.status_code == 200
        assert updated.json()["title"] == "Renamed"

        messages = client.get("/v1/sessions/ses_1/messages")
        assert messages.status_code == 200
        assert messages.json()[0]["id"] == "msg_1"

        interrupted = client.post("/v1/sessions/ses_1/interrupt")
        assert interrupted.status_code == 200
        assert interrupted.json()["interrupted"] is True

        deleted = client.request("DELETE", "/v1/sessions/ses_1/messages", json={"message_ids": ["m1", "m2"]})
        assert deleted.status_code == 200
        assert deleted.json()["deleted"] == 2

        restored = client.post(
            "/v1/sessions/ses_1/messages/restore",
            json={"messages": [{"info": {"id": "m1", "session_id": "ses_1"}}]},
        )
        assert restored.status_code == 200
        assert restored.json()["restored"] == 1

        compacted = client.post("/v1/sessions/ses_1/compact", json={"auto": True})
        assert compacted.status_code == 200
        assert compacted.json()["ok"] is True

    assert captured["create"]["payload"]["project_id"] == "proj_1"
    assert captured["list"]["project_id"] == "proj_1"
    assert captured["get"] == "ses_1"
    assert captured["update"]["payload"]["title"] == "Renamed"
    assert captured["list_messages"] == "ses_1"
    assert captured["interrupt"] == "ses_1"
    assert captured["delete_messages"]["payload"]["message_ids"] == ["m1", "m2"]
    assert captured["restore_messages"]["payload"]["messages"][0]["info"]["id"] == "m1"
    assert captured["compact"]["payload"]["auto"] is True


def test_v1_session_message_route_delegates_to_service(monkeypatch, app_ctx) -> None:  # type: ignore[no-untyped-def]
    captured: dict[str, Any] = {}

    async def fake_message(
        cls,
        session_id: str,
        payload: dict[str, Any],
        cwd: str,
        **_kwargs,
    ) -> dict[str, Any]:
        captured["message"] = {"session_id": session_id, "payload": payload, "cwd": cwd}
        return {"ok": True, "assistant_message_id": "msg_1", "status": "stop", "error": None}

    monkeypatch.setattr("hotaru.app_services.session_service.SessionService.message", classmethod(fake_message))

    app = Server._create_app(app_ctx)
    with TestClient(app) as client:
        response = client.post("/v1/sessions/ses_1/messages", json={"content": "hello"})
        assert response.status_code == 200
        assert response.json()["ok"] is True

    assert captured["message"]["session_id"] == "ses_1"
    assert captured["message"]["payload"]["content"] == "hello"


def test_v1_provider_and_agent_routes_delegate_to_services(monkeypatch, app_ctx) -> None:  # type: ignore[no-untyped-def]
    captured: dict[str, Any] = {}

    async def fake_list_providers(cls, cwd: str):
        captured["provider_list"] = {"cwd": cwd}
        return [{"id": "moonshot", "name": "Moonshot"}]

    async def fake_list_models(cls, provider_id: str, cwd: str):
        captured["provider_models"] = {"provider_id": provider_id, "cwd": cwd}
        return [{"id": "kimi-k2.5"}]

    async def fake_connect(cls, payload: dict[str, Any]):
        captured["provider_connect"] = payload
        return {"ok": True, "provider_id": payload["provider_id"]}

    async def fake_list_agents(cls, **_kw):
        captured["agent_list"] = True
        return [{"name": "build"}]

    monkeypatch.setattr("hotaru.app_services.provider_service.ProviderService.list", classmethod(fake_list_providers))
    monkeypatch.setattr("hotaru.app_services.provider_service.ProviderService.list_models", classmethod(fake_list_models))
    monkeypatch.setattr("hotaru.app_services.provider_service.ProviderService.connect", classmethod(fake_connect))
    monkeypatch.setattr("hotaru.app_services.agent_service.AgentService.list", classmethod(fake_list_agents))

    app = Server._create_app(app_ctx)
    with TestClient(app) as client:
        providers = client.get("/v1/providers", headers={"x-hotaru-directory": "/workspace/provider"})
        assert providers.status_code == 200
        assert providers.json()[0]["id"] == "moonshot"

        models = client.get(
            "/v1/providers/moonshot/models",
            headers={"x-hotaru-directory": "/workspace/provider"},
        )
        assert models.status_code == 200
        assert models.json()[0]["id"] == "kimi-k2.5"

        connected = client.post(
            "/v1/providers/connect",
            json={"provider_id": "moonshot", "api_key": "secret", "config": {"type": "openai", "models": {}}},
        )
        assert connected.status_code == 200
        assert connected.json()["ok"] is True

        agents = client.get("/v1/agents")
        assert agents.status_code == 200
        assert agents.json()[0]["name"] == "build"

    assert captured["provider_list"]["cwd"] == "/workspace/provider"
    assert captured["provider_models"]["provider_id"] == "moonshot"
    assert captured["provider_models"]["cwd"] == "/workspace/provider"
    assert captured["provider_connect"]["provider_id"] == "moonshot"
    assert captured["agent_list"] is True


def test_v1_preference_routes_delegate_to_service(monkeypatch, app_ctx) -> None:  # type: ignore[no-untyped-def]
    captured: dict[str, Any] = {}

    async def fake_get_current(cls):
        captured["get"] = True
        return {"agent": "build", "provider_id": "openai", "model_id": "gpt-5"}

    async def fake_update_current(cls, payload: dict[str, Any]):
        captured["update"] = payload
        return {"agent": payload.get("agent"), "provider_id": payload.get("provider_id"), "model_id": payload.get("model_id")}

    monkeypatch.setattr("hotaru.app_services.preference_service.PreferenceService.get_current", classmethod(fake_get_current))
    monkeypatch.setattr("hotaru.app_services.preference_service.PreferenceService.update_current", classmethod(fake_update_current))

    app = Server._create_app(app_ctx)
    with TestClient(app) as client:
        fetched = client.get("/v1/preferences/current")
        assert fetched.status_code == 200
        assert fetched.json()["provider_id"] == "openai"

        updated = client.patch(
            "/v1/preferences/current",
            json={"agent": "build", "provider_id": "moonshot", "model_id": "kimi-k2.5"},
        )
        assert updated.status_code == 200
        assert updated.json()["model_id"] == "kimi-k2.5"

    assert captured["get"] is True
    assert captured["update"]["provider_id"] == "moonshot"


def test_v1_mcp_routes_delegate_to_service(monkeypatch, app_ctx) -> None:  # type: ignore[no-untyped-def]
    captured: dict[str, Any] = {}

    from hotaru.mcp.mcp import MCPStatusConnected, MCPStatusNeedsAuth

    async def fake_status():
        captured["status"] = True
        return {"demo": MCPStatusNeedsAuth()}

    async def fake_connect(name: str, use_oauth: bool = False):
        captured["connect"] = {"name": name, "use_oauth": use_oauth}

    async def fake_disconnect(name: str):
        captured["disconnect"] = {"name": name}

    async def fake_supports_oauth(name: str):
        captured["supports_oauth"] = name
        return True

    async def fake_start_auth(name: str):
        captured["auth_start"] = {"name": name}
        return {"authorization_url": "https://example.com/oauth"}

    async def fake_finish_auth(name: str, code: str, state: str):
        captured["auth_callback"] = {"name": name, "code": code, "state": state}
        return MCPStatusConnected()

    async def fake_authenticate(name: str):
        captured["auth_authenticate"] = {"name": name}
        return MCPStatusConnected()

    async def fake_remove_auth(name: str):
        captured["auth_remove"] = {"name": name}

    monkeypatch.setattr(app_ctx.mcp, "status", fake_status)
    monkeypatch.setattr(app_ctx.mcp, "connect", fake_connect)
    monkeypatch.setattr(app_ctx.mcp, "disconnect", fake_disconnect)
    monkeypatch.setattr(app_ctx.mcp, "supports_oauth", fake_supports_oauth)
    monkeypatch.setattr(app_ctx.mcp, "start_auth", fake_start_auth)
    monkeypatch.setattr(app_ctx.mcp, "finish_auth", fake_finish_auth)
    monkeypatch.setattr(app_ctx.mcp, "authenticate", fake_authenticate)
    monkeypatch.setattr(app_ctx.mcp, "remove_auth", fake_remove_auth)

    app = Server._create_app(app_ctx)
    with TestClient(app) as client:
        headers = {"x-hotaru-directory": "/tmp"}
        status = client.get("/v1/mcp", headers=headers)
        assert status.status_code == 200
        assert status.json()["demo"]["status"] == "needs_auth"

        connect = client.post("/v1/mcp/demo/connect", headers=headers)
        assert connect.status_code == 200
        assert connect.json()["ok"] is True

        disconnect = client.post("/v1/mcp/demo/disconnect", headers=headers)
        assert disconnect.status_code == 200
        assert disconnect.json()["ok"] is True

        auth_start = client.post("/v1/mcp/demo/auth/start", headers=headers)
        assert auth_start.status_code == 200
        assert auth_start.json()["authorization_url"] == "https://example.com/oauth"

        auth_callback = client.post(
            "/v1/mcp/demo/auth/callback",
            json={"code": "abc", "state": "def"},
            headers=headers,
        )
        assert auth_callback.status_code == 200
        assert auth_callback.json()["status"] == "connected"

        auth_authenticate = client.post("/v1/mcp/demo/auth/authenticate", headers=headers)
        assert auth_authenticate.status_code == 200
        assert auth_authenticate.json()["status"] == "connected"

        auth_remove = client.delete("/v1/mcp/demo/auth", headers=headers)
        assert auth_remove.status_code == 200
        assert auth_remove.json()["ok"] is True

    assert captured["connect"]["name"] == "demo"
    assert captured["connect"]["use_oauth"] is True
    assert captured["disconnect"]["name"] == "demo"
    assert captured["auth_start"]["name"] == "demo"
    assert captured["auth_callback"]["code"] == "abc"
    assert captured["auth_callback"]["state"] == "def"
    assert captured["auth_authenticate"]["name"] == "demo"
    assert captured["auth_remove"]["name"] == "demo"


def test_v1_agent_route_accepts_null_description(monkeypatch, app_ctx) -> None:  # type: ignore[no-untyped-def]
    async def fake_agent_list(cls, **_kw):
        return [
            AgentInfo(
                name="compaction",
                description=None,
                mode=AgentMode.PRIMARY,
                hidden=True,
            )
        ]

    monkeypatch.setattr("hotaru.agent.agent.Agent.list", fake_agent_list)

    app = Server._create_app(app_ctx)
    with TestClient(app) as client:
        agents = client.get("/v1/agents")
        assert agents.status_code == 200
        payload = agents.json()
        assert payload[0]["name"] == "compaction"
        assert payload[0]["description"] == ""


def test_v1_permission_question_and_event_routes_delegate_to_services(monkeypatch, app_ctx) -> None:  # type: ignore[no-untyped-def]
    captured: dict[str, Any] = {}

    async def fake_permission_list(cls, _app):
        return [{"id": "per_1"}]

    async def fake_permission_reply(cls, _app, request_id: str, payload: dict[str, Any]):
        captured["permission_reply"] = {"request_id": request_id, "payload": payload}
        return True

    async def fake_question_list(cls, _app):
        return [{"id": "q_1"}]

    async def fake_question_reply(cls, _app, request_id: str, payload: dict[str, Any]):
        captured["question_reply"] = {"request_id": request_id, "payload": payload}
        return True

    async def fake_question_reject(cls, _app, request_id: str):
        captured["question_reject"] = request_id
        return True

    async def fake_events(cls, bus) -> AsyncIterator[dict[str, Any]]:  # type: ignore[no-untyped-def]
        yield {"type": "server.connected", "data": {"healthy": True}}

    monkeypatch.setattr("hotaru.app_services.permission_service.PermissionService.list", classmethod(fake_permission_list))
    monkeypatch.setattr("hotaru.app_services.permission_service.PermissionService.reply", classmethod(fake_permission_reply))
    monkeypatch.setattr("hotaru.app_services.question_service.QuestionService.list", classmethod(fake_question_list))
    monkeypatch.setattr("hotaru.app_services.question_service.QuestionService.reply", classmethod(fake_question_reply))
    monkeypatch.setattr("hotaru.app_services.question_service.QuestionService.reject", classmethod(fake_question_reject))
    monkeypatch.setattr("hotaru.app_services.event_service.EventService.stream", classmethod(fake_events))

    app = Server._create_app(app_ctx)
    with TestClient(app) as client:
        permissions = client.get("/v1/permissions")
        assert permissions.status_code == 200
        assert permissions.json()[0]["id"] == "per_1"

        permission_reply = client.post("/v1/permissions/per_1/reply", json={"reply": "once"})
        assert permission_reply.status_code == 200
        assert permission_reply.json() is True

        questions = client.get("/v1/questions")
        assert questions.status_code == 200
        assert questions.json()[0]["id"] == "q_1"

        question_reply = client.post("/v1/questions/q_1/reply", json={"answers": [["Yes"]]})
        assert question_reply.status_code == 200
        assert question_reply.json() is True

        question_reject = client.post("/v1/questions/q_1/reject")
        assert question_reject.status_code == 200
        assert question_reject.json() is True

        with client.stream("GET", "/v1/events") as response:
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
