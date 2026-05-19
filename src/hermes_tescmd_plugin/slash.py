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


def _run_tool(tool_name: str, raw_args: str = "", defaults: dict[str, Any] | None = None) -> dict[str, Any]:
    specs = _tool_specs_by_name()
    spec = specs[tool_name]
    args = parse_args(raw_args)
    if defaults:
        args = {**defaults, **args}
    payload = runtime.make_handler(spec)(args)
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


def _add_slash_confirmation_hint(name: str, payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("ok"):
        return payload
    error = str(payload.get("error") or "")
    if "confirm=true is required" not in error:
        return payload
    hinted = dict(payload)
    hinted.setdefault("how_to_run", f"Retry the slash command with confirm=true, for example: /{name} confirm=true")
    hinted.setdefault("retry_command", f"/{name} confirm=true")
    hinted.setdefault(
        "why_confirm_is_required",
        "This command has a real-world vehicle side effect. The explicit confirm=true token is the safety acknowledgement.",
    )
    return hinted


def _friendly_label(name: str) -> str:
    label = name.removeprefix("tescmd-").replace("-", " ")
    return label[:1].upper() + label[1:]


def _stringify(value: Any) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if value is None:
        return "unknown"
    return str(value)


def _first_dict(*values: Any) -> dict[str, Any]:
    for value in values:
        if isinstance(value, dict):
            return value
    return {}


def _vehicle_hint(payload: dict[str, Any]) -> str | None:
    vehicle = _first_dict(payload.get("vehicle"))
    name = vehicle.get("display_name") or vehicle.get("vehicle_name") or vehicle.get("name")
    vin = payload.get("vin") or vehicle.get("vin") or vehicle.get("id_s") or vehicle.get("vehicle_id")
    if name and vin:
        return f"{name} ({vin})"
    if name:
        return str(name)
    if vin:
        return str(vin)
    return None


def _payload_section(payload: dict[str, Any], *keys: str) -> dict[str, Any]:
    for container in (payload, payload.get("data") if isinstance(payload.get("data"), dict) else None):
        if not isinstance(container, dict):
            continue
        for key in keys:
            value = container.get(key)
            if isinstance(value, dict):
                return value
    return {}


def _summarize_success(name: str, payload: dict[str, Any]) -> list[str]:
    label = _friendly_label(name)
    lines = [f"/{name}: success — {label} completed."]
    target = _vehicle_hint(payload)
    if target:
        lines.append(f"Vehicle: {target}")
    profile = payload.get("profile")
    region = payload.get("region")
    if profile or region:
        bits = []
        if profile:
            bits.append(f"profile {profile}")
        if region:
            bits.append(f"region {region}")
        lines.append("Context: " + ", ".join(bits))

    charge = _payload_section(payload, "charge_state")
    if charge:
        lines.append(
            "Charge: "
            + ", ".join(
                part
                for part in (
                    f"{charge.get('battery_level')}%" if charge.get("battery_level") is not None else None,
                    str(charge.get("charging_state")) if charge.get("charging_state") else None,
                    f"limit {charge.get('charge_limit_soc')}%" if charge.get("charge_limit_soc") is not None else None,
                )
                if part
            )
        )

    climate = _payload_section(payload, "climate_state")
    if climate:
        lines.append(
            "Climate: "
            + ", ".join(
                part
                for part in (
                    "on" if climate.get("is_climate_on") else "off" if climate.get("is_climate_on") is not None else None,
                    f"inside {climate.get('inside_temp')}°" if climate.get("inside_temp") is not None else None,
                    f"outside {climate.get('outside_temp')}°" if climate.get("outside_temp") is not None else None,
                )
                if part
            )
        )

    location = _payload_section(payload, "location", "location_data", "drive_state")
    lat = location.get("latitude") or location.get("lat")
    lon = location.get("longitude") or location.get("lon") or location.get("lng")
    if lat is not None and lon is not None:
        lines.append(f"Location: {lat}, {lon}")

    response = _first_dict(payload.get("response"), payload.get("result"), payload.get("payload"))
    result = response.get("result") or response.get("reason") or response.get("message") or payload.get("message")
    if result:
        lines.append(f"Result: {_stringify(result)}")
    elif not any(line.startswith(("Charge:", "Climate:", "Location:")) for line in lines):
        lines.append("Result: command accepted by Tesla Fleet API.")

    cache = payload.get("cache")
    if isinstance(cache, dict) and cache.get("hit") is True:
        lines.append("Source: cached vehicle data")
    return lines


def _summarize_failure(name: str, payload: dict[str, Any]) -> list[str]:
    label = _friendly_label(name)
    error = str(payload.get("error") or "Unknown error")
    lines = [f"/{name}: failed — {label} did not run.", f"Reason: {error}"]
    retry = payload.get("retry_command")
    if retry:
        lines.append(f"Try: {retry}")
    why = payload.get("why_confirm_is_required")
    if why:
        lines.append(str(why))
    next_action = payload.get("next_action")
    if next_action:
        lines.append(f"Next action: {next_action}")
    status_code = payload.get("status_code")
    if status_code:
        lines.append(f"Tesla API status: {status_code}")
    return lines


def _format_command(name: str, payload: dict[str, Any]) -> str:
    payload = _add_slash_confirmation_hint(name, payload)
    if payload.get("ok"):
        return "\n".join(_summarize_success(name, payload))
    return "\n".join(_summarize_failure(name, payload))


_COMMANDS: dict[str, tuple[str, str, Callable[[dict[str, Any]], str]]] = {
    "tescmd-status": (
        "Show Tesla plugin readiness and next steps.",
        "[profile=default]",
        lambda ctx: _format_status(_run_tool("tescmd_status", ctx["raw_args"])),
    ),
    "tescmd-auth-status": (
        "Show OAuth/profile/key readiness details.",
        "[profile=default]",
        lambda ctx: _format_command("tescmd-auth-status", _run_tool("tescmd_auth_status", ctx["raw_args"])),
    ),
    "tescmd-key-show": (
        "Show vehicle-command key status and enrollment URLs.",
        "[profile=default]",
        lambda ctx: _format_command("tescmd-key-show", _run_tool("tescmd_key_show", ctx["raw_args"])),
    ),
    "tescmd-key-validate": (
        "Validate configured public vehicle-command key hosting.",
        "[profile=default]",
        lambda ctx: _format_command("tescmd-key-validate", _run_tool("tescmd_key_validate", ctx["raw_args"])),
    ),
    "tescmd-cache-status": (
        "Show plugin-native response cache status.",
        "[profile=default]",
        lambda ctx: _format_command("tescmd-cache-status", _run_tool("tescmd_cache_status", ctx["raw_args"])),
    ),
    "tescmd-cache-clear": (
        "Clear plugin-native response cache; requires confirm=true.",
        "[profile=default] confirm=true",
        lambda ctx: _format_command("tescmd-cache-clear", _run_tool("tescmd_cache_clear", ctx["raw_args"])),
    ),
    "tescmd-audit-log": (
        "Show recent redacted side-effect command and wake audit events.",
        "[limit=20]",
        lambda ctx: _format_command("tescmd-audit-log", _run_tool("tescmd_audit_log", ctx["raw_args"])),
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
    "tescmd-drive": (
        "Fetch drive/route/GPS state for the selected vehicle.",
        "[vin] [wake=true confirm=true]",
        lambda ctx: _format_command("tescmd-drive", _run_tool("tescmd_vehicle_drive_status", ctx["raw_args"])),
    ),
    "tescmd-closures": (
        "Fetch door/window/trunk/charge-port closure state.",
        "[vin] [wake=true confirm=true]",
        lambda ctx: _format_command("tescmd-closures", _run_tool("tescmd_vehicle_closures_status", ctx["raw_args"])),
    ),
    "tescmd-config": (
        "Fetch model/trim/capability metadata.",
        "[vin] [wake=true confirm=true]",
        lambda ctx: _format_command("tescmd-config", _run_tool("tescmd_vehicle_config_status", ctx["raw_args"])),
    ),
    "tescmd-gui": (
        "Fetch GUI/unit preferences.",
        "[vin] [wake=true confirm=true]",
        lambda ctx: _format_command("tescmd-gui", _run_tool("tescmd_vehicle_gui_settings", ctx["raw_args"])),
    ),
    "tescmd-security-status": (
        "Fetch lock/security state.",
        "[vin] [wake=true confirm=true]",
        lambda ctx: _format_command("tescmd-security-status", _run_tool("tescmd_security_status", ctx["raw_args"])),
    ),
    "tescmd-software": (
        "Fetch software/update status.",
        "[vin] [wake=true confirm=true]",
        lambda ctx: _format_command("tescmd-software", _run_tool("tescmd_software_status", ctx["raw_args"])),
    ),
    "tescmd-nearby-chargers": (
        "Fetch nearby charging sites.",
        "[vin]",
        lambda ctx: _format_command("tescmd-nearby-chargers", _run_tool("tescmd_vehicle_nearby_chargers", ctx["raw_args"])),
    ),
    "tescmd-alerts": (
        "Fetch recent vehicle alerts.",
        "[vin]",
        lambda ctx: _format_command("tescmd-alerts", _run_tool("tescmd_vehicle_alerts", ctx["raw_args"])),
    ),
    "tescmd-release-notes": (
        "Fetch firmware release notes.",
        "[vin]",
        lambda ctx: _format_command("tescmd-release-notes", _run_tool("tescmd_vehicle_release_notes", ctx["raw_args"])),
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
    "tescmd-unlock": (
        "Unlock the selected vehicle; requires confirm=true.",
        "[vin] confirm=true",
        lambda ctx: _format_command("tescmd-unlock", _run_tool("tescmd_security_unlock", ctx["raw_args"])),
    ),
    "tescmd-sentry": (
        "Enable or disable Sentry Mode; requires confirm=true.",
        "[vin] enabled=true|false confirm=true",
        lambda ctx: _format_command("tescmd-sentry", _run_tool("tescmd_security_sentry_mode", ctx["raw_args"])),
    ),
    "tescmd-climate-start": (
        "Start climate control; requires confirm=true.",
        "[vin] confirm=true",
        lambda ctx: _format_command("tescmd-climate-start", _run_tool("tescmd_climate_start", ctx["raw_args"])),
    ),
    "tescmd-climate-stop": (
        "Stop climate control; requires confirm=true.",
        "[vin] confirm=true",
        lambda ctx: _format_command("tescmd-climate-stop", _run_tool("tescmd_climate_stop", ctx["raw_args"])),
    ),
    "tescmd-set-temp": (
        "Set driver/passenger cabin temperatures; requires confirm=true.",
        "[vin] driver_temp=70 passenger_temp=70 confirm=true",
        lambda ctx: _format_command("tescmd-set-temp", _run_tool("tescmd_climate_set_temps", ctx["raw_args"])),
    ),
    "tescmd-charge-start": (
        "Start charging; requires confirm=true.",
        "[vin] confirm=true",
        lambda ctx: _format_command("tescmd-charge-start", _run_tool("tescmd_charge_start", ctx["raw_args"])),
    ),
    "tescmd-charge-stop": (
        "Stop charging; requires confirm=true.",
        "[vin] confirm=true",
        lambda ctx: _format_command("tescmd-charge-stop", _run_tool("tescmd_charge_stop", ctx["raw_args"])),
    ),
    "tescmd-charge-limit": (
        "Set charge limit percentage; requires confirm=true.",
        "[vin] percent=80 confirm=true",
        lambda ctx: _format_command("tescmd-charge-limit", _run_tool("tescmd_charge_limit", ctx["raw_args"])),
    ),
    "tescmd-charge-amps": (
        "Set charge amperage; requires confirm=true.",
        "[vin] amps=32 confirm=true",
        lambda ctx: _format_command("tescmd-charge-amps", _run_tool("tescmd_charge_set_amps", ctx["raw_args"])),
    ),
    "tescmd-charge-port-open": (
        "Open charge port; requires confirm=true.",
        "[vin] confirm=true",
        lambda ctx: _format_command("tescmd-charge-port-open", _run_tool("tescmd_charge_port_open", ctx["raw_args"])),
    ),
    "tescmd-charge-port-close": (
        "Close charge port; requires confirm=true.",
        "[vin] confirm=true",
        lambda ctx: _format_command("tescmd-charge-port-close", _run_tool("tescmd_charge_port_close", ctx["raw_args"])),
    ),
    "tescmd-frunk": (
        "Actuate the front trunk; requires confirm=true.",
        "[vin] confirm=true",
        lambda ctx: _format_command("tescmd-frunk", _run_tool("tescmd_vehicle_actuate_trunk", ctx["raw_args"], {"which_trunk": "front"})),
    ),
    "tescmd-trunk-open": (
        "Open rear trunk; requires confirm=true.",
        "[vin] confirm=true",
        lambda ctx: _format_command("tescmd-trunk-open", _run_tool("tescmd_vehicle_trunk_open", ctx["raw_args"])),
    ),
    "tescmd-trunk-close": (
        "Close rear trunk; requires confirm=true.",
        "[vin] confirm=true",
        lambda ctx: _format_command("tescmd-trunk-close", _run_tool("tescmd_vehicle_trunk_close", ctx["raw_args"])),
    ),
    "tescmd-window-vent": (
        "Vent windows; requires confirm=true.",
        "[vin] confirm=true [lat=.. lon=..]",
        lambda ctx: _format_command("tescmd-window-vent", _run_tool("tescmd_vehicle_window_control", ctx["raw_args"], {"command": "vent"})),
    ),
    "tescmd-window-close": (
        "Close windows; requires confirm=true.",
        "[vin] confirm=true [lat=.. lon=..]",
        lambda ctx: _format_command("tescmd-window-close", _run_tool("tescmd_vehicle_window_control", ctx["raw_args"], {"command": "close"})),
    ),
    "tescmd-media-play": (
        "Toggle media playback; requires confirm=true.",
        "[vin] confirm=true",
        lambda ctx: _format_command("tescmd-media-play", _run_tool("tescmd_media_toggle_playback", ctx["raw_args"])),
    ),
    "tescmd-media-next": (
        "Skip to next track; requires confirm=true.",
        "[vin] confirm=true",
        lambda ctx: _format_command("tescmd-media-next", _run_tool("tescmd_media_next_track", ctx["raw_args"])),
    ),
    "tescmd-media-prev": (
        "Go to previous track; requires confirm=true.",
        "[vin] confirm=true",
        lambda ctx: _format_command("tescmd-media-prev", _run_tool("tescmd_media_prev_track", ctx["raw_args"])),
    ),
    "tescmd-media-volume-up": (
        "Increase media volume; requires confirm=true.",
        "[vin] confirm=true",
        lambda ctx: _format_command("tescmd-media-volume-up", _run_tool("tescmd_media_volume_up", ctx["raw_args"])),
    ),
    "tescmd-media-volume-down": (
        "Decrease media volume; requires confirm=true.",
        "[vin] confirm=true",
        lambda ctx: _format_command("tescmd-media-volume-down", _run_tool("tescmd_media_volume_down", ctx["raw_args"])),
    ),
    "tescmd-media-volume-set": (
        "Set media volume; requires confirm=true.",
        "[vin] volume=3 confirm=true",
        lambda ctx: _format_command("tescmd-media-volume-set", _run_tool("tescmd_media_volume_set", ctx["raw_args"])),
    ),
    "tescmd-nav": (
        "Send navigation destination string; requires confirm=true.",
        "[vin] destination='address or place' confirm=true",
        lambda ctx: _format_command("tescmd-nav", _run_tool("tescmd_navigation_send", ctx["raw_args"])),
    ),
    "tescmd-nav-search": (
        "Search Google Places for navigation Place IDs.",
        "query='address or place' [limit=5]",
        lambda ctx: _format_command("tescmd-nav-search", _run_tool("tescmd_navigation_place_search", ctx["raw_args"])),
    ),
    "tescmd-nav-waypoints": (
        "Send Google Place ID waypoints; requires confirm=true.",
        "[vin] place_ids=id1,id2 confirm=true",
        lambda ctx: _format_command("tescmd-nav-waypoints", _run_tool("tescmd_navigation_waypoints", ctx["raw_args"])),
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
