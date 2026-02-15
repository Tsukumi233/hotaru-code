"""Project detection and management.

Detects project boundaries from git repositories and manages project metadata.
"""

import asyncio
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict

from ..core.bus import Bus, BusEvent
from ..storage import NotFoundError, Storage
from ..util.log import Log

log = Log.create({"service": "project"})


class ProjectIcon(BaseModel):
    """Project icon configuration."""
    url: Optional[str] = None
    override: Optional[str] = None
    color: Optional[str] = None


class ProjectCommands(BaseModel):
    """Project command configuration."""
    start: Optional[str] = None


class ProjectTime(BaseModel):
    """Project timestamps."""
    created: int
    updated: int
    initialized: Optional[int] = None


class ProjectInfo(BaseModel):
    """Project information schema."""
    id: str
    worktree: str
    vcs: Optional[Literal["git"]] = None
    name: Optional[str] = None
    icon: Optional[ProjectIcon] = None
    commands: Optional[ProjectCommands] = None
    time: ProjectTime
    sandboxes: List[str] = field(default_factory=list)

    model_config = ConfigDict(extra="allow")


# Project events
class ProjectUpdatedEvent(BaseModel):
    """Event data for project updates."""
    project: ProjectInfo


ProjectUpdated = BusEvent(
    event_type="project.updated",
    properties_type=ProjectInfo
)


