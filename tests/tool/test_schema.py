from __future__ import annotations

from typing import Any

from hotaru.tool.schema import strictify_schema


def _contains_key(node: Any, key: str) -> bool:
    if isinstance(node, dict):
        if key in node:
            return True
        return any(_contains_key(value, key) for value in node.values())
    if isinstance(node, list):
        return any(_contains_key(item, key) for item in node)
    return False


def test_strictify_schema_removes_title_recursively() -> None:
    schema = {
        "title": "Root",
        "type": "object",
        "properties": {
            "filePath": {"type": "string", "title": "File path"},
            "list": {
                "type": "array",
                "items": {
                    "title": "Item",
                    "type": "object",
                    "properties": {"name": {"type": "string", "title": "Name"}},
                },
            },
        },
        "$defs": {
            "inner": {
                "title": "Inner",
                "type": "object",
                "properties": {"ok": {"type": "boolean", "title": "Ok"}},
            }
        },
    }

    result = strictify_schema(schema)

    assert _contains_key(result, "title") is False


def test_strictify_schema_flattens_nullable_anyof_optional_field() -> None:
    schema = {
        "type": "object",
        "properties": {
            "workdir": {
                "title": "Workdir",
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
            }
        },
    }

    result = strictify_schema(schema)
    prop = result["properties"]["workdir"]

    assert result["additionalProperties"] is False
    assert prop["type"] == "string"
    assert "anyOf" not in prop
    assert "default" not in prop
    assert "title" not in prop


def test_strictify_schema_flattens_nullable_type_list() -> None:
    schema = {
        "type": "object",
        "properties": {
            "path": {
                "type": ["string", "null"],
                "default": None,
            }
        },
    }

    result = strictify_schema(schema)
    prop = result["properties"]["path"]

    assert prop["type"] == "string"
    assert "default" not in prop


def test_strictify_schema_keeps_complex_anyof_unchanged() -> None:
    schema = {
        "type": "object",
        "properties": {
            "value": {
                "anyOf": [{"type": "string"}, {"type": "integer"}, {"type": "null"}],
                "default": None,
            }
        },
    }

    result = strictify_schema(schema)
    prop = result["properties"]["value"]

    assert "anyOf" in prop
    assert prop["default"] is None


def test_strictify_schema_adds_object_strictness_after_anyof_flatten() -> None:
    schema = {
        "type": "object",
        "properties": {
            "outer": {
                "anyOf": [
                    {
                        "type": "object",
                        "properties": {"value": {"type": "string"}},
                    },
                    {"type": "null"},
                ],
                "default": None,
            }
        },
    }

    result = strictify_schema(schema)
    outer = result["properties"]["outer"]

    assert outer["type"] == "object"
    assert outer["additionalProperties"] is False
    assert "anyOf" not in outer
    assert "default" not in outer
