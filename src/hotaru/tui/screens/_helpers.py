"""Shared helpers for screen modules."""

from typing import List

from ..commands import CommandRegistry
from ..widgets import SlashCommandItem

_INTERRUPT_WINDOW_SECONDS = 5.0


def build_slash_commands(registry: CommandRegistry) -> List[SlashCommandItem]:
    """Build slash command items from registry."""
    items: List[SlashCommandItem] = []
    for cmd in registry.list_commands():
        if not cmd.slash_name:
            continue

        description = cmd.availability_reason if not cmd.enabled else ""
        items.append(
            SlashCommandItem(
                id=cmd.id,
                trigger=cmd.slash_name,
                title=cmd.title,
                description=description,
                keybind=cmd.keybind,
                type="builtin",
            )
        )

        for alias in cmd.slash_aliases:
            items.append(
                SlashCommandItem(
                    id=cmd.id,
                    trigger=alias,
                    title=cmd.title,
                    description=f"Alias for /{cmd.slash_name}",
                    keybind=cmd.keybind,
                    type="builtin",
                )
            )
    return items
