"""LSP server definitions.

This module contains built-in Language Server Protocol (LSP) integrations and
helpers for spawning language servers with optional per-server configuration
overrides (environment variables and initialization options).
"""

from __future__ import annotations

import asyncio
import json
import os
import platform
import shutil
import stat
import subprocess
import tarfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Callable, Coroutine, Dict, List, Optional

from ..core.global_paths import GlobalPath
from ..project.instance import Instance
from ..util.log import Log

log = Log.create({"service": "lsp.server"})


class LSPServerHandle:
    """Handle to a running LSP server process."""

    def __init__(
        self,
        process: subprocess.Popen,
        initialization: Optional[Dict[str, Any]] = None,
    ):
        self.process = process
        self.initialization = initialization or {}


RootFunction = Callable[[str], Coroutine[Any, Any, Optional[str]]]
SpawnFunction = Callable[[str, Dict[str, str], Dict[str, Any]], Coroutine[Any, Any, Optional[LSPServerHandle]]]


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if isinstance(result.get(key), dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


class LSPServerInfo:
    """LSP server definition and runtime override state."""

    def __init__(
        self,
        server_id: str,
        extensions: List[str],
        root: RootFunction,
        spawn: SpawnFunction,
        global_server: bool = False,
        env: Optional[Dict[str, str]] = None,
        initialization: Optional[Dict[str, Any]] = None,
    ):
        self.id = server_id
        self.extensions = extensions
        self.root = root
        self._spawn = spawn
        self.global_server = global_server
        self.env = env or {}
        self.initialization = initialization or {}

    async def spawn(self, root: str) -> Optional[LSPServerHandle]:
        return await self._spawn(root, self.env, self.initialization)

    def configured(
        self,
        *,
        extensions: Optional[List[str]] = None,
        env: Optional[Dict[str, str]] = None,
        initialization: Optional[Dict[str, Any]] = None,
    ) -> "LSPServerInfo":
        return LSPServerInfo(
            server_id=self.id,
            extensions=extensions if extensions is not None else list(self.extensions),
            root=self.root,
            spawn=self._spawn,
            global_server=self.global_server,
            env=dict(env or self.env),
            initialization=dict(initialization or self.initialization),
        )


def _truthy_env(key: str) -> bool:
    value = os.environ.get(key, "").strip().lower()
    return value in {"1", "true"}


def lsp_download_disabled() -> bool:
    """Return whether automatic LSP downloads are disabled.
    """
    return _truthy_env("HOTARU_DISABLE_LSP_DOWNLOAD")


def _which(cmd: str) -> Optional[str]:
    path = os.environ.get("PATH", "")
    search_path = f"{path}{os.pathsep}{GlobalPath.bin()}"
    return shutil.which(cmd, path=search_path)


def _is_windows() -> bool:
    return os.name == "nt"


def _bin_name(name: str) -> str:
    if _is_windows() and not name.endswith(".exe"):
        return f"{name}.exe"
    return name


def _node_modules_dir() -> Path:
    return Path(GlobalPath.bin()) / "node_modules"


def _global_node_script(package: str, script_rel_path: str) -> Path:
    return _node_modules_dir() / Path(package) / Path(script_rel_path)


def _to_subprocess_env(extra: Optional[Dict[str, str]]) -> Dict[str, str]:
    return {**os.environ, **(extra or {})}


def _popen(
    cmd: List[str],
    cwd: str,
    env: Optional[Dict[str, str]] = None,
) -> Optional[subprocess.Popen]:
    try:
        return subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd,
            env=_to_subprocess_env(env),
        )
    except Exception as error:
        log.error("failed to spawn LSP server", {"cmd": cmd, "error": str(error)})
        return None


async def _run_command(
    cmd: List[str],
    cwd: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
) -> bool:
    def run() -> bool:
        try:
            completed = subprocess.run(
                cmd,
                cwd=cwd,
                env=_to_subprocess_env(env),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                text=True,
            )
            return completed.returncode == 0
        except Exception:
            return False

    return await asyncio.to_thread(run)


async def _install_npm_package(package: str) -> bool:
    if lsp_download_disabled():
        return False

    npm = _which("npm")
    if not npm:
        log.info("npm not found; cannot auto-install package", {"package": package})
        return False

    target = Path(GlobalPath.bin())
    target.mkdir(parents=True, exist_ok=True)

    log.info("installing npm package for LSP", {"package": package})
    return await _run_command(
        [npm, "install", "--no-audit", "--no-fund", package],
        cwd=str(target),
    )


async def _install_dotnet_tool(tool: str) -> bool:
    if lsp_download_disabled():
        return False

    dotnet = _which("dotnet")
    if not dotnet:
        return False

    target = Path(GlobalPath.bin())
    target.mkdir(parents=True, exist_ok=True)

    log.info("installing dotnet tool for LSP", {"tool": tool})
    return await _run_command([dotnet, "tool", "install", tool, "--tool-path", str(target)])


async def _install_go_binary(package: str) -> bool:
    if lsp_download_disabled():
        return False

    go = _which("go")
    if not go:
        return False

    target = Path(GlobalPath.bin())
    target.mkdir(parents=True, exist_ok=True)

    log.info("installing go binary for LSP", {"package": package})
    return await _run_command(
        [go, "install", package],
        env={"GOBIN": str(target)},
    )


async def _install_gem_package(package: str) -> bool:
    if lsp_download_disabled():
        return False

    gem = _which("gem")
    if not gem:
        return False

    target = Path(GlobalPath.bin())
    target.mkdir(parents=True, exist_ok=True)

    log.info("installing gem package for LSP", {"package": package})
    return await _run_command([gem, "install", package, "--bindir", str(target)])


def _safe_join(base: Path, relative: Path) -> Optional[Path]:
    try:
        target = (base / relative).resolve()
        base_resolved = base.resolve()
        if target == base_resolved or base_resolved in target.parents:
            return target
    except Exception:
        return None
    return None


