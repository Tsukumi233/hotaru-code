"""PTY pseudo-terminal session management.

Provides interactive terminal sessions via PTY with WebSocket streaming,
buffer management, and resize support. Port of opencode's bun-pty module.
"""

import asyncio
import fcntl
import json
import os
import pty as pty_mod
import struct
import subprocess
import termios
from dataclasses import dataclass, field
from typing import Callable, Literal

from pydantic import BaseModel
from starlette.websockets import WebSocket

from ..core.bus import Bus, BusEvent
from ..core.id import Identifier
from ..shell import Shell
from ..util.log import Log

log = Log.create({"service": "pty"})

BUFFER_LIMIT = 2 * 1024 * 1024
BUFFER_CHUNK = 64 * 1024


# --- Models ---

class PtyInfo(BaseModel):
    id: str
    title: str
    command: str
    args: list[str]
    cwd: str
    status: Literal["running", "exited"]
    pid: int


class PtyCreateInput(BaseModel):
    command: str | None = None
    args: list[str] | None = None
    cwd: str | None = None
    title: str | None = None
    env: dict[str, str] | None = None


class PtyUpdateInput(BaseModel):
    title: str | None = None
    size: dict[str, int] | None = None  # {"cols": N, "rows": N}


# --- Bus Events ---

class _InfoProps(BaseModel):
    info: dict[str, object]


class _IdProps(BaseModel):
    id: str


class _ExitProps(BaseModel):
    id: str
    exit_code: int


Event = {
    "Created": BusEvent.define("pty.created", _InfoProps),
    "Updated": BusEvent.define("pty.updated", _InfoProps),
    "Exited": BusEvent.define("pty.exited", _ExitProps),
    "Deleted": BusEvent.define("pty.deleted", _IdProps),
}


# --- Internal State ---

@dataclass
class _Session:
    info: PtyInfo
    process: subprocess.Popen[bytes]
    master_fd: int
    buffer: str = ""
    buffer_cursor: int = 0
    cursor: int = 0
    subscribers: dict[WebSocket, int] = field(default_factory=dict)
    closed: bool = False


_sessions: dict[str, _Session] = {}
_sub_counter = 0


def _meta(cursor: int) -> bytes:
    """Build a WebSocket control frame: 0x00 + JSON cursor payload."""
    return b"\x00" + json.dumps({"cursor": cursor}).encode()


async def _send(session: _Session, ws: WebSocket, data: bytes) -> None:
    try:
        await ws.send_bytes(data)
    except Exception:
        session.subscribers.pop(ws, None)


def _on_read(sid: str) -> None:
    """Callback for asyncio add_reader — reads PTY output and broadcasts."""
    session = _sessions.get(sid)
    if not session or session.closed:
        return
    try:
        data = os.read(session.master_fd, 65536)
    except OSError:
        return
    if not data:
        return

    chunk = data.decode("utf-8", errors="replace")
    session.cursor += len(chunk)

    for ws in list(session.subscribers):
        asyncio.ensure_future(_send(session, ws, data))

    session.buffer += chunk
    if len(session.buffer) > BUFFER_LIMIT:
        excess = len(session.buffer) - BUFFER_LIMIT
        session.buffer = session.buffer[excess:]
        session.buffer_cursor += excess


def _cleanup(session: _Session) -> None:
    """Remove reader and close master fd (idempotent)."""
    if session.closed:
        return
    session.closed = True
    try:
        asyncio.get_event_loop().remove_reader(session.master_fd)
    except Exception:
        pass
    try:
        os.close(session.master_fd)
    except OSError:
        pass


# --- Public API ---

