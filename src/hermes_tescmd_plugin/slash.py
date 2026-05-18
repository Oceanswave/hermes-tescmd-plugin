from __future__ import annotations

import json
import shlex
from collections.abc import Callable
from typing import Any

from . import runtime

_TRUE_VALUES = {"1", "true", "yes", "y", "on"}
_FALSE_VALUES = {"0", "false", "no", "n", "off"}


def _coerce_cli_value(value: str) -> Any:
    lowered = value.strip().lower()
    if lowered in _TRUE_VALUES:
        return True
    if lowered in _FALSE_VALUES:
        return False
    if lowered in {"null", "none"}:
        return None
    if value.startswith("[") or value.startswith("{"):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value


def parse_args(raw_args: str, *, positional_name: str = "vin") -> dict[str, Any]:
    """Parse terse slash-command arguments into plugin tool args.

    Supports ``key=value``/``key:value`` tokens plus one bare positional token
    (usually ``vin``). Comma-separated values are used for list-like fields such
    as ``endpoints`` or ``place_ids``.
    """
    args: dict[str, Any] = {}
    if not raw_args.strip():
        return args
    for token in shlex.split(raw_args):
        key: str | None = None
        value: str | None = None
        if "=" in token:
            key, value = token.split("=", 1)
        elif ":" in token and not token.startswith(("http://", "https://")):
            key, value = token.split(":", 1)
        else:
            if positional_name and positional_name not in args:
                args[positional_name] = token
            else:
                args.setdefault("extra", []).append(token)
            continue
        key = key.strip().replace("-", "_")
        value = (value or "").strip()
        if key in {"endpoints", "place_ids", "scopes", "vins"} and value:
            args[key] = [part.strip() for part in value.split(",") if part.strip()]
        else:
            args[key] = _coerce_cli_value(value)
    return args


def _tool_specs_by_name() -> dict[str, runtime.ToolSpec]:
    return {spec.name: spec for spec in runtime.list_tool_specs()}


def _run_tool(tool_name: str, raw_args: str = "") -> dict[str, Any]:
    specs = _tool_specs_by_name()
    spec = specs[tool_name]
    payload = runtime.make_handler(spec)(parse_args(raw_args))
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return {"ok": False, "operation": spec.operation, "error": payload}


def _compact_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True)


def _format_status(payload: dict[str, Any]) -> str:
    if not payload.get("ok"):
        return _compact_json(payload)
    bootstrap = payload.get("bootstrap") if isinstance(payload.get("bootstrap"), dict) else {}
    lines = ["Tesla Fleet status"]
    for key in (
        "app_configured",
        "authenticated",
        "ready_for_vehicle_reads",
        "ready_for_vehicle_commands",
        "ready_for_signed_commands",
        "key_hosting_ready",
    ):
        if key in bootstrap:
            lines.append(f"- {key}: {bootstrap[key]}")
    next_action = payload.get("next_action")
    if next_action:
        lines.append(f"- next_action: {next_action}")
    next_steps = payload.get("next_steps")
    if isinstance(next_steps, list) and next_steps:
        lines.append("Next steps:")
        lines.extend(f"- {step}" for step in next_steps[:3])
    return "\n".join(lines)


def _format_vehicles(payload: dict[str, Any]) -> str:
    if not payload.get("ok"):
        return _compact_json(payload)
    vehicles = payload.get("vehicles") or payload.get("response") or []
    if not isinstance(vehicles, list):
        return _compact_json(payload)
    lines = [f"Tesla vehicles: {len(vehicles)}"]
    for idx, vehicle in enumerate(vehicles, 1):
        if not isinstance(vehicle, dict):
            lines.append(f"{idx}. {vehicle}")
            continue
        name = vehicle.get("display_name") or vehicle.get("vehicle_name") or vehicle.get("name") or "Unnamed"
        state = vehicle.get("state") or vehicle.get("vehicle_state") or "unknown"
        identifiers = [str(vehicle.get(k)) for k in ("id_s", "vehicle_id", "vin") if vehicle.get(k)]
        ident = identifiers[0] if identifiers else "no id"
        lines.append(f"{idx}. {name} — {state} — {ident}")
    return "\n".join(lines)


def _format_command(name: str, payload: dict[str, Any]) -> str:
    if payload.get("ok"):
        return f"/{name}: ok\n" + _compact_json(payload)
    return f"/{name}: failed\n" + _compact_json(payload)


_COMMANDS: dict[str, tuple[str, str, Callable[[dict[str, Any]], str]]] = {
    "tescmd-status": (
        "Show Tesla plugin readiness and next steps.",
        "[profile=default]",
        lambda ctx: _format_status(_run_tool("tescmd_status", ctx["raw_args"])),
    ),
    "tescmd-vehicles": (
        "List Tesla vehicles on the account.",
        "[profile=default] [region=na|eu|cn]",
        lambda ctx: _format_vehicles(_run_tool("tescmd_vehicle_list", ctx["raw_args"])),
    ),
    "tescmd-vehicle-status": (
        "Fetch selected vehicle status. Optional endpoints=a,b limits payload.",
        "[vin] [endpoints=charge_state,drive_state] [wake=true confirm=true]",
        lambda ctx: _format_command("tescmd-vehicle-status", _run_tool("tescmd_vehicle_status", ctx["raw_args"])),
    ),
    "tescmd-charge": (
        "Fetch charge-state data for the selected vehicle.",
        "[vin] [wake=true confirm=true]",
        lambda ctx: _format_command("tescmd-charge", _run_tool("tescmd_charge_status", ctx["raw_args"])),
    ),
    "tescmd-climate": (
        "Fetch climate-state data for the selected vehicle.",
        "[vin] [wake=true confirm=true]",
        lambda ctx: _format_command("tescmd-climate", _run_tool("tescmd_climate_status", ctx["raw_args"])),
    ),
    "tescmd-location": (
        "Fetch vehicle location data.",
        "[vin] [wake=true confirm=true]",
        lambda ctx: _format_command("tescmd-location", _run_tool("tescmd_vehicle_location", ctx["raw_args"])),
    ),
    "tescmd-wake": (
        "Wake the selected vehicle; requires confirm=true.",
        "[vin] confirm=true",
        lambda ctx: _format_command("tescmd-wake", _run_tool("tescmd_vehicle_wake", ctx["raw_args"])),
    ),
    "tescmd-flash": (
        "Flash the selected vehicle lights; requires confirm=true.",
        "[vin] confirm=true",
        lambda ctx: _format_command("tescmd-flash", _run_tool("tescmd_security_flash_lights", ctx["raw_args"])),
    ),
    "tescmd-honk": (
        "Honk the selected vehicle horn; requires confirm=true.",
        "[vin] confirm=true",
        lambda ctx: _format_command("tescmd-honk", _run_tool("tescmd_security_honk_horn", ctx["raw_args"])),
    ),
    "tescmd-lock": (
        "Lock the selected vehicle; requires confirm=true.",
        "[vin] confirm=true",
        lambda ctx: _format_command("tescmd-lock", _run_tool("tescmd_security_lock", ctx["raw_args"])),
    ),
}


def command_definitions() -> dict[str, dict[str, Any]]:
    return {
        name: {"description": description, "args_hint": args_hint, "handler": handler}
        for name, (description, args_hint, handler) in _COMMANDS.items()
    }


def register_commands(ctx: Any) -> None:
    for name, entry in command_definitions().items():
        ctx.register_command(
            name=name,
            handler=lambda raw_args, _handler=entry["handler"]: _handler({"raw_args": raw_args}),
            description=entry["description"],
            args_hint=entry["args_hint"],
        )