def _extract_archive(archive: Path, destination: Path, strip_components: int = 0) -> bool:
    try:
        destination.mkdir(parents=True, exist_ok=True)

        if archive.suffix == ".zip":
            with zipfile.ZipFile(archive, "r") as zf:
                if strip_components <= 0:
                    zf.extractall(destination)
                    return True

                for info in zf.infolist():
                    parts = Path(info.filename).parts[strip_components:]
                    if not parts:
                        continue
                    relative = Path(*parts)
                    target = _safe_join(destination, relative)
                    if not target:
                        continue
                    if info.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(info, "r") as src, open(target, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                return True

        mode = None
        name = archive.name
        if name.endswith(".tar.gz"):
            mode = "r:gz"
        elif name.endswith(".tar.xz"):
            mode = "r:xz"

        if mode is None:
            return False

        with tarfile.open(archive, mode) as tf:
            if strip_components <= 0:
                tf.extractall(destination)
                return True

            for member in tf.getmembers():
                parts = Path(member.name).parts[strip_components:]
                if not parts:
                    continue
                relative = Path(*parts)
                target = _safe_join(destination, relative)
                if not target:
                    continue
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                if not member.isfile():
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                src = tf.extractfile(member)
                if src is None:
                    continue
                with src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
        return True
    except Exception as error:
        log.error("failed to extract archive", {"archive": str(archive), "error": str(error)})
        return False


def _http_get_json(url: str) -> Optional[Dict[str, Any]]:
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "hotaru-code"})
        with urllib.request.urlopen(request, timeout=60) as response:
            data = response.read()
        parsed = json.loads(data.decode("utf-8"))
        if isinstance(parsed, dict):
            return parsed
        return None
    except Exception as error:
        log.error("failed to fetch JSON", {"url": url, "error": str(error)})
        return None


def _http_download(url: str, target: Path) -> bool:
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        request = urllib.request.Request(url, headers={"User-Agent": "hotaru-code"})
        with urllib.request.urlopen(request, timeout=180) as response, open(target, "wb") as out:
            shutil.copyfileobj(response, out)
        return True
    except Exception as error:
        log.error("failed to download file", {"url": url, "target": str(target), "error": str(error)})
        return False


async def _download_latest_github_asset(
    repo: str,
    pick_asset: Callable[[Dict[str, Any]], Optional[Dict[str, Any]]],
    target_dir: Path,
) -> Optional[Path]:
    def task() -> Optional[Path]:
        release = _http_get_json(f"https://api.github.com/repos/{repo}/releases/latest")
        if not release:
            return None

        asset = pick_asset(release)
        if not asset:
            return None

        name = asset.get("name")
        url = asset.get("browser_download_url")
        if not name or not url:
            return None

        archive = target_dir / name
        if not _http_download(url, archive):
            return None

        ok = _extract_archive(archive, target_dir)
        try:
            archive.unlink(missing_ok=True)
        except Exception:
            pass
        if not ok:
            return None
        return target_dir

    return await asyncio.to_thread(task)


def _iter_parent_dirs(start: Path, stop: Path):
    if start != stop and stop not in start.parents:
        return

    current = start
    while True:
        yield current
        if current == stop:
            break
        parent = current.parent
        if parent == current:
            break
        current = parent


def _pattern_exists(directory: Path, pattern: str) -> bool:
    if any(ch in pattern for ch in "*?["):
        return any(directory.glob(pattern))
    return (directory / pattern).exists()


async def _find_nearest_root(
    file: str,
    include_patterns: List[str],
    exclude_patterns: Optional[List[str]] = None,
    fallback_to_instance: bool = True,
) -> Optional[str]:
    instance_dir = Path(Instance.directory()).resolve()
    path = Path(file)
    if not path.is_absolute():
        path = (instance_dir / path).resolve()
    start_dir = path.parent

    if exclude_patterns:
        for current in _iter_parent_dirs(start_dir, instance_dir) or []:
            if any(_pattern_exists(current, pattern) for pattern in exclude_patterns):
                return None

    for current in _iter_parent_dirs(start_dir, instance_dir) or []:
        if any(_pattern_exists(current, pattern) for pattern in include_patterns):
            return str(current)

    if fallback_to_instance:
        return str(instance_dir)
    return None


def _nearest_root(
    include_patterns: List[str],
    exclude_patterns: Optional[List[str]] = None,
    fallback_to_instance: bool = True,
) -> RootFunction:
    async def find_root(file: str) -> Optional[str]:
        return await _find_nearest_root(
            file,
            include_patterns,
            exclude_patterns,
            fallback_to_instance=fallback_to_instance,
        )

    return find_root


