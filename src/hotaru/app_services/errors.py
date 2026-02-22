"""Shared application service exceptions."""

from __future__ import annotations


class NotFoundError(Exception):
    """Raised when an API resource is not found."""

    def __init__(self, resource: str, id: str | None = None):
        self.resource = resource
        self.id = id
        super().__init__(f"{resource} '{id}' not found" if id is not None else f"{resource} not found")
