"""PTY transport routes."""

from __future__ import annotations

from fastapi import APIRouter, Body, WebSocket
from starlette.websockets import WebSocketDisconnect

from ...pty import Pty, PtyCreateInput, PtyInfo, PtyUpdateInput
from ..schemas import SessionDeleteResponse

router = APIRouter(prefix="/v1/ptys", tags=["ptys"])


@router.get("", response_model=list[PtyInfo])
async def list_ptys() -> list[PtyInfo]:
    return Pty.list()


@router.post("", response_model=PtyInfo)
async def create_pty(payload: PtyCreateInput | None = Body(default=None)) -> PtyInfo:
    return await Pty.create(payload or PtyCreateInput())


@router.get("/{pty_id}", response_model=PtyInfo)
async def get_pty(pty_id: str) -> PtyInfo:
    info = Pty.get(pty_id)
    if not info:
        raise KeyError("PTY session not found")
    return info


@router.put("/{pty_id}", response_model=PtyInfo)
async def update_pty(pty_id: str, payload: PtyUpdateInput = Body(...)) -> PtyInfo:
    info = await Pty.update(pty_id, payload)
    if not info:
        raise KeyError("PTY session not found")
    return info


@router.delete("/{pty_id}", response_model=SessionDeleteResponse)
async def delete_pty(pty_id: str) -> SessionDeleteResponse:
    await Pty.remove(pty_id)
    return SessionDeleteResponse(ok=True)


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
        cleanup()