def _merge_initialization(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    if not override:
        return base
    return _deep_merge(base, override)


def _find_local_node_module(root: str, relative_path: str) -> Optional[Path]:
    current = Path(root).resolve()
    while True:
        candidate = current / "node_modules" / Path(relative_path)
        if candidate.exists():
            return candidate
        parent = current.parent
        if parent == current:
            break
        current = parent
    return None


def _node_dependency_exists(root: str, package_name: str) -> bool:
    module_dir = _find_local_node_module(root, package_name)
    if module_dir:
        return True

    current = Path(root).resolve()
    while True:
        pkg = current / "package.json"
        if pkg.exists():
            try:
                parsed = json.loads(pkg.read_text(encoding="utf-8"))
            except Exception:
                parsed = {}

            for key in ["dependencies", "devDependencies", "peerDependencies", "optionalDependencies"]:
                value = parsed.get(key)
                if isinstance(value, dict) and package_name in value:
                    return True
        parent = current.parent
        if parent == current:
            break
        current = parent

    return False


async def _spawn_node_script(
    root: str,
    package: str,
    script_rel_path: str,
    args: List[str],
    env: Dict[str, str],
    initialization: Dict[str, Any],
    auto_install: bool,
) -> Optional[LSPServerHandle]:
    node = _which("node")
    if not node:
        return None

    script = _global_node_script(package, script_rel_path)
    if not script.exists() and auto_install:
        ok = await _install_npm_package(package)
        if not ok:
            return None

    if not script.exists():
        return None

    process = _popen([node, str(script), *args], root, env)
    if not process:
        return None
    return LSPServerHandle(process, initialization)


async def _spawn_binary(
    binary: str,
    args: List[str],
    root: str,
    env: Dict[str, str],
    initialization: Dict[str, Any],
) -> Optional[LSPServerHandle]:
    process = _popen([binary, *args], root, env)
    if not process:
        return None
    return LSPServerHandle(process, initialization)


async def _instance_root(_: str) -> Optional[str]:
    return Instance.directory()


# ---- Built-in LSP servers ----


async def _deno_root(file: str) -> Optional[str]:
    return await _find_nearest_root(file, ["deno.json", "deno.jsonc"], fallback_to_instance=False)


async def _deno_spawn(root: str, env: Dict[str, str], initialization: Dict[str, Any]) -> Optional[LSPServerHandle]:
    deno = _which("deno")
    if not deno:
        return None
    return await _spawn_binary(deno, ["lsp"], root, env, initialization)


Deno = LSPServerInfo(
    server_id="deno",
    extensions=[".ts", ".tsx", ".js", ".jsx", ".mjs"],
    root=_deno_root,
    spawn=_deno_spawn,
)


async def _typescript_spawn(root: str, env: Dict[str, str], initialization: Dict[str, Any]) -> Optional[LSPServerHandle]:
    if not _node_dependency_exists(root, "typescript"):
        return None

    tsserver = _find_local_node_module(root, "typescript/lib/tsserver.js")
    if not tsserver:
        return None

    ts_lang = _which("typescript-language-server")
    base_init = {"tsserver": {"path": str(tsserver)}}

    if ts_lang:
        return await _spawn_binary(
            ts_lang,
            ["--stdio"],
            root,
            env,
            _merge_initialization(base_init, initialization),
        )

    # Try using npx as a fallback if available.
    npx = _which("npx")
    if npx:
        return await _spawn_binary(
            npx,
            ["typescript-language-server", "--stdio"],
            root,
            env,
            _merge_initialization(base_init, initialization),
        )

    return None


Typescript = LSPServerInfo(
    server_id="typescript",
    extensions=[".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts"],
    root=_nearest_root(
        ["package-lock.json", "bun.lockb", "bun.lock", "pnpm-lock.yaml", "yarn.lock"],
        ["deno.json", "deno.jsonc"],
    ),
    spawn=_typescript_spawn,
)


async def _vue_spawn(root: str, env: Dict[str, str], initialization: Dict[str, Any]) -> Optional[LSPServerHandle]:
    vue_ls = _which("vue-language-server")
    if vue_ls:
        return await _spawn_binary(vue_ls, ["--stdio"], root, env, initialization)

    return await _spawn_node_script(
        root,
        "@vue/language-server",
        "bin/vue-language-server.js",
        ["--stdio"],
        env,
        initialization,
        auto_install=True,
    )


Vue = LSPServerInfo(
    server_id="vue",
    extensions=[".vue"],
    root=_nearest_root(["package-lock.json", "bun.lockb", "bun.lock", "pnpm-lock.yaml", "yarn.lock"]),
    spawn=_vue_spawn,
)


async def _eslint_spawn(root: str, env: Dict[str, str], initialization: Dict[str, Any]) -> Optional[LSPServerHandle]:
    if not _node_dependency_exists(root, "eslint"):
        return None

    server = _which("vscode-eslint-language-server")
    if not server:
        # Common alternative package.
        server = _which("eslint-language-server")

    if not server:
        return None

    return await _spawn_binary(server, ["--stdio"], root, env, initialization)


ESLint = LSPServerInfo(
    server_id="eslint",
    extensions=[".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts", ".vue"],
    root=_nearest_root(["package-lock.json", "bun.lockb", "bun.lock", "pnpm-lock.yaml", "yarn.lock"]),
    spawn=_eslint_spawn,
)


async def _oxlint_spawn(root: str, env: Dict[str, str], initialization: Dict[str, Any]) -> Optional[LSPServerHandle]:
    # Prefer modern oxlint --lsp when available.
    oxlint = _which("oxlint")
    if oxlint:
        return await _spawn_binary(oxlint, ["--lsp"], root, env, initialization)

    language_server = _which("oxc_language_server")
    if language_server:
        return await _spawn_binary(language_server, [], root, env, initialization)

    return None


Oxlint = LSPServerInfo(
    server_id="oxlint",
    extensions=[".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts", ".vue", ".astro", ".svelte"],
    root=_nearest_root([".oxlintrc.json", "package-lock.json", "bun.lockb", "bun.lock", "pnpm-lock.yaml", "yarn.lock", "package.json"]),
    spawn=_oxlint_spawn,
)


async def _gopls_root(file: str) -> Optional[str]:
    work_root = await _find_nearest_root(file, ["go.work"], fallback_to_instance=False)
    if work_root:
        return work_root
    return await _find_nearest_root(file, ["go.mod", "go.sum"], fallback_to_instance=False)


async def _gopls_spawn(root: str, env: Dict[str, str], initialization: Dict[str, Any]) -> Optional[LSPServerHandle]:
    gopls = _which("gopls")
    if not gopls:
        await _install_go_binary("golang.org/x/tools/gopls@latest")
        gopls = _which("gopls")

    if not gopls:
        return None

    return await _spawn_binary(gopls, [], root, env, initialization)


Gopls = LSPServerInfo(
    server_id="gopls",
    extensions=[".go"],
    root=_gopls_root,
    spawn=_gopls_spawn,
)


async def _rubocop_spawn(root: str, env: Dict[str, str], initialization: Dict[str, Any]) -> Optional[LSPServerHandle]:
    rubocop = _which("rubocop")
    if not rubocop:
        if _which("ruby") and _which("gem"):
            await _install_gem_package("rubocop")
            rubocop = _which("rubocop")

    if not rubocop:
        return None

    return await _spawn_binary(rubocop, ["--lsp"], root, env, initialization)


RubyLSP = LSPServerInfo(
    server_id="ruby-lsp",
    extensions=[".rb", ".rake", ".gemspec", ".ru"],
    root=_nearest_root(["Gemfile"]),
    spawn=_rubocop_spawn,
)


def _detect_python_path(root: str) -> Dict[str, Any]:
    potential = [
        os.environ.get("VIRTUAL_ENV"),
        str(Path(root) / ".venv"),
        str(Path(root) / "venv"),
    ]

    for item in potential:
        if not item:
            continue

        path = Path(item)
        if _is_windows():
            candidate = path / "Scripts" / "python.exe"
        else:
            candidate = path / "bin" / "python"

        if candidate.exists():
            return {"pythonPath": str(candidate)}

    return {}


async def _pyright_spawn(root: str, env: Dict[str, str], initialization: Dict[str, Any]) -> Optional[LSPServerHandle]:
    binary = _which("pyright-langserver")
    args: List[str] = []

    if not binary:
        local_js = _find_local_node_module(root, "pyright/dist/pyright-langserver.js")
        if local_js:
            node = _which("node")
            if not node:
                return None
            binary = node
            args = [str(local_js)]
        else:
            # If globally installed under managed bin, allow that too.
            global_js = _global_node_script("pyright", "dist/pyright-langserver.js")
            if not global_js.exists() and not lsp_download_disabled():
                await _install_npm_package("pyright")
            if global_js.exists():
                node = _which("node")
                if not node:
                    return None
                binary = node
                args = [str(global_js)]

    if not binary:
        return None

    args.append("--stdio")
    server_init = _merge_initialization(_detect_python_path(root), initialization)

    process = _popen([binary, *args], root, env)
    if not process:
        return None
    return LSPServerHandle(process, server_init)


Pyright = LSPServerInfo(
    server_id="pyright",
    extensions=[".py", ".pyi"],
    root=_nearest_root(["pyproject.toml", "setup.py", "setup.cfg", "requirements.txt", "Pipfile", "pyrightconfig.json"]),
    spawn=_pyright_spawn,
)


async def _elixir_ls_spawn(root: str, env: Dict[str, str], initialization: Dict[str, Any]) -> Optional[LSPServerHandle]:
    binary = _which("elixir-ls")
    if not binary:
        return None
    return await _spawn_binary(binary, [], root, env, initialization)


ElixirLS = LSPServerInfo(
    server_id="elixir-ls",
    extensions=[".ex", ".exs"],
    root=_nearest_root(["mix.exs", "mix.lock"]),
    spawn=_elixir_ls_spawn,
)


async def _install_zls() -> Optional[str]:
    if lsp_download_disabled():
        return None

    sys_name = platform.system()
    machine = platform.machine().lower()

    if machine in {"x86_64", "amd64"}:
        arch = "x86_64"
    elif machine in {"arm64", "aarch64"}:
        arch = "aarch64"
    elif machine in {"x86", "i386", "i686"}:
        arch = "x86"
    else:
        return None

    if sys_name == "Darwin":
        zls_platform = "macos"
    elif sys_name == "Windows":
        zls_platform = "windows"
    elif sys_name == "Linux":
        zls_platform = "linux"
    else:
        return None

    ext = "zip" if sys_name == "Windows" else "tar.xz"
    asset_name = f"zls-{arch}-{zls_platform}.{ext}"

    def pick_asset(release: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        assets = release.get("assets")
        if not isinstance(assets, list):
            return None
        for item in assets:
            if isinstance(item, dict) and item.get("name") == asset_name:
                return item
        return None

    installed = await _download_latest_github_asset("zigtools/zls", pick_asset, Path(GlobalPath.bin()))
    if not installed:
        return None

    binary = Path(GlobalPath.bin()) / _bin_name("zls")
    if not binary.exists():
        return None

    await asyncio.to_thread(_set_executable, binary)
    return str(binary)


async def _zls_spawn(root: str, env: Dict[str, str], initialization: Dict[str, Any]) -> Optional[LSPServerHandle]:
    zls = _which("zls")
    if not zls and _which("zig") and not lsp_download_disabled():
        zls = await _install_zls()
    if not zls:
        return None
    return await _spawn_binary(zls, [], root, env, initialization)


Zls = LSPServerInfo(
    server_id="zls",
    extensions=[".zig", ".zon"],
    root=_nearest_root(["build.zig"]),
    spawn=_zls_spawn,
)


async def _csharp_spawn(root: str, env: Dict[str, str], initialization: Dict[str, Any]) -> Optional[LSPServerHandle]:
    binary = _which("csharp-ls")
    if not binary:
        if _which("dotnet"):
            await _install_dotnet_tool("csharp-ls")
            binary = _which("csharp-ls")

    if not binary:
        return None

    return await _spawn_binary(binary, [], root, env, initialization)


CSharp = LSPServerInfo(
    server_id="csharp",
    extensions=[".cs"],
    root=_nearest_root([".slnx", ".sln", ".csproj", "global.json"]),
    spawn=_csharp_spawn,
)


async def _fsharp_spawn(root: str, env: Dict[str, str], initialization: Dict[str, Any]) -> Optional[LSPServerHandle]:
    binary = _which("fsautocomplete")
    if not binary:
        if _which("dotnet"):
            await _install_dotnet_tool("fsautocomplete")
            binary = _which("fsautocomplete")

    if not binary:
        return None

    return await _spawn_binary(binary, [], root, env, initialization)


FSharp = LSPServerInfo(
    server_id="fsharp",
    extensions=[".fs", ".fsi", ".fsx", ".fsscript"],
    root=_nearest_root([".slnx", ".sln", ".fsproj", "global.json"]),
    spawn=_fsharp_spawn,
)


async def _sourcekit_spawn(root: str, env: Dict[str, str], initialization: Dict[str, Any]) -> Optional[LSPServerHandle]:
    sourcekit = _which("sourcekit-lsp")
    if sourcekit:
        return await _spawn_binary(sourcekit, [], root, env, initialization)

    if platform.system() == "Darwin":
        xcrun = _which("xcrun")
        if xcrun:
            resolved = await asyncio.to_thread(
                lambda: subprocess.run(
                    [xcrun, "--find", "sourcekit-lsp"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                    text=True,
                )
            )
            if resolved.returncode == 0 and resolved.stdout.strip():
                return await _spawn_binary(resolved.stdout.strip(), [], root, env, initialization)

    return None


SourceKit = LSPServerInfo(
    server_id="sourcekit-lsp",
    extensions=[".swift", ".objc", ".objcpp"],
    root=_nearest_root(["Package.swift", "*.xcodeproj", "*.xcworkspace"]),
    spawn=_sourcekit_spawn,
)


async def _rust_root(file: str) -> Optional[str]:
    crate_root = await _find_nearest_root(file, ["Cargo.toml", "Cargo.lock"], fallback_to_instance=False)
    if not crate_root:
        return None

    current = Path(crate_root).resolve()
    worktree = Path(Instance.worktree()).resolve()

    while True:
        cargo_toml = current / "Cargo.toml"
        if cargo_toml.exists():
            try:
                if "[workspace]" in cargo_toml.read_text(encoding="utf-8"):
                    return str(current)
            except Exception:
                pass

        if current == worktree:
            break

        parent = current.parent
        if parent == current:
            break
        current = parent

    return crate_root


async def _rust_spawn(root: str, env: Dict[str, str], initialization: Dict[str, Any]) -> Optional[LSPServerHandle]:
    rust = _which("rust-analyzer")
    if not rust:
        return None
    return await _spawn_binary(rust, [], root, env, initialization)


RustAnalyzer = LSPServerInfo(
    server_id="rust",
    extensions=[".rs"],
    root=_rust_root,
    spawn=_rust_spawn,
)


async def _install_clangd() -> Optional[str]:
    if lsp_download_disabled():
        return None

    target = Path(GlobalPath.bin())
    ext = ".exe" if _is_windows() else ""

    def pick_asset(release: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        tag = release.get("tag_name")
        assets = release.get("assets") or []
        if not isinstance(assets, list):
            return None

        token = {
            "Darwin": "mac",
            "Linux": "linux",
            "Windows": "windows",
        }.get(platform.system())
        if not token:
            return None

        def valid(asset: Dict[str, Any]) -> bool:
            name = asset.get("name")
            if not isinstance(name, str):
                return False
            if token not in name:
                return False
            if not tag or str(tag) not in name:
                return False
            return name.endswith(".zip") or name.endswith(".tar.xz")

        for item in assets:
            if isinstance(item, dict) and valid(item):
                return item
        return None

    await _download_latest_github_asset("clangd/clangd", pick_asset, target)

    direct = target / _bin_name("clangd")
    if direct.exists():
        return str(direct)

    for child in target.iterdir():
        candidate = child / "bin" / _bin_name("clangd")
        if candidate.exists():
            return str(candidate)

    return None


async def _clangd_spawn(root: str, env: Dict[str, str], initialization: Dict[str, Any]) -> Optional[LSPServerHandle]:
    clangd = _which("clangd")
    if not clangd:
        clangd = await _install_clangd()

    if not clangd:
        return None

    return await _spawn_binary(clangd, ["--background-index", "--clang-tidy"], root, env, initialization)


Clangd = LSPServerInfo(
    server_id="clangd",
    extensions=[".c", ".cpp", ".cc", ".cxx", ".c++", ".h", ".hpp", ".hh", ".hxx", ".h++"],
    root=_nearest_root(["compile_commands.json", "compile_flags.txt", ".clangd", "CMakeLists.txt", "Makefile"]),
    spawn=_clangd_spawn,
)


async def _svelte_spawn(root: str, env: Dict[str, str], initialization: Dict[str, Any]) -> Optional[LSPServerHandle]:
    svelte = _which("svelteserver")
    if svelte:
        return await _spawn_binary(svelte, ["--stdio"], root, env, initialization)

    return await _spawn_node_script(
        root,
        "svelte-language-server",
        "bin/server.js",
        ["--stdio"],
        env,
        initialization,
        auto_install=True,
    )


Svelte = LSPServerInfo(
    server_id="svelte",
    extensions=[".svelte"],
    root=_nearest_root(["package-lock.json", "bun.lockb", "bun.lock", "pnpm-lock.yaml", "yarn.lock"]),
    spawn=_svelte_spawn,
)


async def _astro_spawn(root: str, env: Dict[str, str], initialization: Dict[str, Any]) -> Optional[LSPServerHandle]:
    tsserver = _find_local_node_module(root, "typescript/lib/tsserver.js")
    if not tsserver:
        return None

    astro = _which("astro-ls")
    base_init = {"typescript": {"tsdk": str(tsserver.parent)}}

    if astro:
        return await _spawn_binary(astro, ["--stdio"], root, env, _merge_initialization(base_init, initialization))

    return await _spawn_node_script(
        root,
        "@astrojs/language-server",
        "bin/nodeServer.js",
        ["--stdio"],
        env,
        _merge_initialization(base_init, initialization),
        auto_install=True,
    )


Astro = LSPServerInfo(
    server_id="astro",
    extensions=[".astro"],
    root=_nearest_root(["package-lock.json", "bun.lockb", "bun.lock", "pnpm-lock.yaml", "yarn.lock"]),
    spawn=_astro_spawn,
)


def _java_major_version() -> Optional[int]:
    java = _which("java")
    if not java:
        return None

    try:
        completed = subprocess.run(
            [java, "-version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            text=True,
        )
    except Exception:
        return None

    text = completed.stderr or completed.stdout
    if not text:
        return None

    import re

    # Handles both: "21.0.4" and "1.8.0" style outputs.
    match = re.search(r'"(\d+)(?:\.(\d+))?', text)
    if not match:
        return None

    major = int(match.group(1))
    minor = int(match.group(2) or "0")
    if major == 1:
        return minor
    return major


async def _jdtls_spawn(root: str, env: Dict[str, str], initialization: Dict[str, Any]) -> Optional[LSPServerHandle]:
    major = await asyncio.to_thread(_java_major_version)
    if major is None or major < 21:
        return None

    jdtls = _which("jdtls")
    if not jdtls:
        return None

    return await _spawn_binary(jdtls, [], root, env, initialization)


JDTLS = LSPServerInfo(
    server_id="jdtls",
    extensions=[".java"],
    root=_nearest_root(["pom.xml", "build.gradle", "build.gradle.kts", ".project", ".classpath"]),
    spawn=_jdtls_spawn,
)


async def _install_kotlin_ls() -> Optional[str]:
    if lsp_download_disabled():
        return None

    dist = Path(GlobalPath.bin()) / "kotlin-ls"
    launcher = dist / ("kotlin-lsp.cmd" if _is_windows() else "kotlin-lsp.sh")
    if launcher.exists():
        return str(launcher)

    release = await asyncio.to_thread(_http_get_json, "https://api.github.com/repos/Kotlin/kotlin-lsp/releases/latest")
    if not release:
        return None

    version = str(release.get("name") or release.get("tag_name") or "").lstrip("v")
    if not version:
        return None

    sys_name = platform.system()
    machine = platform.machine().lower()

    if machine in {"x86_64", "amd64"}:
        arch = "x64"
    elif machine in {"arm64", "aarch64"}:
        arch = "aarch64"
    else:
        return None

    if sys_name == "Darwin":
        target = "mac"
    elif sys_name == "Linux":
        target = "linux"
    elif sys_name == "Windows":
        target = "win"
    else:
        return None

    asset = f"kotlin-lsp-{version}-{target}-{arch}.zip"
    url = f"https://download-cdn.jetbrains.com/kotlin-lsp/{version}/{asset}"

    archive = dist / "kotlin-ls.zip"

    ok = await asyncio.to_thread(_http_download, url, archive)
    if not ok:
        return None

    extracted = await asyncio.to_thread(_extract_archive, archive, dist)
    try:
        archive.unlink(missing_ok=True)
    except Exception:
        pass

    if not extracted or not launcher.exists():
        return None

    await asyncio.to_thread(_set_executable, launcher)
    return str(launcher)


def _set_executable(path: Path) -> None:
    if _is_windows() or not path.exists():
        return
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


async def _kotlin_ls_spawn(root: str, env: Dict[str, str], initialization: Dict[str, Any]) -> Optional[LSPServerHandle]:
    kotlin_ls = _which("kotlin-lsp") or _which("kotlin-ls")
    if not kotlin_ls:
        kotlin_ls = await _install_kotlin_ls()

    if not kotlin_ls:
        return None

    return await _spawn_binary(kotlin_ls, ["--stdio"], root, env, initialization)


KotlinLS = LSPServerInfo(
    server_id="kotlin-ls",
    extensions=[".kt", ".kts"],
    root=_nearest_root(["settings.gradle.kts", "settings.gradle", "gradlew", "gradlew.bat", "build.gradle.kts", "build.gradle", "pom.xml"]),
    spawn=_kotlin_ls_spawn,
)


async def _yaml_ls_spawn(root: str, env: Dict[str, str], initialization: Dict[str, Any]) -> Optional[LSPServerHandle]:
    yaml_ls = _which("yaml-language-server")
    if yaml_ls:
        return await _spawn_binary(yaml_ls, ["--stdio"], root, env, initialization)

    return await _spawn_node_script(
        root,
        "yaml-language-server",
        "out/server/src/server.js",
        ["--stdio"],
        env,
        initialization,
        auto_install=True,
    )


YamlLS = LSPServerInfo(
    server_id="yaml-ls",
    extensions=[".yaml", ".yml"],
    root=_nearest_root(["package-lock.json", "bun.lockb", "bun.lock", "pnpm-lock.yaml", "yarn.lock"]),
    spawn=_yaml_ls_spawn,
)


async def _install_lua_ls() -> Optional[str]:
    if lsp_download_disabled():
        return None

    release = await asyncio.to_thread(
        _http_get_json,
        "https://api.github.com/repos/LuaLS/lua-language-server/releases/latest",
    )
    if not release:
        return None

    tag = release.get("tag_name")
    if not isinstance(tag, str):
        return None

    sys_name = platform.system()
    machine = platform.machine().lower()

    if machine in {"x86_64", "amd64"}:
        arch = "x64"
    elif machine in {"arm64", "aarch64"}:
        arch = "arm64"
    elif machine in {"x86", "i386", "i686"}:
        arch = "ia32"
    else:
        return None

    if sys_name == "Darwin":
        plat = "darwin"
        ext = "tar.gz"
    elif sys_name == "Linux":
        plat = "linux"
        ext = "tar.gz"
    elif sys_name == "Windows":
        plat = "win32"
        ext = "zip"
    else:
        return None

    asset_name = f"lua-language-server-{tag}-{plat}-{arch}.{ext}"
    assets = release.get("assets")
    if not isinstance(assets, list):
        return None

    url = None
    for item in assets:
        if not isinstance(item, dict):
            continue
        if item.get("name") == asset_name:
            url = item.get("browser_download_url")
            break

    if not isinstance(url, str):
        return None

    install_dir = Path(GlobalPath.bin()) / f"lua-language-server-{arch}-{plat}"
    archive = Path(GlobalPath.bin()) / asset_name
    if not await asyncio.to_thread(_http_download, url, archive):
        return None

    extracted = await asyncio.to_thread(_extract_archive, archive, install_dir)
    try:
        archive.unlink(missing_ok=True)
    except Exception:
        pass
    if not extracted:
        return None

    binary = install_dir / "bin" / _bin_name("lua-language-server")
    if not binary.exists():
        return None

    await asyncio.to_thread(_set_executable, binary)
    return str(binary)


async def _lua_ls_spawn(root: str, env: Dict[str, str], initialization: Dict[str, Any]) -> Optional[LSPServerHandle]:
    lua_ls = _which("lua-language-server")
    if not lua_ls:
        lua_ls = await _install_lua_ls()

    if not lua_ls:
        return None

    return await _spawn_binary(lua_ls, [], root, env, initialization)


LuaLS = LSPServerInfo(
    server_id="lua-ls",
    extensions=[".lua"],
    root=_nearest_root([".luarc.json", ".luarc.jsonc", ".luacheckrc", ".stylua.toml", "stylua.toml", "selene.toml", "selene.yml"]),
    spawn=_lua_ls_spawn,
)


async def _php_intelephense_spawn(
    root: str,
    env: Dict[str, str],
    initialization: Dict[str, Any],
) -> Optional[LSPServerHandle]:
    intelephense = _which("intelephense")
    base_init = {"telemetry": {"enabled": False}}

    if intelephense:
        return await _spawn_binary(
            intelephense,
            ["--stdio"],
            root,
            env,
            _merge_initialization(base_init, initialization),
        )

    return await _spawn_node_script(
        root,
        "intelephense",
        "lib/intelephense.js",
        ["--stdio"],
        env,
        _merge_initialization(base_init, initialization),
        auto_install=True,
    )


PHPIntelephense = LSPServerInfo(
    server_id="php intelephense",
    extensions=[".php"],
    root=_nearest_root(["composer.json", "composer.lock", ".php-version"]),
    spawn=_php_intelephense_spawn,
)


async def _prisma_spawn(root: str, env: Dict[str, str], initialization: Dict[str, Any]) -> Optional[LSPServerHandle]:
    prisma = _which("prisma")
    if not prisma:
        return None
    return await _spawn_binary(prisma, ["language-server"], root, env, initialization)


Prisma = LSPServerInfo(
    server_id="prisma",
    extensions=[".prisma"],
    root=_nearest_root(["schema.prisma", "prisma/schema.prisma", "prisma"], ["package.json"]),
    spawn=_prisma_spawn,
)


async def _dart_spawn(root: str, env: Dict[str, str], initialization: Dict[str, Any]) -> Optional[LSPServerHandle]:
    dart = _which("dart")
    if not dart:
        return None
    return await _spawn_binary(dart, ["language-server", "--lsp"], root, env, initialization)


Dart = LSPServerInfo(
    server_id="dart",
    extensions=[".dart"],
    root=_nearest_root(["pubspec.yaml", "analysis_options.yaml"]),
    spawn=_dart_spawn,
)


async def _ocaml_spawn(root: str, env: Dict[str, str], initialization: Dict[str, Any]) -> Optional[LSPServerHandle]:
    ocamllsp = _which("ocamllsp")
    if not ocamllsp:
        return None
    return await _spawn_binary(ocamllsp, [], root, env, initialization)


OcamlLS = LSPServerInfo(
    server_id="ocaml-lsp",
    extensions=[".ml", ".mli"],
    root=_nearest_root(["dune-project", "dune-workspace", ".merlin", "opam"]),
    spawn=_ocaml_spawn,
)


async def _bash_spawn(root: str, env: Dict[str, str], initialization: Dict[str, Any]) -> Optional[LSPServerHandle]:
    bash_ls = _which("bash-language-server")
    if bash_ls:
        return await _spawn_binary(bash_ls, ["start"], root, env, initialization)

    return await _spawn_node_script(
        root,
        "bash-language-server",
        "out/cli.js",
        ["start"],
        env,
        initialization,
        auto_install=True,
    )


BashLS = LSPServerInfo(
    server_id="bash",
    extensions=[".sh", ".bash", ".zsh", ".ksh"],
    root=_instance_root,
    spawn=_bash_spawn,
)


async def _install_terraform_ls() -> Optional[str]:
    if lsp_download_disabled():
        return None

    release = await asyncio.to_thread(
        _http_get_json,
        "https://api.github.com/repos/hashicorp/terraform-ls/releases/latest",
    )
    if not release:
        return None

    version = str(release.get("tag_name") or "").lstrip("v")
    if not version:
        return None

    sys_name = platform.system()
    machine = platform.machine().lower()

    arch = "arm64" if machine in {"arm64", "aarch64"} else "amd64"
    plat = "windows" if sys_name == "Windows" else sys_name.lower()

    asset_name = f"terraform-ls_{version}_{plat}_{arch}.zip"
    assets = release.get("assets")
    if not isinstance(assets, list):
        return None

    url = None
    for item in assets:
        if not isinstance(item, dict):
            continue
        if item.get("name") == asset_name:
            url = item.get("browser_download_url")
            break

    if not isinstance(url, str):
        return None

    archive = Path(GlobalPath.bin()) / asset_name
    if not await asyncio.to_thread(_http_download, url, archive):
        return None

    extracted = await asyncio.to_thread(_extract_archive, archive, Path(GlobalPath.bin()))
    try:
        archive.unlink(missing_ok=True)
    except Exception:
        pass

    if not extracted:
        return None

    binary = Path(GlobalPath.bin()) / _bin_name("terraform-ls")
    if not binary.exists():
        return None

    await asyncio.to_thread(_set_executable, binary)
    return str(binary)


async def _terraform_spawn(root: str, env: Dict[str, str], initialization: Dict[str, Any]) -> Optional[LSPServerHandle]:
    terraform_ls = _which("terraform-ls")
    if not terraform_ls:
        terraform_ls = await _install_terraform_ls()

    if not terraform_ls:
        return None

    base_init = {
        "experimentalFeatures": {
            "prefillRequiredFields": True,
            "validateOnSave": True,
        }
    }

    return await _spawn_binary(
        terraform_ls,
        ["serve"],
        root,
        env,
        _merge_initialization(base_init, initialization),
    )


TerraformLS = LSPServerInfo(
    server_id="terraform",
    extensions=[".tf", ".tfvars"],
    root=_nearest_root([".terraform.lock.hcl", "terraform.tfstate", "*.tf"]),
    spawn=_terraform_spawn,
)


async def _install_tinymist() -> Optional[str]:
    if lsp_download_disabled():
        return None

    release = await asyncio.to_thread(
        _http_get_json,
        "https://api.github.com/repos/Myriad-Dreamin/tinymist/releases/latest",
    )
    if not release:
        return None

    sys_name = platform.system()
    machine = platform.machine().lower()

    arch = "aarch64" if machine in {"arm64", "aarch64"} else "x86_64"
    if sys_name == "Darwin":
        target = "apple-darwin"
        ext = "tar.gz"
    elif sys_name == "Windows":
        target = "pc-windows-msvc"
        ext = "zip"
    else:
        target = "unknown-linux-gnu"
        ext = "tar.gz"

    asset_name = f"tinymist-{arch}-{target}.{ext}"
    assets = release.get("assets")
    if not isinstance(assets, list):
        return None

    url = None
    for item in assets:
        if not isinstance(item, dict):
            continue
        if item.get("name") == asset_name:
            url = item.get("browser_download_url")
            break

    if not isinstance(url, str):
        return None

    archive = Path(GlobalPath.bin()) / asset_name
    if not await asyncio.to_thread(_http_download, url, archive):
        return None

    if ext == "zip":
        extracted = await asyncio.to_thread(_extract_archive, archive, Path(GlobalPath.bin()))
    else:
        extracted = await asyncio.to_thread(_extract_archive, archive, Path(GlobalPath.bin()), 1)

    try:
        archive.unlink(missing_ok=True)
    except Exception:
        pass

    if not extracted:
        return None

    binary = Path(GlobalPath.bin()) / _bin_name("tinymist")
    if not binary.exists():
        return None

    await asyncio.to_thread(_set_executable, binary)
    return str(binary)


async def _tinymist_spawn(root: str, env: Dict[str, str], initialization: Dict[str, Any]) -> Optional[LSPServerHandle]:
    tinymist = _which("tinymist")
    if not tinymist:
        tinymist = await _install_tinymist()

    if not tinymist:
        return None

    return await _spawn_binary(tinymist, [], root, env, initialization)


Tinymist = LSPServerInfo(
    server_id="tinymist",
    extensions=[".typ", ".typc"],
    root=_nearest_root(["typst.toml"]),
    spawn=_tinymist_spawn,
)


async def _gleam_spawn(root: str, env: Dict[str, str], initialization: Dict[str, Any]) -> Optional[LSPServerHandle]:
    gleam = _which("gleam")
    if not gleam:
        return None
    return await _spawn_binary(gleam, ["lsp"], root, env, initialization)


Gleam = LSPServerInfo(
    server_id="gleam",
    extensions=[".gleam"],
    root=_nearest_root(["gleam.toml"]),
    spawn=_gleam_spawn,
)


async def _clojure_spawn(root: str, env: Dict[str, str], initialization: Dict[str, Any]) -> Optional[LSPServerHandle]:
    clj_lsp = _which("clojure-lsp") or _which("clojure-lsp.exe")
    if not clj_lsp:
        return None
    return await _spawn_binary(clj_lsp, ["listen"], root, env, initialization)


ClojureLS = LSPServerInfo(
    server_id="clojure-lsp",
    extensions=[".clj", ".cljs", ".cljc", ".edn"],
    root=_nearest_root(["deps.edn", "project.clj", "shadow-cljs.edn", "bb.edn", "build.boot"]),
    spawn=_clojure_spawn,
)


async def _nixd_root(file: str) -> Optional[str]:
    flake = await _find_nearest_root(file, ["flake.nix"], fallback_to_instance=False)
    if flake and flake != Instance.directory():
        return flake

    worktree = Instance.worktree()
    if worktree and worktree != Instance.directory():
        return worktree

    return Instance.directory()


async def _nixd_spawn(root: str, env: Dict[str, str], initialization: Dict[str, Any]) -> Optional[LSPServerHandle]:
    nixd = _which("nixd")
    if not nixd:
        return None
    return await _spawn_binary(nixd, [], root, env, initialization)


Nixd = LSPServerInfo(
    server_id="nixd",
    extensions=[".nix"],
    root=_nixd_root,
    spawn=_nixd_spawn,
)


async def _hls_spawn(root: str, env: Dict[str, str], initialization: Dict[str, Any]) -> Optional[LSPServerHandle]:
    hls = _which("haskell-language-server-wrapper")
    if not hls:
        return None
    return await _spawn_binary(hls, ["--lsp"], root, env, initialization)


HLS = LSPServerInfo(
    server_id="hls",
    extensions=[".hs", ".lhs"],
    root=_nearest_root(["stack.yaml", "cabal.project", "hie.yaml", "*.cabal"]),
    spawn=_hls_spawn,
)


ALL_SERVERS: Dict[str, LSPServerInfo] = {
    # JavaScript/TypeScript ecosystem
    "astro": Astro,
    "bash": BashLS,
    "deno": Deno,
    "eslint": ESLint,
    "oxlint": Oxlint,
    "svelte": Svelte,
    "typescript": Typescript,
    "vue": Vue,
    "yaml-ls": YamlLS,

    # Systems / native
    "clangd": Clangd,
    "gopls": Gopls,
    "rust": RustAnalyzer,
    "sourcekit-lsp": SourceKit,
    "zls": Zls,

    # JVM / .NET
    "csharp": CSharp,
    "fsharp": FSharp,
    "jdtls": JDTLS,
    "kotlin-ls": KotlinLS,

    # Language-specific
    "clojure-lsp": ClojureLS,
    "dart": Dart,
    "elixir-ls": ElixirLS,
    "gleam": Gleam,
    "hls": HLS,
    "lua-ls": LuaLS,
    "nixd": Nixd,
    "ocaml-lsp": OcamlLS,
    "php intelephense": PHPIntelephense,
    "prisma": Prisma,
    "pyright": Pyright,
    "ruby-lsp": RubyLSP,
    "terraform": TerraformLS,
    "tinymist": Tinymist,
}
