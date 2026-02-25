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
from typing import Awaitable, Callable, Literal

from pydantic import BaseModel
from fastapi.websockets import WebSocket

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


def _meta(cursor: int) -> bytes:
    """Build a WebSocket control frame: 0x00 + JSON cursor payload."""
    return b"\x00" + json.dumps({"cursor": cursor}).encode()


class PtyManager:
    def __init__(self) -> None:
        self._sessions: dict[str, _Session] = {}
        self._lock = asyncio.Lock()
        self._counter = 0

    async def _send(self, sid: str, ws: WebSocket, data: bytes) -> None:
        try:
            await ws.send_bytes(data)
            return
        except Exception:
            pass
        await self._disconnect(sid, ws)

    async def _handle_read(self, sid: str) -> None:
        data = b""
        sockets: list[WebSocket] = []
        async with self._lock:
            session = self._sessions.get(sid)
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
            sockets = list(session.subscribers)
            session.buffer += chunk
            if len(session.buffer) > BUFFER_LIMIT:
                excess = len(session.buffer) - BUFFER_LIMIT
                session.buffer = session.buffer[excess:]
                session.buffer_cursor += excess

        for ws in sockets:
            asyncio.create_task(self._send(sid, ws, data))

    def _on_read(self, sid: str) -> None:
        asyncio.create_task(self._handle_read(sid))

    def _cleanup(self, session: _Session) -> None:
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

    def _resize(self, session: _Session, cols: int, rows: int) -> None:
        if session.info.status != "running":
            return
        fcntl.ioctl(
            session.master_fd,
            termios.TIOCSWINSZ,
            struct.pack("HHHH", rows, cols, 0, 0),
        )

    async def _disconnect(self, sid: str, ws: WebSocket) -> None:
        async with self._lock:
            session = self._sessions.get(sid)
            if not session:
                return
            session.subscribers.pop(ws, None)

    async def create(self, input: PtyCreateInput) -> PtyInfo:
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
        async with self._lock:
            self._sessions[sid] = session

        loop = asyncio.get_event_loop()
        loop.add_reader(master, self._on_read, sid)

        async def _wait() -> None:
            code = await loop.run_in_executor(None, process.wait)
            log.info("pty exited", {"id": sid, "exit_code": code})
            session.info.status = "exited"
            async with self._lock:
                self._cleanup(session)
                sockets = list(session.subscribers)
                session.subscribers.clear()
                self._sessions.pop(sid, None)

            for ws in sockets:
                try:
                    await ws.close()
                except Exception:
                    pass
            await Bus.publish(Event["Exited"], _ExitProps(id=sid, exit_code=code))

        asyncio.create_task(_wait())
        await Bus.publish(Event["Created"], _InfoProps(info=info.model_dump()))
        return info

    def list(self) -> list[PtyInfo]:
        return [s.info for s in self._sessions.values()]

    def get(self, sid: str) -> PtyInfo | None:
        session = self._sessions.get(sid)
        return session.info if session else None

    async def update(self, sid: str, input: PtyUpdateInput) -> PtyInfo | None:
        async with self._lock:
            session = self._sessions.get(sid)
            if not session:
                return None
            if input.title:
                session.info.title = input.title
            if input.size:
                self._resize(session, input.size["cols"], input.size["rows"])
            info = session.info.model_dump()
        await Bus.publish(Event["Updated"], _InfoProps(info=info))
        return session.info

    async def remove(self, sid: str) -> None:
        async with self._lock:
            session = self._sessions.get(sid)
            if not session:
                return
            log.info("removing pty", {"id": sid})
            try:
                session.process.kill()
            except ProcessLookupError:
                pass
            self._cleanup(session)
            sockets = list(session.subscribers)
            session.subscribers.clear()
            self._sessions.pop(sid, None)

        for ws in sockets:
            try:
                await ws.close()
            except Exception:
                pass
        await Bus.publish(Event["Deleted"], _IdProps(id=sid))

    def resize(self, sid: str, cols: int, rows: int) -> None:
        session = self._sessions.get(sid)
        if not session:
            return
        self._resize(session, cols, rows)

    def write(self, sid: str, data: str) -> None:
        session = self._sessions.get(sid)
        if session and session.info.status == "running":
            os.write(session.master_fd, data.encode())

    async def connect(self, sid: str, ws: WebSocket, cursor: int = 0) -> Callable[[], Awaitable[None]]:
        """Attach a WebSocket to a PTY session, replay buffer, return cleanup fn."""
        replay = b""
        end = 0
        session: _Session | None = None
        async with self._lock:
            session = self._sessions.get(sid)
            if not session:
                session_missing = True
            else:
                session_missing = False
                log.info("ws connected", {"id": sid})
                self._counter += 1
                session.subscribers[ws] = self._counter
                start = session.buffer_cursor
                end = session.cursor
                replay_from = end if cursor == -1 else max(0, cursor)
                if session.buffer and replay_from < end:
                    offset = max(0, replay_from - start)
                    if offset < len(session.buffer):
                        replay = session.buffer[offset:].encode("utf-8", errors="replace")

        if session_missing:
            await ws.close()
            async def noop() -> None:
                return None

            return noop

        for i in range(0, len(replay), BUFFER_CHUNK):
            await ws.send_bytes(replay[i : i + BUFFER_CHUNK])
        await ws.send_bytes(_meta(end))

        async def cleanup() -> None:
            log.info("ws disconnected", {"id": sid})
            await self._disconnect(sid, ws)

        return cleanup


_manager = PtyManager()


# --- Public API ---

class Pty:

    @staticmethod
    async def create(input: PtyCreateInput) -> PtyInfo:
        return await _manager.create(input)

    @staticmethod
    def list() -> list[PtyInfo]:
        return _manager.list()

    @staticmethod
    def get(sid: str) -> PtyInfo | None:
        return _manager.get(sid)

    @staticmethod
    async def update(sid: str, input: PtyUpdateInput) -> PtyInfo | None:
        return await _manager.update(sid, input)

    @staticmethod
    async def remove(sid: str) -> None:
        await _manager.remove(sid)

    @staticmethod
    def resize(sid: str, cols: int, rows: int) -> None:
        _manager.resize(sid, cols, rows)

    @staticmethod
    def write(sid: str, data: str) -> None:
        _manager.write(sid, data)

    @staticmethod
    async def connect(sid: str, ws: WebSocket, cursor: int = 0) -> Callable[[], Awaitable[None]]:
        return await _manager.connect(sid, ws, cursor)