class Pty:

    @staticmethod
    async def create(input: PtyCreateInput) -> PtyInfo:
        sid = Identifier.ascending("pty")
        command = input.command or Shell.preferred()
        args = list(input.args or [])
        if command.endswith("sh"):
            args.append("-l")

        cwd = input.cwd or os.getcwd()
        env = {
            **os.environ,
            **(input.env or {}),
            "TERM": "xterm-256color",
            "HOTARU_TERMINAL": "1",
        }

        log.info("creating pty", {"id": sid, "command": command, "cwd": cwd})

        master, slave = pty_mod.openpty()
        process = subprocess.Popen(
            [command, *args],
            stdin=slave,
            stdout=slave,
            stderr=slave,
            cwd=cwd,
            env=env,
            start_new_session=True,
        )
        os.close(slave)

        info = PtyInfo(
            id=sid,
            title=input.title or f"Terminal {sid[-4:]}",
            command=command,
            args=args,
            cwd=cwd,
            status="running",
            pid=process.pid,
        )
        session = _Session(info=info, process=process, master_fd=master)
        _sessions[sid] = session

        loop = asyncio.get_event_loop()
        loop.add_reader(master, _on_read, sid)

        async def _wait():
            code = await loop.run_in_executor(None, process.wait)
            log.info("pty exited", {"id": sid, "exit_code": code})
            session.info.status = "exited"
            _cleanup(session)
            for ws in list(session.subscribers):
                try:
                    await ws.close()
                except Exception:
                    pass
            session.subscribers.clear()
            await Bus.publish(Event["Exited"], _ExitProps(id=sid, exit_code=code))
            _sessions.pop(sid, None)

        asyncio.create_task(_wait())
        await Bus.publish(Event["Created"], _InfoProps(info=info.model_dump()))
        return info

    @staticmethod
    def list() -> list[PtyInfo]:
        return [s.info for s in _sessions.values()]

    @staticmethod
    def get(sid: str) -> PtyInfo | None:
        session = _sessions.get(sid)
        return session.info if session else None

    @staticmethod
    async def update(sid: str, input: PtyUpdateInput) -> PtyInfo | None:
        session = _sessions.get(sid)
        if not session:
            return None
        if input.title:
            session.info.title = input.title
        if input.size:
            Pty.resize(sid, input.size["cols"], input.size["rows"])
        await Bus.publish(Event["Updated"], _InfoProps(info=session.info.model_dump()))
        return session.info

    @staticmethod
    async def remove(sid: str) -> None:
        session = _sessions.get(sid)
        if not session:
            return
        log.info("removing pty", {"id": sid})
        try:
            session.process.kill()
        except ProcessLookupError:
            pass
        _cleanup(session)
        for ws in list(session.subscribers):
            try:
                await ws.close()
            except Exception:
                pass
        session.subscribers.clear()
        _sessions.pop(sid, None)
        await Bus.publish(Event["Deleted"], _IdProps(id=sid))

    @staticmethod
    def resize(sid: str, cols: int, rows: int) -> None:
        session = _sessions.get(sid)
        if session and session.info.status == "running":
            fcntl.ioctl(
                session.master_fd,
                termios.TIOCSWINSZ,
                struct.pack("HHHH", rows, cols, 0, 0),
            )

    @staticmethod
    def write(sid: str, data: str) -> None:
        session = _sessions.get(sid)
        if session and session.info.status == "running":
            os.write(session.master_fd, data.encode())

    @staticmethod
    async def connect(sid: str, ws: WebSocket, cursor: int = 0) -> Callable[[], None]:
        """Attach a WebSocket to a PTY session, replay buffer, return cleanup fn."""
        global _sub_counter
        session = _sessions.get(sid)
        if not session:
            await ws.close()
            return lambda: None

        log.info("ws connected", {"id": sid})
        _sub_counter += 1
        session.subscribers[ws] = _sub_counter

        start = session.buffer_cursor
        end = session.cursor
        replay_from = end if cursor == -1 else max(0, cursor)

        if session.buffer and replay_from < end:
            offset = max(0, replay_from - start)
            if offset < len(session.buffer):
                encoded = session.buffer[offset:].encode("utf-8", errors="replace")
                for i in range(0, len(encoded), BUFFER_CHUNK):
                    await ws.send_bytes(encoded[i : i + BUFFER_CHUNK])

        await ws.send_bytes(_meta(end))

        def cleanup() -> None:
            log.info("ws disconnected", {"id": sid})
            session.subscribers.pop(ws, None)

        return cleanup
