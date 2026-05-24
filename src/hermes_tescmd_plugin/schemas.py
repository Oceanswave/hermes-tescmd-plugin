from __future__ import annotations

from typing import Any

from .runtime import ParamSpec, ToolSpec


def _has_meaningful_default(value: object) -> bool:
    return value is not None


def _param_schema(spec: ParamSpec) -> dict[str, Any]:
    schema: dict[str, Any]
    if spec.is_array:
        schema = {
            "type": "array",
            "items": {"type": spec.item_type},
            "description": spec.description,
        }
        if _has_meaningful_default(spec.default):
            schema["default"] = spec.default
        return schema

    schema = {
        "type": spec.value_type,
        "description": spec.description,
    }
    if spec.enum:
        schema["enum"] = list(spec.enum)
    sensitive_markers = (
        "secret",
        "token",
        "password",
        "pin",
        "code",
        "auth",
        "api_key",
        "vin",
        "state",
        "callback_url",
    )
    if any(marker in spec.name.lower() for marker in sensitive_markers):
        schema["writeOnly"] = True
        schema["x-sensitive"] = True
    if spec.minimum is not None:
        schema["minimum"] = spec.minimum
    if spec.maximum is not None:
        schema["maximum"] = spec.maximum
    if _has_meaningful_default(spec.default):
        schema["default"] = spec.default
    return schema


def build_schema(spec: ToolSpec) -> dict[str, Any]:
    properties = {param.name: _param_schema(param) for param in spec.params}
    required = [param.name for param in spec.params if param.required]
    if "confirm" in properties:
        properties["confirm"]["x-confirmation-required"] = True
    return {
        "name": spec.name,
        "description": spec.description,
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        },
    }
