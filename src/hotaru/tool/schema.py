"""Tool schema normalization helpers."""

from __future__ import annotations

from typing import Any


def strictify_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Return a normalized JSON schema with strict object defaults.

    Any object schema with explicit properties defaults to
    ``additionalProperties=false`` unless already set.
    """
    result = dict(schema or {})

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            node_type = node.get("type")
            props = node.get("properties")
            if node_type == "object" and isinstance(props, dict) and "additionalProperties" not in node:
                node["additionalProperties"] = False

            nested_dict_keys = ("properties", "patternProperties", "$defs", "definitions")
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
            return

        if isinstance(node, list):
            for item in node:
                walk(item)

    walk(result)
    return result
