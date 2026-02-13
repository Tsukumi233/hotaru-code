"""Theme system for TUI.

This module provides theme definitions and management for the TUI,
supporting both dark and light modes with customizable color schemes.
"""

from dataclasses import dataclass, field
from typing import Dict, Literal, Optional
from pathlib import Path
import json

from ..core.global_paths import GlobalPath


@dataclass
class Theme:
    """Theme color definitions.

    Contains all color values used throughout the TUI interface.
    Colors are specified as hex strings (e.g., "#ffffff").
    """

    # Base colors
    background: str = "#0a0a0a"
    background_panel: str = "#141414"
    background_element: str = "#1e1e1e"
    background_menu: str = "#252525"

    # Text colors
    text: str = "#eeeeee"
    text_muted: str = "#808080"

    # Accent colors
    primary: str = "#3b7dd8"
    secondary: str = "#6b7280"
    accent: str = "#fab283"

    # Status colors
    success: str = "#4ade80"
    warning: str = "#fbbf24"
    error: str = "#f87171"
    info: str = "#60a5fa"

    # Border colors
    border: str = "#333333"
    border_active: str = "#555555"

    # Diff colors
    diff_added: str = "#4ade80"
    diff_removed: str = "#f87171"
    diff_added_bg: str = "#1a2e1a"
    diff_removed_bg: str = "#2e1a1a"
    diff_context_bg: str = "#141414"
    diff_highlight_added: str = "#22c55e"
    diff_highlight_removed: str = "#ef4444"
    diff_line_number: str = "#666666"
    diff_added_line_number_bg: str = "#1a2e1a"
    diff_removed_line_number_bg: str = "#2e1a1a"

    # Agent colors (for different agent types)
    agent_build: str = "#3b82f6"
    agent_plan: str = "#8b5cf6"
    agent_explore: str = "#06b6d4"
    agent_code: str = "#22c55e"

    def to_dict(self) -> Dict[str, str]:
        """Convert theme to dictionary."""
        return {
            "background": self.background,
            "background_panel": self.background_panel,
            "background_element": self.background_element,
            "background_menu": self.background_menu,
            "text": self.text,
            "text_muted": self.text_muted,
            "primary": self.primary,
            "secondary": self.secondary,
            "accent": self.accent,
            "success": self.success,
            "warning": self.warning,
            "error": self.error,
            "info": self.info,
            "border": self.border,
            "border_active": self.border_active,
            "diff_added": self.diff_added,
            "diff_removed": self.diff_removed,
        }


# Predefined dark theme
DARK_THEME = Theme(
    background="#0a0a0a",
    background_panel="#141414",
    background_element="#1e1e1e",
    background_menu="#252525",
    text="#eeeeee",
    text_muted="#808080",
    primary="#3b7dd8",
    secondary="#6b7280",
    accent="#fab283",
    success="#4ade80",
    warning="#fbbf24",
    error="#f87171",
    info="#60a5fa",
    border="#333333",
    border_active="#555555",
)

# Predefined light theme
LIGHT_THEME = Theme(
    background="#ffffff",
    background_panel="#f5f5f5",
    background_element="#ebebeb",
    background_menu="#e0e0e0",
    text="#1a1a1a",
    text_muted="#666666",
    primary="#2563eb",
    secondary="#4b5563",
    accent="#d97706",
    success="#16a34a",
    warning="#ca8a04",
    error="#dc2626",
    info="#2563eb",
    border="#d1d5db",
    border_active="#9ca3af",
    diff_added="#16a34a",
    diff_removed="#dc2626",
    diff_added_bg="#dcfce7",
    diff_removed_bg="#fee2e2",
    diff_context_bg="#f5f5f5",
    diff_highlight_added="#15803d",
    diff_highlight_removed="#b91c1c",
    diff_line_number="#9ca3af",
    diff_added_line_number_bg="#dcfce7",
    diff_removed_line_number_bg="#fee2e2",
)

# Catppuccin Mocha theme
CATPPUCCIN_MOCHA = Theme(
    background="#1e1e2e",
    background_panel="#181825",
    background_element="#313244",
    background_menu="#45475a",
    text="#cdd6f4",
    text_muted="#6c7086",
    primary="#89b4fa",
    secondary="#9399b2",
    accent="#fab387",
    success="#a6e3a1",
    warning="#f9e2af",
    error="#f38ba8",
    info="#89dceb",
    border="#45475a",
    border_active="#585b70",
)

