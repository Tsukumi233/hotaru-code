"""PTY transport routes."""

from __future__ import annotations

from fastapi import Body, WebSocket
from starlette.websockets import WebSocketDisconnect

from ...app_services.errors import NotFoundError
from ...pty import Pty, PtyCreateInput, PtyInfo, PtyUpdateInput
from ..schemas import SessionDeleteResponse
from .crud import crud_router, many, one


async def list_ptys() -> list[PtyInfo]:
    return Pty.list()


async def create_pty(payload: PtyCreateInput | None = Body(default=None)) -> PtyInfo:
    return await Pty.create(payload or PtyCreateInput())


async def get_pty(pty_id: str) -> PtyInfo:
    info = Pty.get(pty_id)
    if not info:
        raise NotFoundError("PTY session", pty_id)
    return info


async def update_pty(pty_id: str, payload: PtyUpdateInput = Body(...)) -> PtyInfo:
    info = await Pty.update(pty_id, payload)
    if not info:
        raise NotFoundError("PTY session", pty_id)
    return info


async def delete_pty(pty_id: str) -> SessionDeleteResponse:
    await Pty.remove(pty_id)
    return SessionDeleteResponse(ok=True)


router = crud_router(
    prefix="/v1/ptys",
    tags=["ptys"],
    routes=[
        many("GET", "", PtyInfo, list_ptys),
        one("POST", "", PtyInfo, create_pty),
        one("GET", "/{pty_id}", PtyInfo, get_pty),
        one("PUT", "/{pty_id}", PtyInfo, update_pty),
        one("DELETE", "/{pty_id}", SessionDeleteResponse, delete_pty),
    ],
)


@router.websocket("/{pty_id}/connect")
async def pty_ws(websocket: WebSocket, pty_id: str) -> None:
    await websocket.accept()
    cursor = int(websocket.query_params.get("cursor", "0"))
    cleanup = await Pty.connect(pty_id, websocket, cursor)
    try:
        while True:
            msg = await websocket.receive()
            if msg["type"] == "websocket.disconnect":
                break
            if "text" in msg:
                Pty.write(pty_id, msg["text"])
    except WebSocketDisconnect:
        pass
    finally:
        await cleanup()
