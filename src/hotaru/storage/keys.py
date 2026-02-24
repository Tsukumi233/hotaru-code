"""Typed factory methods for storage key construction."""

from __future__ import annotations


class StorageKey:
    """Namespace providing typed key factories for the Storage layer."""

    @staticmethod
    def session(project_id: str, session_id: str) -> list[str]:
        return ["session", project_id, session_id]

    @staticmethod
    def session_prefix(project_id: str) -> list[str]:
        return ["session", project_id]

    @staticmethod
    def session_index(session_id: str) -> list[str]:
        return ["session_index", session_id]

    @staticmethod
    def message(session_id: str, message_id: str) -> list[str]:
        return ["message_store", session_id, message_id]

    @staticmethod
    def message_prefix(session_id: str) -> list[str]:
        return ["message_store", session_id]

    @staticmethod
    def part(session_id: str, part_id: str) -> list[str]:
        return ["part", session_id, part_id]

    @staticmethod
    def part_prefix(session_id: str) -> list[str]:
        return ["part", session_id]

    @staticmethod
    def permission_approval(project_id: str) -> list[str]:
        return ["permission_approval", project_id]