# Dracula theme
DRACULA_THEME = Theme(
    background="#282a36",
    background_panel="#21222c",
    background_element="#343746",
    background_menu="#44475a",
    text="#f8f8f2",
    text_muted="#6272a4",
    primary="#bd93f9",
    secondary="#6272a4",
    accent="#ffb86c",
    success="#50fa7b",
    warning="#f1fa8c",
    error="#ff5555",
    info="#8be9fd",
    border="#44475a",
    border_active="#6272a4",
)

# Nord theme
NORD_THEME = Theme(
    background="#2e3440",
    background_panel="#3b4252",
    background_element="#434c5e",
    background_menu="#4c566a",
    text="#eceff4",
    text_muted="#d8dee9",
    primary="#88c0d0",
    secondary="#81a1c1",
    accent="#ebcb8b",
    success="#a3be8c",
    warning="#ebcb8b",
    error="#bf616a",
    info="#5e81ac",
    border="#4c566a",
    border_active="#d8dee9",
)

# Available themes
THEMES: Dict[str, Theme] = {
    "dark": DARK_THEME,
    "light": LIGHT_THEME,
    "catppuccin-mocha": CATPPUCCIN_MOCHA,
    "dracula": DRACULA_THEME,
    "nord": NORD_THEME,
}


class ThemeManager:
    """Theme manager for the TUI.

    Handles theme selection, persistence, and mode switching.
    """

    _current_theme: str = "dark"
    _mode: Literal["dark", "light"] = "dark"

    @classmethod
    def get_theme(cls) -> Theme:
        """Get the current theme.

        Returns:
            Current Theme instance
        """
        return THEMES.get(cls._current_theme, DARK_THEME)

    @classmethod
    def set_theme(cls, name: str) -> bool:
        """Set the current theme by name.

        Args:
            name: Theme name

        Returns:
            True if theme was set, False if not found
        """
        if name in THEMES:
            cls._current_theme = name
            cls._save_preference()
            return True
        return False

    @classmethod
    def get_mode(cls) -> Literal["dark", "light"]:
        """Get the current color mode.

        Returns:
            Current mode ("dark" or "light")
        """
        return cls._mode

    @classmethod
    def set_mode(cls, mode: Literal["dark", "light"]) -> None:
        """Set the color mode.

        Args:
            mode: Color mode to set
        """
        cls._mode = mode
        # Auto-switch to appropriate theme if using default
        if cls._current_theme in ("dark", "light"):
            cls._current_theme = mode
        cls._save_preference()

    @classmethod
    def toggle_mode(cls) -> Literal["dark", "light"]:
        """Toggle between dark and light mode.

        Returns:
            New mode after toggle
        """
        new_mode: Literal["dark", "light"] = "light" if cls._mode == "dark" else "dark"
        cls.set_mode(new_mode)
        return new_mode

    @classmethod
    def list_themes(cls) -> list[str]:
        """List available theme names.

        Returns:
            List of theme names
        """
        return list(THEMES.keys())

    @classmethod
    def _get_prefs_path(cls) -> Path:
        """Get path to theme preferences file."""
        return Path(GlobalPath.config()) / "theme.json"

    @classmethod
    def _save_preference(cls) -> None:
        """Save theme preference to disk."""
        prefs_path = cls._get_prefs_path()
        try:
            prefs_path.parent.mkdir(parents=True, exist_ok=True)
            with open(prefs_path, "w") as f:
                json.dump({
                    "theme": cls._current_theme,
                    "mode": cls._mode,
                }, f)
        except Exception:
            pass  # Ignore save errors

    @classmethod
    def load_preference(cls) -> None:
        """Load theme preference from disk."""
        prefs_path = cls._get_prefs_path()
        try:
            if prefs_path.exists():
                with open(prefs_path, "r") as f:
                    data = json.load(f)
                    if "theme" in data and data["theme"] in THEMES:
                        cls._current_theme = data["theme"]
                    if "mode" in data and data["mode"] in ("dark", "light"):
                        cls._mode = data["mode"]
        except Exception:
            pass  # Use defaults on error