async def _run_git_command(cmd: List[str], cwd: str) -> Optional[str]:
    """Run a git command and return output, or None on failure."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        if proc.returncode == 0:
            return stdout.decode().strip()
        return None
    except Exception:
        return None


def _find_git_dir(start: str) -> Optional[str]:
    """Find .git directory by walking up from start."""
    current = Path(start).resolve()

    while current != current.parent:
        git_path = current / ".git"
        if git_path.exists():
            return str(git_path)
        current = current.parent

    # Check root
    git_path = current / ".git"
    if git_path.exists():
        return str(git_path)

    return None


class Project:
    """Project detection and management.

    Projects are identified by their git root commit hash, allowing
    tracking across worktrees and directory moves.
    """

    _initialized_projects: Dict[str, int] = {}
    _command_event_subscription_started: bool = False

    @staticmethod
    def _project_key(project_id: str) -> List[str]:
        return ["project", project_id]

    @classmethod
    def ensure_command_event_subscription(cls) -> None:
        """Subscribe once to command-executed events."""
        if cls._command_event_subscription_started:
            return

        from ..command import CommandEvent

        async def _on_command_executed(payload) -> None:
            name = payload.properties.get("name")
            project_id = payload.properties.get("project_id")

            if name != "init":
                return
            if not isinstance(project_id, str) or not project_id:
                return

            await cls.set_initialized(project_id)

        Bus.subscribe(CommandEvent.Executed, _on_command_executed)
        cls._command_event_subscription_started = True

    @staticmethod
    async def from_directory(directory: str) -> tuple["ProjectInfo", str]:
        """Detect project from a directory.

        Args:
            directory: Starting directory to search from

        Returns:
            Tuple of (ProjectInfo, sandbox_directory)
        """
        log.info("from_directory", {"directory": directory})
        Project.ensure_command_event_subscription()

        git_dir = _find_git_dir(directory)

        if git_dir:
            sandbox = str(Path(git_dir).parent)

            # Try to read cached project ID
            opencode_file = Path(git_dir) / "opencode"
            project_id: Optional[str] = None

            if opencode_file.exists():
                try:
                    project_id = opencode_file.read_text().strip()
                except Exception:
                    pass

            # Generate ID from root commit if not cached
            if not project_id:
                roots_output = await _run_git_command(
                    ["git", "rev-list", "--max-parents=0", "--all"],
                    sandbox
                )

                if roots_output:
                    roots = sorted([r.strip() for r in roots_output.split("\n") if r.strip()])
                    if roots:
                        project_id = roots[0]
                        # Cache the ID
                        try:
                            opencode_file.write_text(project_id)
                        except Exception:
                            pass

            if not project_id:
                project_id = "global"
                vcs = None
            else:
                vcs = "git"

            # Get the actual worktree root
            toplevel = await _run_git_command(
                ["git", "rev-parse", "--show-toplevel"],
                sandbox
            )
            if toplevel:
                sandbox = str(Path(sandbox).resolve() / Path(toplevel).name if not Path(toplevel).is_absolute() else toplevel)
                sandbox = toplevel

            # Get common git dir for worktree detection
            common_dir = await _run_git_command(
                ["git", "rev-parse", "--git-common-dir"],
                sandbox
            )
            worktree = sandbox
            if common_dir and common_dir != ".":
                parent = Path(common_dir).parent
                if str(parent) != ".":
                    worktree = str(parent)
        else:
            # No git repository found
            project_id = "global"
            worktree = "/"
            sandbox = "/"
            vcs = None

        now = int(time.time() * 1000)

        # Load persisted project info if present
        project: ProjectInfo
        try:
            stored = await Storage.read(Project._project_key(project_id))
            project = ProjectInfo.model_validate(stored)
        except NotFoundError:
            project = ProjectInfo(
                id=project_id,
                worktree=worktree,
                vcs=vcs,
                sandboxes=[],
                time=ProjectTime(
                    created=now,
                    updated=now,
                    initialized=Project._initialized_projects.get(project_id),
                ),
            )

        # Apply runtime detection updates
        project.worktree = worktree
        project.vcs = vcs
        project.time.updated = now

        # Add sandbox if different from worktree
        if sandbox != worktree and sandbox not in project.sandboxes:
            project.sandboxes.append(sandbox)

        # Filter existing sandboxes
        project.sandboxes = [s for s in project.sandboxes if Path(s).exists()]

        await Storage.write(Project._project_key(project_id), project.model_dump())

        # Publish update event
        await Bus.publish(ProjectUpdated, project)

        return project, sandbox

    @staticmethod
    async def list() -> List[ProjectInfo]:
        """List all known projects.

        Returns:
            List of project info objects
        """
        keys = await Storage.list(["project"])
        projects: List[ProjectInfo] = []

        for key in keys:
            try:
                data = await Storage.read(key)
            except NotFoundError:
                continue
            except Exception:
                continue

            try:
                project = ProjectInfo.model_validate(data)
            except Exception:
                continue

            project.sandboxes = [s for s in project.sandboxes if Path(s).exists()]
            projects.append(project)

        projects.sort(key=lambda p: p.time.updated, reverse=True)
        return projects

    @staticmethod
    async def set_initialized(project_id: str) -> None:
        """Mark a project as initialized.

        Args:
            project_id: Project ID to update
        """
        now = int(time.time() * 1000)
        Project._initialized_projects[project_id] = now
        log.info("project marked initialized", {"project_id": project_id, "initialized": now})

        try:
            def _mark_initialized(draft: dict) -> None:
                draft.setdefault("time", {})
                draft["time"]["updated"] = now
                draft["time"]["initialized"] = now

            updated = await Storage.update(
                Project._project_key(project_id),
                _mark_initialized,
            )
            await Bus.publish(ProjectUpdated, ProjectInfo.model_validate(updated))
            return
        except NotFoundError:
            pass

        # If project record does not exist yet, create a minimal one.
        project = ProjectInfo(
            id=project_id,
            worktree="/",
            sandboxes=[],
            time=ProjectTime(
                created=now,
                updated=now,
                initialized=now,
            ),
        )
        await Storage.write(Project._project_key(project_id), project.model_dump())
        await Bus.publish(ProjectUpdated, project)

    @staticmethod
    def initialized_at(project_id: str) -> Optional[int]:
        """Get in-memory initialized timestamp for a project."""
        return Project._initialized_projects.get(project_id)

    @staticmethod
    def reset_runtime_state() -> None:
        """Reset runtime-only state used for subscriptions/tests."""
        Project._initialized_projects.clear()
        Project._command_event_subscription_started = False

    @staticmethod
    async def add_sandbox(project_id: str, directory: str) -> Optional[ProjectInfo]:
        """Add a sandbox directory to a project.

        Args:
            project_id: Project ID
            directory: Directory to add as sandbox

        Returns:
            Updated project info or None
        """
        try:
            def _add_sandbox(draft: dict) -> None:
                draft.setdefault("sandboxes", [])
                if directory not in draft["sandboxes"]:
                    draft["sandboxes"].append(directory)
                draft.setdefault("time", {})
                draft["time"]["updated"] = int(time.time() * 1000)

            updated = await Storage.update(
                Project._project_key(project_id),
                _add_sandbox,
            )
        except NotFoundError:
            return None

        project = ProjectInfo.model_validate(updated)
        project.sandboxes = [s for s in project.sandboxes if Path(s).exists()]
        await Storage.write(Project._project_key(project_id), project.model_dump())
        await Bus.publish(ProjectUpdated, project)
        return project

    @staticmethod
    async def remove_sandbox(project_id: str, directory: str) -> Optional[ProjectInfo]:
        """Remove a sandbox directory from a project.

        Args:
            project_id: Project ID
            directory: Directory to remove

        Returns:
            Updated project info or None
        """
        try:
            def _remove_sandbox(draft: dict) -> None:
                draft.setdefault("sandboxes", [])
                draft["sandboxes"] = [s for s in draft["sandboxes"] if s != directory]
                draft.setdefault("time", {})
                draft["time"]["updated"] = int(time.time() * 1000)

            updated = await Storage.update(
                Project._project_key(project_id),
                _remove_sandbox,
            )
        except NotFoundError:
            return None

        project = ProjectInfo.model_validate(updated)
        project.sandboxes = [s for s in project.sandboxes if Path(s).exists()]
        await Storage.write(Project._project_key(project_id), project.model_dump())
        await Bus.publish(ProjectUpdated, project)
        return project
