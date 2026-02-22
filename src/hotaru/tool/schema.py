"""Tool schema normalization helpers."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def strictify_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Return a normalized JSON schema with strict object defaults.

    Any object schema with explicit properties defaults to
    ``additionalProperties=false`` unless already set.
    """
    result = deepcopy(schema or {})

    def _is_null(branch: Any) -> bool:
        return isinstance(branch, dict) and branch.get("type") == "null"

    def _normalize_nullable_type(node: dict[str, Any]) -> None:
        value = node.get("type")
        if not isinstance(value, list):
            return
        if len(value) != 2 or not all(isinstance(item, str) for item in value):
            return
        if "null" not in value:
            return
        non_null = [item for item in value if item != "null"]
        if len(non_null) != 1:
            return
        node["type"] = non_null[0]
        if node.get("default") is None:
            node.pop("default", None)

    def _normalize_nullable_anyof(node: dict[str, Any]) -> None:
        value = node.get("anyOf")
        if not isinstance(value, list) or len(value) != 2:
            return
        null_count = sum(1 for item in value if _is_null(item))
        if null_count != 1:
            return
        branch = next((item for item in value if isinstance(item, dict) and not _is_null(item)), None)
        if branch is None:
            return
        if node.get("default") is None:
            node.pop("default", None)
        node.pop("anyOf", None)
        for key, item in branch.items():
            if key == "title":
                continue
            if key not in node:
                node[key] = item

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            node.pop("title", None)
            _normalize_nullable_type(node)
            _normalize_nullable_anyof(node)

            node_type = node.get("type")
            props = node.get("properties")
            if node_type == "object" and isinstance(props, dict) and "additionalProperties" not in node:
                node["additionalProperties"] = False

            nested_dict_keys = ("properties", "patternProperties", "$defs", "definitions", "dependentSchemas")
            for key in nested_dict_keys:
                value = node.get(key)
                if isinstance(value, dict):
                    for sub in value.values():
                        walk(sub)

            items = node.get("items")
            if isinstance(items, dict):
                walk(items)
            elif isinstance(items, list):
                for sub in items:
                    walk(sub)

            for key in ("anyOf", "oneOf", "allOf"):
                value = node.get(key)
                if isinstance(value, list):
                    for sub in value:
                        walk(sub)

            not_schema = node.get("not")
            if isinstance(not_schema, dict):
                walk(not_schema)

            nested_schema_keys = (
                "additionalProperties",
                "unevaluatedProperties",
                "contains",
                "propertyNames",
                "if",
                "then",
                "else",
            )
            for key in nested_schema_keys:
                value = node.get(key)
                if isinstance(value, dict):
                    walk(value)
            return

        if isinstance(node, list):
            for item in node:
                walk(item)

    walk(result)
    return result
