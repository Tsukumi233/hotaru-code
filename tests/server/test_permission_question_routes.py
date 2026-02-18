from starlette.testclient import TestClient

from hotaru.permission.permission import PermissionRequest
from hotaru.question.question import QuestionInfo, QuestionOption, QuestionRequest
from hotaru.server.server import Server


def test_permission_routes_list_and_reply(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    captured: dict[str, str] = {}

    async def fake_list_pending(cls):  # type: ignore[no-untyped-def]
        return [
            PermissionRequest(
                id="per_1",
                session_id="ses_1",
                permission="bash",
                patterns=["git status"],
                metadata={"command": "git status"},
                always=["git *"],
                tool={"message_id": "msg_1", "call_id": "call_1"},
            )
        ]

    async def fake_reply(cls, request_id: str, reply, message=None):  # type: ignore[no-untyped-def]
        captured["request_id"] = request_id
        captured["reply"] = str(reply.value if hasattr(reply, "value") else reply)
        if message:
            captured["message"] = message

    monkeypatch.setattr("hotaru.permission.permission.Permission.list_pending", classmethod(fake_list_pending))
    monkeypatch.setattr("hotaru.permission.permission.Permission.reply", classmethod(fake_reply))

    app = Server._create_app()
    with TestClient(app) as client:
        listed = client.get("/v1/permission")
        assert listed.status_code == 200
        payload = listed.json()
        assert len(payload) == 1
        assert payload[0]["id"] == "per_1"
        assert payload[0]["tool"] == {"message_id": "msg_1", "call_id": "call_1"}

        replied = client.post("/v1/permission/per_1/reply", json={"reply": "always", "message": "approved"})
        assert replied.status_code == 200
        assert replied.json() is True

    assert captured == {
        "request_id": "per_1",
        "reply": "always",
        "message": "approved",
    }


def test_question_routes_list_reply_and_reject(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    captured: dict[str, object] = {}

    async def fake_list_pending(cls):  # type: ignore[no-untyped-def]
        return [
            QuestionRequest(
                id="q_1",
                session_id="ses_1",
                questions=[
                    QuestionInfo(
                        question="Proceed?",
                        header="Confirm",
                        options=[
                            QuestionOption(label="Yes", description="Continue"),
                            QuestionOption(label="No", description="Stop"),
                        ],
                    )
                ],
            )
        ]

    async def fake_reply(cls, request_id: str, answers):  # type: ignore[no-untyped-def]
        captured["reply_request_id"] = request_id
        captured["answers"] = answers

    async def fake_reject(cls, request_id: str):  # type: ignore[no-untyped-def]
        captured["reject_request_id"] = request_id

    monkeypatch.setattr("hotaru.question.question.Question.list_pending", classmethod(fake_list_pending))
    monkeypatch.setattr("hotaru.question.question.Question.reply", classmethod(fake_reply))
    monkeypatch.setattr("hotaru.question.question.Question.reject", classmethod(fake_reject))

    app = Server._create_app()
    with TestClient(app) as client:
        listed = client.get("/v1/question")
        assert listed.status_code == 200
        payload = listed.json()
        assert len(payload) == 1
        assert payload[0]["id"] == "q_1"

        replied = client.post("/v1/question/q_1/reply", json={"answers": [["Yes"]]})
        assert replied.status_code == 200
        assert replied.json() is True

        rejected = client.post("/v1/question/q_1/reject")
        assert rejected.status_code == 200
        assert rejected.json() is True

    assert captured["reply_request_id"] == "q_1"
    assert captured["answers"] == [["Yes"]]
    assert captured["reject_request_id"] == "q_1"
