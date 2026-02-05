"""Utility functions for TUI.

This module provides utility functions used throughout the TUI,
including clipboard operations, terminal detection, and formatting.
"""

import os
import subprocess
import sys
from typing import Optional


async def copy_to_clipboard(text: str) -> bool:
    """Copy text to system clipboard.

    Supports multiple clipboard backends:
    - Windows: clip.exe
    - macOS: pbcopy
    - Linux: xclip, xsel, or wl-copy

    Args:
        text: Text to copy

    Returns:
        True if copy succeeded, False otherwise
    """
    try:
        if sys.platform == "win32":
            # Windows
            process = subprocess.Popen(
                ["clip.exe"],
                stdin=subprocess.PIPE,
                shell=True
            )
            process.communicate(text.encode("utf-16le"))
            return process.returncode == 0

        elif sys.platform == "darwin":
            # macOS
            process = subprocess.Popen(
                ["pbcopy"],
                stdin=subprocess.PIPE
            )
            process.communicate(text.encode("utf-8"))
            return process.returncode == 0

        else:
            # Linux - try multiple backends
            for cmd in [["wl-copy"], ["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]]:
                try:
                    process = subprocess.Popen(
                        cmd,
                        stdin=subprocess.PIPE
                    )
                    process.communicate(text.encode("utf-8"))
                    if process.returncode == 0:
                        return True
                except FileNotFoundError:
                    continue

            return False

    except Exception:
        return False


async def get_clipboard_content() -> Optional[str]:
    """Get text from system clipboard.

    Returns:
        Clipboard content or None if failed
    """
    try:
        if sys.platform == "win32":
            # Windows - use PowerShell
            result = subprocess.run(
                ["powershell.exe", "-Command", "Get-Clipboard"],
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                return result.stdout.rstrip("\r\n")

        elif sys.platform == "darwin":
            # macOS
            result = subprocess.run(
                ["pbpaste"],
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                return result.stdout

        else:
            # Linux
            for cmd in [["wl-paste"], ["xclip", "-selection", "clipboard", "-o"], ["xsel", "--clipboard", "--output"]]:
                try:
                    result = subprocess.run(cmd, capture_output=True, text=True)
                    if result.returncode == 0:
                        return result.stdout
                except FileNotFoundError:
                    continue

        return None

    except Exception:
        return None


def detect_terminal_background() -> str:
    """Detect terminal background color mode.

    Attempts to query the terminal for its background color
    to determine if dark or light mode should be used.

    Returns:
        "dark" or "light"
    """
    # Check environment variables first
    colorfgbg = os.environ.get("COLORFGBG", "")
    if colorfgbg:
        # Format: "foreground;background" where 0-6 are dark, 7-15 are light
        parts = colorfgbg.split(";")
        if len(parts) >= 2:
            try:
                bg = int(parts[-1])
                return "light" if bg >= 7 else "dark"
            except ValueError:
                pass

    # Check for common dark terminal indicators
    term = os.environ.get("TERM", "").lower()
    term_program = os.environ.get("TERM_PROGRAM", "").lower()

    # Most modern terminals default to dark
    dark_indicators = ["kitty", "alacritty", "wezterm", "iterm", "hyper"]
    for indicator in dark_indicators:
        if indicator in term or indicator in term_program:
            return "dark"

    # Default to dark mode
    return "dark"


def truncate_text(text: str, max_length: int, suffix: str = "...") -> str:
    """Truncate text to maximum length with suffix.

    Args:
        text: Text to truncate
        max_length: Maximum length including suffix
        suffix: Suffix to append when truncated

    Returns:
        Truncated text
    """
    if len(text) <= max_length:
        return text
    return text[:max_length - len(suffix)] + suffix


def format_duration(ms: float) -> str:
    """Format duration in milliseconds to human-readable string.

    Args:
        ms: Duration in milliseconds

    Returns:
        Formatted duration string
    """
    if ms < 1000:
        return f"{int(ms)}ms"
    elif ms < 60000:
        return f"{ms / 1000:.1f}s"
    elif ms < 3600000:
        minutes = int(ms / 60000)
        seconds = int((ms % 60000) / 1000)
        return f"{minutes}m {seconds}s"
    else:
        hours = int(ms / 3600000)
        minutes = int((ms % 3600000) / 60000)
        return f"{hours}h {minutes}m"


def format_file_size(bytes_size: int) -> str:
    """Format file size to human-readable string.

    Args:
        bytes_size: Size in bytes

    Returns:
        Formatted size string
    """
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if bytes_size < 1024:
            if unit == "B":
                return f"{bytes_size} {unit}"
            return f"{bytes_size:.1f} {unit}"
        bytes_size /= 1024
    return f"{bytes_size:.1f} PB"


def pluralize(count: int, singular: str, plural: Optional[str] = None) -> str:
    """Pluralize a word based on count.

    Args:
        count: Number of items
        singular: Singular form (can contain {} for count)
        plural: Plural form (defaults to singular + "s")

    Returns:
        Formatted string with correct pluralization
    """
    if plural is None:
        plural = singular + "s"

    template = singular if count == 1 else plural
    return template.replace("{}", str(count))


def strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from text.

    Args:
        text: Text with potential ANSI codes

    Returns:
        Text with ANSI codes removed
    """
    import re
    ansi_pattern = re.compile(r'\x1b\[[0-9;]*m')
    return ansi_pattern.sub('', text)


def normalize_path(path: str, base_dir: Optional[str] = None) -> str:
    """Normalize a file path for display.

    Converts absolute paths to relative paths when possible.

    Args:
        path: Path to normalize
        base_dir: Base directory for relative paths

    Returns:
        Normalized path string
    """
    import os.path

    if not path:
        return ""

    if base_dir is None:
        base_dir = os.getcwd()

    if os.path.isabs(path):
        try:
            rel_path = os.path.relpath(path, base_dir)
            # Only use relative if it doesn't go up too many levels
            if not rel_path.startswith("..\\..\\.."):
                return rel_path
        except ValueError:
            pass  # Different drives on Windows

    return path
