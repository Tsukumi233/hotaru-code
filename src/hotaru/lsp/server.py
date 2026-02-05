"""LSP server definitions.

This module defines the available LSP servers and how to spawn them.
Each server definition includes:
- ID: Unique identifier
- Extensions: File extensions this server handles
- Root function: How to find the project root for a file
- Spawn function: How to start the server process
"""

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable, Coroutine, Dict, List, Optional

from ..core.global_paths import GlobalPath
from ..project.instance import Instance
from ..util.log import Log

log = Log.create({"service": "lsp.server"})


class LSPServerHandle:
    """Handle to a running LSP server process.

    Attributes:
        process: The subprocess running the server
        initialization: Optional initialization settings
    """

    def __init__(
        self,
        process: subprocess.Popen,
        initialization: Optional[Dict[str, Any]] = None
    ):
        self.process = process
        self.initialization = initialization or {}


# Type for root-finding functions
RootFunction = Callable[[str], Coroutine[Any, Any, Optional[str]]]

# Type for spawn functions
SpawnFunction = Callable[[str], Coroutine[Any, Any, Optional[LSPServerHandle]]]


class LSPServerInfo:
    """LSP server definition.

    Attributes:
        id: Unique server identifier
        extensions: File extensions this server handles
        root: Function to find project root for a file
        spawn: Function to spawn the server process
        global_server: Whether this is a global server (not project-specific)
    """

    def __init__(
        self,
        server_id: str,
        extensions: List[str],
        root: RootFunction,
        spawn: SpawnFunction,
        global_server: bool = False
    ):
        self.id = server_id
        self.extensions = extensions
        self.root = root
        self.spawn = spawn
        self.global_server = global_server


async def _find_nearest_root(
    file: str,
    include_patterns: List[str],
    exclude_patterns: Optional[List[str]] = None
) -> Optional[str]:
    """Find the nearest directory containing any of the target files.

    Args:
        file: Starting file path
        include_patterns: Files to search for
        exclude_patterns: Files that exclude a directory

    Returns:
        Path to the root directory, or None if not found
    """
    start_dir = Path(file).parent
    stop_dir = Path(Instance.directory())

    # Check for exclusions first
    if exclude_patterns:
        current = start_dir
        while current >= stop_dir:
            for pattern in exclude_patterns:
                if (current / pattern).exists():
                    return None
            current = current.parent

    # Search for include patterns
    current = start_dir
    while current >= stop_dir:
        for pattern in include_patterns:
            if (current / pattern).exists():
                return str(current)
        current = current.parent

    # Return instance directory as fallback
    return str(stop_dir)


def _nearest_root(
    include_patterns: List[str],
    exclude_patterns: Optional[List[str]] = None
) -> RootFunction:
    """Create a root-finding function for the given patterns.

    Args:
        include_patterns: Files to search for
        exclude_patterns: Files that exclude a directory

    Returns:
        Root-finding function
    """
    async def find_root(file: str) -> Optional[str]:
        return await _find_nearest_root(file, include_patterns, exclude_patterns)
    return find_root


def _which(cmd: str) -> Optional[str]:
    """Find an executable in PATH.

    Args:
        cmd: Command name

    Returns:
        Full path to executable, or None if not found
    """
    return shutil.which(cmd)


# Python LSP server (Pyright)
async def _pyright_root(file: str) -> Optional[str]:
    return await _find_nearest_root(
        file,
        ["pyproject.toml", "setup.py", "setup.cfg", "requirements.txt",
         "Pipfile", "pyrightconfig.json"]
    )


async def _pyright_spawn(root: str) -> Optional[LSPServerHandle]:
    """Spawn Pyright language server."""
    binary = _which("pyright-langserver")
    args = []

    if not binary:
        # Try to find installed pyright
        bin_path = GlobalPath.bin()
        pyright_js = bin_path / "node_modules" / "pyright" / "dist" / "pyright-langserver.js"

        if not pyright_js.exists():
            log.info("pyright not found, please install pyright")
            return None

        # Use node to run pyright
        node = _which("node")
        if not node:
            log.info("node not found, required for pyright")
            return None

        binary = node
        args = [str(pyright_js)]

    args.append("--stdio")

    initialization: Dict[str, str] = {}

    # Try to find Python in virtual environment
    venv_paths = [
        os.environ.get("VIRTUAL_ENV"),
        os.path.join(root, ".venv"),
        os.path.join(root, "venv"),
    ]

    for venv_path in venv_paths:
        if not venv_path:
            continue

        if os.name == "nt":
            python_path = os.path.join(venv_path, "Scripts", "python.exe")
        else:
            python_path = os.path.join(venv_path, "bin", "python")

        if os.path.exists(python_path):
            initialization["pythonPath"] = python_path
            break

    process = subprocess.Popen(
        [binary] + args,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=root,
    )

    return LSPServerHandle(process, initialization)


Pyright = LSPServerInfo(
    server_id="pyright",
    extensions=[".py", ".pyi"],
    root=_pyright_root,
    spawn=_pyright_spawn,
)


