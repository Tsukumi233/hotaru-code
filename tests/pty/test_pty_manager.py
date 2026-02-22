import asyncio
import subprocess
from typing import cast

import pytest

from hotaru.pty import pty as pty_mod


class _Ws:
    def __init__(self) -> None:
        self.sent: list[bytes] = []
        self.closed = False

    async def send_bytes(self, data: bytes) -> None:
        self.sent.append(data)

    async def close(self) -> None:
        self.closed = True


class _Proc:
    pid = 7


def _session(sid: str) -> pty_mod._Session:
    info = pty_mod.PtyInfo(
        id=sid,
        title="t",
        command="sh",
        args=[],
        cwd="/tmp",
        status="running",
        pid=7,
    )
    proc = cast(subprocess.Popen[bytes], _Proc())
    return pty_mod._Session(info=info, process=proc, master_fd=0, buffer="abc", cursor=3)


def test_manager_state_is_instance_scoped() -> None:
    a = pty_mod.PtyManager()
    b = pty_mod.PtyManager()
    assert isinstance(a._lock, asyncio.Lock)
    assert a._sessions is not b._sessions


@pytest.mark.anyio
async def test_manager_connect_assigns_unique_subscriber_ids() -> None:
    sid = "pty_1"
    m = pty_mod.PtyManager()
    m._sessions[sid] = _session(sid)
    a = _Ws()
    b = _Ws()

    clean_a, clean_b = await asyncio.gather(
        m.connect(sid, a),  # type: ignore[arg-type]
        m.connect(sid, b),  # type: ignore[arg-type]
    )
    subs = m._sessions[sid].subscribers
    assert subs[a] != subs[b]

    await clean_a()
    assert a not in subs
    assert b in subs

    await clean_b()
    assert not subs
