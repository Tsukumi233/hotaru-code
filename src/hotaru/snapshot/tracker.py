"""Git-backed workspace snapshot tracking."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from ..core.config import ConfigManager
from ..core.global_paths import GlobalPath
from ..util.log import Log

log = Log.create({"service": "snapshot"})


@dataclass(frozen=True)
class PatchResult:
    """Patch listing for a tracked baseline snapshot."""

    hash: str
    files: List[str]


class SnapshotTracker:
    """Track and diff workspace trees using an isolated git dir."""

    @classmethod
    async def track(cls, *, session_id: str, cwd: str, worktree: str) -> Optional[str]:
        """Record the current workspace tree and return the tree hash."""
        if not await cls._enabled():
            return None
        if not cls._is_git_workspace(worktree):
            return None

        git_dir = cls._git_dir(session_id=session_id)
        initialized = await cls._initialize_repo(git_dir=git_dir, worktree=worktree, cwd=cwd)
        if not initialized:
            return None

        await cls._add_all(git_dir=git_dir, worktree=worktree, cwd=cwd)
        result = await cls._run_git(
            ["write-tree"],
            git_dir=git_dir,
            worktree=worktree,
            cwd=cwd,
        )
        if result is None or result.exit_code != 0:
            return None
        value = result.stdout.strip()
        return value or None

    @classmethod
    async def patch(cls, *, session_id: str, base_hash: str, cwd: str, worktree: str) -> PatchResult:
        """Return changed files against a previously tracked hash."""
        if not base_hash:
            return PatchResult(hash=base_hash, files=[])
        if not await cls._enabled():
            return PatchResult(hash=base_hash, files=[])
        if not cls._is_git_workspace(worktree):
            return PatchResult(hash=base_hash, files=[])

        git_dir = cls._git_dir(session_id=session_id)
        if not git_dir.exists():
            return PatchResult(hash=base_hash, files=[])

        await cls._add_all(git_dir=git_dir, worktree=worktree, cwd=cwd)
        result = await cls._run_git(
            ["-c", "core.quotepath=false", "diff", "--no-ext-diff", "--name-only", base_hash, "--", "."],
            git_dir=git_dir,
            worktree=worktree,
            cwd=cwd,
        )
        if result is None or result.exit_code != 0:
            return PatchResult(hash=base_hash, files=[])

        files: List[str] = []
        for line in result.stdout.splitlines():
            rel = line.strip()
            if not rel:
                continue
            files.append(str((Path(worktree) / rel).resolve()))
        return PatchResult(hash=base_hash, files=files)

    @classmethod
    async def diff(
        cls,
        *,
        session_id: str,
        from_hash: str,
        to_hash: Optional[str],
        cwd: str,
        worktree: str,
    ) -> str:
        """Return unified diff text between two snapshots (or from snapshot to current)."""
        if not from_hash:
            return ""
        if not await cls._enabled():
            return ""
        if not cls._is_git_workspace(worktree):
            return ""

        git_dir = cls._git_dir(session_id=session_id)
        if not git_dir.exists():
            return ""

        await cls._add_all(git_dir=git_dir, worktree=worktree, cwd=cwd)
        args = ["-c", "core.quotepath=false", "diff", "--no-ext-diff", from_hash]
        if to_hash:
            args.append(to_hash)
        args.extend(["--", "."])
        result = await cls._run_git(
            args,
            git_dir=git_dir,
            worktree=worktree,
            cwd=cwd,
        )
        if result is None or result.exit_code != 0:
            return ""
        return result.stdout.strip()

    @staticmethod
    async def _enabled() -> bool:
        try:
            cfg = await ConfigManager.get()
            if getattr(cfg, "snapshot", None) is False:
                return False
        except Exception:
            # Best effort: keep snapshot tracking enabled when config lookup fails.
            return True
        return True

    @staticmethod
    def _is_git_workspace(worktree: str) -> bool:
        root = Path(worktree).resolve()
        for candidate in [root, *root.parents]:
            if (candidate / ".git").exists():
                return True
        return False

    @staticmethod
    def _git_dir(*, session_id: str) -> Path:
        return Path(GlobalPath.data()) / "snapshot" / session_id

    @classmethod
    async def _initialize_repo(cls, *, git_dir: Path, worktree: str, cwd: str) -> bool:
        git_dir.mkdir(parents=True, exist_ok=True)
        if (git_dir / "HEAD").exists():
            return True

        env = {
            "GIT_DIR": str(git_dir),
            "GIT_WORK_TREE": str(Path(worktree).resolve()),
        }
        init_result = await cls._run(
            ["git", "init", "--quiet"],
            cwd=worktree,
            env=env,
        )
        if init_result is None or init_result.exit_code != 0:
            log.warn("snapshot init failed", {"cwd": cwd, "worktree": worktree})
            return False

        await cls._run_git(
            ["config", "core.autocrlf", "false"],
            git_dir=git_dir,
            worktree=worktree,
            cwd=cwd,
        )
        return True

    @classmethod
    async def _add_all(cls, *, git_dir: Path, worktree: str, cwd: str) -> None:
        await cls._run_git(
            ["add", "-A", "."],
            git_dir=git_dir,
            worktree=worktree,
            cwd=cwd,
        )

    @classmethod
    async def _run_git(
        cls,
        args: List[str],
        *,
        git_dir: Path,
        worktree: str,
        cwd: str,
    ) -> Optional["_RunResult"]:
        cmd = ["git", f"--git-dir={git_dir}", f"--work-tree={Path(worktree).resolve()}", *args]
        return await cls._run(cmd, cwd=cwd, env=None)

    @staticmethod
    async def _run(
        cmd: List[str],
        *,
        cwd: str,
        env: Optional[dict[str, str]],
    ) -> Optional["_RunResult"]:
        full_env = os.environ.copy()
        if env:
            full_env.update(env)
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=cwd,
                env=full_env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except (FileNotFoundError, OSError):
            return None

        stdout_bytes, stderr_bytes = await proc.communicate()
        return _RunResult(
            exit_code=int(proc.returncode or 0),
            stdout=stdout_bytes.decode("utf-8", errors="replace"),
            stderr=stderr_bytes.decode("utf-8", errors="replace"),
        )


@dataclass(frozen=True)
class _RunResult:
    exit_code: int
    stdout: str
    stderr: str