# Go LSP server (gopls)
async def _gopls_root(file: str) -> Optional[str]:
    # Check for go.work first (workspace)
    work_root = await _find_nearest_root(file, ["go.work"])
    if work_root:
        return work_root
    return await _find_nearest_root(file, ["go.mod", "go.sum"])


async def _gopls_spawn(root: str) -> Optional[LSPServerHandle]:
    """Spawn gopls language server."""
    bin_path = GlobalPath.bin()
    gopls = _which("gopls")

    if not gopls:
        # Check in bin directory
        gopls_bin = bin_path / ("gopls.exe" if os.name == "nt" else "gopls")
        if gopls_bin.exists():
            gopls = str(gopls_bin)

    if not gopls:
        log.info("gopls not found, please install gopls")
        return None

    process = subprocess.Popen(
        [gopls],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=root,
    )

    return LSPServerHandle(process)


Gopls = LSPServerInfo(
    server_id="gopls",
    extensions=[".go"],
    root=_gopls_root,
    spawn=_gopls_spawn,
)


# Rust LSP server (rust-analyzer)
async def _rust_root(file: str) -> Optional[str]:
    crate_root = await _find_nearest_root(file, ["Cargo.toml", "Cargo.lock"])
    if not crate_root:
        return None

    # Look for workspace root
    current = Path(crate_root)
    worktree = Path(Instance.worktree())

    while current >= worktree:
        cargo_toml = current / "Cargo.toml"
        if cargo_toml.exists():
            try:
                content = cargo_toml.read_text()
                if "[workspace]" in content:
                    return str(current)
            except Exception:
                pass

        parent = current.parent
        if parent == current:
            break
        current = parent

    return crate_root


async def _rust_spawn(root: str) -> Optional[LSPServerHandle]:
    """Spawn rust-analyzer language server."""
    rust_analyzer = _which("rust-analyzer")

    if not rust_analyzer:
        log.info("rust-analyzer not found, please install rust-analyzer")
        return None

    process = subprocess.Popen(
        [rust_analyzer],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=root,
    )

    return LSPServerHandle(process)


RustAnalyzer = LSPServerInfo(
    server_id="rust",
    extensions=[".rs"],
    root=_rust_root,
    spawn=_rust_spawn,
)


# TypeScript LSP server
async def _typescript_root(file: str) -> Optional[str]:
    return await _find_nearest_root(
        file,
        ["package-lock.json", "bun.lockb", "bun.lock", "pnpm-lock.yaml", "yarn.lock"],
        ["deno.json", "deno.jsonc"]  # Exclude Deno projects
    )


async def _typescript_spawn(root: str) -> Optional[LSPServerHandle]:
    """Spawn TypeScript language server."""
    # Try to find typescript-language-server
    tsserver = _which("typescript-language-server")

    if not tsserver:
        log.info("typescript-language-server not found")
        return None

    process = subprocess.Popen(
        [tsserver, "--stdio"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=root,
    )

    return LSPServerHandle(process)


Typescript = LSPServerInfo(
    server_id="typescript",
    extensions=[".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts"],
    root=_typescript_root,
    spawn=_typescript_spawn,
)


# C/C++ LSP server (clangd)
async def _clangd_root(file: str) -> Optional[str]:
    return await _find_nearest_root(
        file,
        ["compile_commands.json", "compile_flags.txt", ".clangd",
         "CMakeLists.txt", "Makefile"]
    )


async def _clangd_spawn(root: str) -> Optional[LSPServerHandle]:
    """Spawn clangd language server."""
    clangd = _which("clangd")

    if not clangd:
        log.info("clangd not found, please install clangd")
        return None

    process = subprocess.Popen(
        [clangd, "--background-index", "--clang-tidy"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=root,
    )

    return LSPServerHandle(process)


Clangd = LSPServerInfo(
    server_id="clangd",
    extensions=[".c", ".cpp", ".cc", ".cxx", ".c++", ".h", ".hpp", ".hh", ".hxx", ".h++"],
    root=_clangd_root,
    spawn=_clangd_spawn,
)


# Bash LSP server
async def _bash_root(file: str) -> Optional[str]:
    return Instance.directory()


async def _bash_spawn(root: str) -> Optional[LSPServerHandle]:
    """Spawn bash-language-server."""
    bash_ls = _which("bash-language-server")

    if not bash_ls:
        log.info("bash-language-server not found")
        return None

    process = subprocess.Popen(
        [bash_ls, "start"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=root,
    )

    return LSPServerHandle(process)


BashLS = LSPServerInfo(
    server_id="bash",
    extensions=[".sh", ".bash", ".zsh", ".ksh"],
    root=_bash_root,
    spawn=_bash_spawn,
)


# All available LSP servers
ALL_SERVERS: Dict[str, LSPServerInfo] = {
    "pyright": Pyright,
    "gopls": Gopls,
    "rust": RustAnalyzer,
    "typescript": Typescript,
    "clangd": Clangd,
    "bash": BashLS,
}
