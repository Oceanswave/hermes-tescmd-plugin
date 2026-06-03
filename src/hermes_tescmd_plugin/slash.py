from __future__ import annotations

import json
import re
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


def _run_tool(
    tool_name: str,
    raw_args: str = "",
    defaults: dict[str, Any] | None = None,
    *,
    positional_name: str = "vin",
    expose_args: tuple[str, ...] = (),
) -> dict[str, Any]:
    specs = _tool_specs_by_name()
    spec = specs[tool_name]
    args = parse_args(raw_args, positional_name=positional_name)
    if positional_name != "vin" and args.get("extra") and positional_name in args:
        extra = args.pop("extra")
        if isinstance(extra, list):
            args[positional_name] = " ".join(
                str(part) for part in (args[positional_name], *extra) if str(part)
            )
    if defaults:
        args = {**defaults, **args}
    payload = runtime.make_handler(spec)(args)
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        return {"ok": False, "operation": spec.operation, "error": payload}
    if expose_args and isinstance(parsed, dict) and parsed.get("ok"):
        request = {
            key: args[key]
            for key in expose_args
            if key in args and args[key] is not None
        }
        if request:
            parsed["request"] = request
    return parsed


def _compact_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True)


def _format_status(payload: dict[str, Any]) -> str:
    if not payload.get("ok"):
        return _format_command("tescmd-status", payload)
    raw_bootstrap = payload.get("bootstrap")
    bootstrap: dict[str, Any] = raw_bootstrap if isinstance(raw_bootstrap, dict) else {}
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
        lines.append(f"- next_action: {_redact_slash_text(next_action)}")
    next_steps = payload.get("next_steps")
    if isinstance(next_steps, list) and next_steps:
        lines.append("Next steps:")
        lines.extend(f"- {_redact_slash_text(step)}" for step in next_steps[:3])
    return "\n".join(lines)


def _format_auth_status(payload: dict[str, Any]) -> str:
    if not payload.get("ok"):
        return _format_command("tescmd-auth-status", payload)

    lines = ["Tesla auth status"]
    for key in ("profile", "region", "domain"):
        value = payload.get(key)
        if value:
            lines.append(f"- {key}: {_redact_slash_text(value)}")
    for key in ("configured", "authenticated", "pending_login"):
        if key in payload:
            lines.append(f"- {key}: {_stringify(payload[key])}")

    default_vin = payload.get("default_vin")
    if default_vin:
        lines.append(f"- default vehicle: {_redact_slash_text(default_vin)}")

    bootstrap = payload.get("bootstrap")
    scope_readiness = (
        bootstrap.get("scope_readiness") if isinstance(bootstrap, dict) else None
    )
    if isinstance(scope_readiness, dict):
        source = scope_readiness.get("grant_scope_source")
        if source:
            lines.append(f"- scope source: {_redact_slash_text(source)}")
        missing = scope_readiness.get("missing_granted_user_scopes")
        if isinstance(missing, list) and missing:
            lines.append(
                "- missing granted scopes: "
                + ", ".join(_redact_slash_text(scope) for scope in missing)
            )
        elif payload.get("authenticated"):
            lines.append("- missing granted scopes: none detected")

        capabilities = scope_readiness.get("capabilities")
        if isinstance(capabilities, dict) and capabilities:
            capability_lines = []
            for name, details in capabilities.items():
                if not isinstance(details, dict):
                    continue
                state = "ready" if details.get("ready") else "missing"
                capability_line = f"{_redact_slash_text(name)}={state}"
                missing_scopes = details.get("missing_scopes")
                if isinstance(missing_scopes, list) and missing_scopes:
                    capability_line += (
                        " (needs "
                        + ", ".join(
                            _redact_slash_text(scope) for scope in missing_scopes
                        )
                        + ")"
                    )
                capability_lines.append(capability_line)
            if capability_lines:
                lines.append("Capabilities: " + "; ".join(capability_lines))

    configured_scopes = payload.get("configured_user_scopes") or payload.get("scopes")
    if isinstance(configured_scopes, list) and configured_scopes:
        lines.append(
            "Configured user scopes: "
            + ", ".join(_redact_slash_text(scope) for scope in configured_scopes[:8])
        )

    vehicle_command_key = payload.get("vehicle_command_key")
    if isinstance(vehicle_command_key, dict):
        private_present = bool(vehicle_command_key.get("private_key_path"))
        public_present = bool(vehicle_command_key.get("public_key_path"))
        lines.append(
            "Vehicle-command key paths: "
            f"private={'configured' if private_present else 'missing'}, "
            f"public={'configured' if public_present else 'missing'}"
        )
    return "\n".join(lines)


def _format_onboarding(payload: dict[str, Any]) -> str:
    if not payload.get("ok"):
        return _format_command("tescmd-onboarding", payload)

    lines = ["Tesla onboarding status"]
    phase = payload.get("phase") or payload.get("next_action")
    if phase:
        lines.append(f"- phase: {_redact_slash_text(phase)}")
    next_tool = payload.get("next_tool")
    if next_tool:
        lines.append(f"- next tool: {_redact_slash_text(next_tool)}")
    docs_anchor = payload.get("docs_anchor")
    if docs_anchor:
        lines.append(f"- docs: {_redact_slash_text(docs_anchor)}")

    missing = payload.get("missing_prerequisites")
    if isinstance(missing, list) and missing:
        lines.append("Missing prerequisites:")
        lines.extend(f"- {_redact_slash_text(item)}" for item in missing[:6])

    next_steps = payload.get("next_steps")
    if isinstance(next_steps, list) and next_steps:
        lines.append("Next steps:")
        lines.extend(f"- {_redact_slash_text(step)}" for step in next_steps[:4])

    readiness = payload.get("readiness")
    if isinstance(readiness, dict):
        readiness_lines = []
        for key in (
            "app_configured",
            "authenticated",
            "ready_for_vehicle_reads",
            "ready_for_vehicle_commands",
            "ready_for_signed_commands",
            "key_hosting_ready",
        ):
            if key in readiness:
                readiness_lines.append(f"{key}={_stringify(readiness[key])}")
        if readiness_lines:
            lines.append("Readiness: " + ", ".join(readiness_lines))

    if payload.get("mutates_state") is False:
        lines.append(
            "Safety: read-only; no config, token, key, or vehicle state changes."
        )
    return "\n".join(lines)


def _format_vehicles(payload: dict[str, Any]) -> str:
    if not payload.get("ok"):
        return _format_command("tescmd-vehicles", payload)
    vehicles = payload.get("vehicles") or payload.get("response") or []
    if not isinstance(vehicles, list):
        return _compact_json(payload)
    lines = [f"Tesla vehicles: {len(vehicles)}"]
    for idx, vehicle in enumerate(vehicles, 1):
        if not isinstance(vehicle, dict):
            lines.append(f"{idx}. {_redact_slash_text(vehicle)}")
            continue
        name = (
            vehicle.get("display_name")
            or vehicle.get("vehicle_name")
            or vehicle.get("name")
            or "Unnamed"
        )
        state = vehicle.get("state") or vehicle.get("vehicle_state") or "unknown"
        identifiers = [
            str(vehicle.get(k)) for k in ("id_s", "vehicle_id", "vin") if vehicle.get(k)
        ]
        ident = _redact_vehicle_identifier(identifiers[0]) if identifiers else None
        ident = ident or "no id"
        parts = [
            _redact_slash_text(name),
            _redact_slash_text(state),
            ident,
        ]
        model_hint = _vehicle_model_hint(vehicle)
        if model_hint:
            parts.append(model_hint)
        lines.append(f"{idx}. " + " — ".join(parts))
    return "\n".join(lines)


def _vehicle_model_hint(vehicle: dict[str, Any]) -> str | None:
    """Return a non-sensitive model/capability hint for target selection.

    Tesla vehicle-list payloads often include a nested ``vehicle_config`` with
    ``car_type`` (for example ``cybertruck``) and sometimes trim information.
    Showing that hint in `/tescmd-vehicles` helps operators pick the intended
    car without exposing full VINs or Fleet identifiers.
    """
    config = vehicle.get("vehicle_config")
    if not isinstance(config, dict):
        config = {}

    car_type = vehicle.get("car_type") or config.get("car_type")
    trim = (
        vehicle.get("trim_badging")
        or vehicle.get("trim")
        or config.get("trim_badging")
        or config.get("trim")
    )

    hints = []
    if car_type:
        hints.append(f"type={_redact_slash_text(car_type)}")
    if trim and str(trim).strip().lower() != str(car_type).strip().lower():
        hints.append(f"trim={_redact_slash_text(trim)}")
    return ", ".join(hints) if hints else None


def _format_audit_log(payload: dict[str, Any]) -> str:
    if not payload.get("ok"):
        return _format_command("tescmd-audit-log", payload)
    events = payload.get("events") or []
    if not isinstance(events, list):
        return _format_command("tescmd-audit-log", payload)
    lines = [f"Tesla command audit log: {len(events)} event(s)"]
    if not events:
        lines.append("No wake or vehicle-control attempts are recorded yet.")
        return "\n".join(lines)

    for idx, event in enumerate(events, 1):
        if not isinstance(event, dict):
            lines.append(f"{idx}. {_redact_slash_text(event)}")
            continue
        tool = _redact_slash_text(event.get("tool") or "unknown tool")
        stage = _redact_slash_text(event.get("stage") or "unknown stage")
        ok = event.get("ok")
        if ok is True:
            outcome = "succeeded"
        elif ok is False:
            outcome = "failed"
        else:
            outcome = "attempted"

        parts = [f"{idx}. {tool} {stage} {outcome}"]
        command_name = event.get("command_name")
        if command_name:
            parts.append(f"command={_redact_slash_text(command_name)}")
        target = event.get("target")
        if isinstance(target, dict) and target.get("provided"):
            suffix = target.get("suffix")
            parts.append(
                f"target=…{_redact_slash_text(suffix)}" if suffix else "target=provided"
            )
        if event.get("confirm") is not None:
            parts.append(f"confirm={_stringify(event.get('confirm'))}")
        if event.get("wake"):
            parts.append("wake=yes")
        status_code = event.get("status_code")
        if status_code:
            parts.append(f"status={_redact_slash_text(status_code)}")
        error = event.get("error")
        if error:
            parts.append(f"error={_redact_slash_text(error)}")
        lines.append(" — ".join(parts))
    return "\n".join(lines)


def _add_slash_confirmation_hint(name: str, payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("ok"):
        return payload
    error = str(payload.get("error") or "")
    if "confirm=true is required" not in error:
        return payload
    hinted = dict(payload)
    hinted.setdefault(
        "how_to_run",
        f"Retry the slash command with confirm=true, for example: /{name} confirm=true",
    )
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


def _redact_vehicle_identifier(value: Any) -> str | None:
    """Return a human-usable, non-sensitive vehicle identifier hint.

    Slash command output is commonly copied into chats/logs. Keep enough of a
    VIN/Fleet id for an operator to distinguish vehicles without printing the
    full identifier.
    """
    if value is None:
        return None
    ident = str(value).strip()
    if not ident:
        return None
    if len(ident) <= 4:
        return "••••"
    return f"…{ident[-4:]}"


_VIN_PATTERN = re.compile(r"\b[A-HJ-NPR-Z0-9]{17}\b")
_LONG_NUMERIC_ID_PATTERN = re.compile(r"\b\d{10,}\b")
_BEARER_TOKEN_PATTERN = re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._~+/=-]{8,}")
_SENSITIVE_QUERY_VALUE_PATTERN = re.compile(
    r"(?i)([?&](?:code|state|token|access_token|refresh_token|id_token)=)[^\s&]+"
)


def _redact_slash_text(value: Any) -> str:
    """Redact sensitive identifiers before printing slash-command summaries."""
    text = str(value)
    text = _BEARER_TOKEN_PATTERN.sub(r"\1[REDACTED]", text)
    text = _SENSITIVE_QUERY_VALUE_PATTERN.sub(r"\1[REDACTED]", text)
    text = _VIN_PATTERN.sub(
        lambda match: _redact_vehicle_identifier(match.group(0)) or "••••", text
    )
    text = _LONG_NUMERIC_ID_PATTERN.sub(
        lambda match: _redact_vehicle_identifier(match.group(0)) or "••••", text
    )
    return text


def _first_dict(*values: Any) -> dict[str, Any]:
    for value in values:
        if isinstance(value, dict):
            return value
    return {}


def _vehicle_hint(payload: dict[str, Any]) -> str | None:
    vehicle = _first_dict(payload.get("vehicle"))
    name = (
        vehicle.get("display_name")
        or vehicle.get("vehicle_name")
        or vehicle.get("name")
    )
    vin = (
        payload.get("vin")
        or vehicle.get("vin")
        or vehicle.get("id_s")
        or vehicle.get("vehicle_id")
    )
    safe_identifier = _redact_vehicle_identifier(vin)
    if name and safe_identifier:
        return f"{_redact_slash_text(name)} ({safe_identifier})"
    if name:
        return _redact_slash_text(name)
    if safe_identifier:
        return safe_identifier
    return None


def _payload_section(payload: dict[str, Any], *keys: str) -> dict[str, Any]:
    for container in (
        payload,
        payload.get("data") if isinstance(payload.get("data"), dict) else None,
    ):
        if not isinstance(container, dict):
            continue
        for key in keys:
            value = container.get(key)
            if isinstance(value, dict):
                return value
    return {}


def _collection_from_payload(payload: dict[str, Any], *keys: str) -> list[Any]:
    for container in (
        payload,
        payload.get("data") if isinstance(payload.get("data"), dict) else None,
        payload.get("response") if isinstance(payload.get("response"), dict) else None,
        payload.get("sites") if isinstance(payload.get("sites"), dict) else None,
    ):
        if not isinstance(container, dict):
            continue
        for key in keys:
            value = container.get(key)
            if isinstance(value, list):
                return value
    return []


def _charger_distance(site: dict[str, Any]) -> str | None:
    for key, unit in (
        ("distance_miles", "mi"),
        ("distance_mi", "mi"),
        ("distance", "mi"),
        ("distance_km", "km"),
    ):
        value = site.get(key)
        if value is None:
            continue
        return f"{value} {unit}"
    return None


def _charger_label(site: Any, *, order: int | None = None) -> str:
    if not isinstance(site, dict):
        label = _redact_slash_text(site)
    else:
        name = (
            site.get("name")
            or site.get("site_name")
            or site.get("location")
            or "Unnamed"
        )
        bits = [_redact_slash_text(name)]
        available = site.get("available_stalls")
        if available is None:
            available = site.get("available")
        total = site.get("total_stalls")
        if total is None:
            total = site.get("stalls")
        if available is not None and total is not None:
            bits.append(f"{available}/{total} stalls")
        elif available is not None:
            bits.append(f"{available} stalls available")
        distance = _charger_distance(site)
        if distance:
            bits.append(distance)
        label = (
            bits[0] if len(bits) == 1 else f"{bits[0]} (" + ", ".join(bits[1:]) + ")"
        )
    if order is not None:
        return f"#{order} {label}"
    return label


def _summarize_nearby_chargers(payload: dict[str, Any]) -> list[str]:
    superchargers = _collection_from_payload(
        payload, "superchargers", "nearby_superchargers"
    )
    destination = _collection_from_payload(
        payload, "destination_charging", "destination_chargers"
    )
    total = len(superchargers) + len(destination)
    if total == 0:
        return ["Nearby chargers: no charging sites returned."]

    parts = []
    if superchargers:
        parts.append(f"{len(superchargers)} Supercharger(s)")
    if destination:
        parts.append(f"{len(destination)} destination charger(s)")
    lines = ["Nearby chargers: " + ", ".join(parts)]
    if superchargers:
        lines.append(
            "Top Superchargers: "
            + "; ".join(
                _charger_label(site, order=idx)
                for idx, site in enumerate(superchargers[:3], 1)
            )
        )
        lines.append(
            "Navigation: use tescmd_navigation_supercharger order=N confirm=true "
            "with the matching Supercharger number."
        )
    if destination:
        lines.append(
            "Top destination chargers: "
            + "; ".join(_charger_label(site) for site in destination[:3])
        )
    return lines


def _drive_detail_parts(drive: dict[str, Any]) -> list[str]:
    """Return safe, operator-useful drive/location details.

    Drive state often carries precise coordinates next to simple status fields.
    Keep the status fields visible for slash-command usefulness while leaving
    latitude/longitude redaction to the dedicated location marker below.
    """

    parts: list[str] = []
    shift = drive.get("shift_state")
    if shift:
        shift_labels = {
            "p": "parked",
            "r": "reverse",
            "n": "neutral",
            "d": "drive",
        }
        label = shift_labels.get(str(shift).strip().lower(), str(shift))
        parts.append(f"shift {_redact_slash_text(label)}")

    speed = drive.get("speed")
    if speed is not None:
        parts.append(f"speed {speed} mph")

    heading = drive.get("heading")
    if heading is not None:
        parts.append(f"heading {heading}°")

    power = drive.get("power")
    if power is not None:
        parts.append(f"power {power} kW")

    native_lat = drive.get("native_latitude")
    native_lon = drive.get("native_longitude")
    if native_lat is not None and native_lon is not None:
        parts.append("native location available (coordinates redacted)")

    return parts


def _charge_detail_parts(charge: dict[str, Any]) -> list[str]:
    parts: list[str] = []
    if charge.get("battery_level") is not None:
        parts.append(f"{charge.get('battery_level')}%")
    if charge.get("charging_state"):
        parts.append(str(charge.get("charging_state")))
    if charge.get("charge_limit_soc") is not None:
        parts.append(f"limit {charge.get('charge_limit_soc')}%")
    if charge.get("battery_range") is not None:
        parts.append(f"range {charge.get('battery_range')} mi")
    if charge.get("charger_power") is not None:
        parts.append(f"{charge.get('charger_power')} kW")
    if charge.get("charger_actual_current") is not None:
        parts.append(f"{charge.get('charger_actual_current')} A")
    if charge.get("time_to_full_charge") is not None:
        parts.append(f"{charge.get('time_to_full_charge')} h to full")
    cable = charge.get("conn_charge_cable")
    if cable and str(cable).lower() not in {"none", "unknown"}:
        parts.append(f"cable {_redact_slash_text(str(cable))}")
    if charge.get("charge_port_door_open") is not None:
        parts.append(
            "port open" if charge.get("charge_port_door_open") else "port closed"
        )
    return parts


def _charge_action_summary(name: str, payload: dict[str, Any]) -> str | None:
    raw_request = payload.get("request")
    request: dict[str, Any] = raw_request if isinstance(raw_request, dict) else {}
    if name == "tescmd-charge-start":
        return "start charging."
    if name == "tescmd-charge-stop":
        return "stop charging."
    if name == "tescmd-charge-port-open":
        return "open the charge port."
    if name == "tescmd-charge-port-close":
        return "close the charge port."
    if name == "tescmd-charge-limit":
        percent = request.get("percent")
        if percent is not None:
            return f"set charge limit to {percent}%."
        return "set charge limit."
    if name == "tescmd-charge-amps":
        amps = request.get("amps")
        if amps is not None:
            return f"set charging current to {amps} A."
        return "set charging current."
    return None


def _climate_detail_parts(climate: dict[str, Any]) -> list[str]:
    parts: list[str] = []
    if climate.get("is_climate_on") is not None:
        parts.append("on" if climate.get("is_climate_on") else "off")
    if climate.get("inside_temp") is not None:
        parts.append(f"inside {climate.get('inside_temp')}°")
    if climate.get("outside_temp") is not None:
        parts.append(f"outside {climate.get('outside_temp')}°")
    if climate.get("driver_temp_setting") is not None:
        parts.append(f"driver target {climate.get('driver_temp_setting')}°")
    if climate.get("passenger_temp_setting") is not None:
        parts.append(f"passenger target {climate.get('passenger_temp_setting')}°")
    if climate.get("fan_status") is not None:
        parts.append(f"fan {climate.get('fan_status')}")
    if climate.get("is_front_defroster_on"):
        parts.append("front defroster on")
    if climate.get("is_rear_defroster_on"):
        parts.append("rear defroster on")
    if climate.get("steering_wheel_heater"):
        parts.append("steering heat on")
    seat_heat = [
        label
        for key, label in (
            ("seat_heater_left", "driver"),
            ("seat_heater_right", "passenger"),
            ("seat_heater_rear_left", "rear-left"),
            ("seat_heater_rear_center", "rear-center"),
            ("seat_heater_rear_right", "rear-right"),
        )
        if climate.get(key)
    ]
    if seat_heat:
        parts.append("seat heat " + "/".join(seat_heat))
    return parts


def _climate_action_summary(name: str, payload: dict[str, Any]) -> str | None:
    raw_request = payload.get("request")
    request: dict[str, Any] = raw_request if isinstance(raw_request, dict) else {}
    if name == "tescmd-climate-start":
        return "start climate control."
    if name == "tescmd-climate-stop":
        return "stop climate control."
    if name == "tescmd-set-temp":
        driver = request.get("driver_temp")
        passenger = request.get("passenger_temp")
        if driver is not None and passenger is not None:
            return f"set cabin targets to driver {driver}° and passenger {passenger}°."
        if driver is not None:
            return f"set driver cabin target to {driver}°."
        if passenger is not None:
            return f"set passenger cabin target to {passenger}°."
        return "set cabin temperature targets."
    return None


def _media_action_summary(name: str, payload: dict[str, Any]) -> str | None:
    raw_request = payload.get("request")
    request: dict[str, Any] = raw_request if isinstance(raw_request, dict) else {}
    if name == "tescmd-media-play":
        return "toggle media playback."
    if name == "tescmd-media-next":
        return "skip to the next media track."
    if name == "tescmd-media-prev":
        return "go to the previous media track."
    if name == "tescmd-media-volume-up":
        return "increase media volume."
    if name == "tescmd-media-volume-down":
        return "decrease media volume."
    if name == "tescmd-media-volume-set":
        volume = request.get("volume")
        if volume is not None:
            return f"set media volume to {volume}."
        return "set media volume."
    return None


def _software_detail_parts(software: dict[str, Any]) -> list[str]:
    parts: list[str] = []
    version = software.get("car_version") or software.get("version")
    if version:
        parts.append(f"version {_redact_slash_text(version)}")

    update = software.get("software_update")
    update_parts: list[str] = []
    if isinstance(update, dict):
        status = update.get("status") or update.get("state")
        if status:
            update_parts.append(_redact_slash_text(status))
        version_available = update.get("version")
        if version_available:
            update_parts.append(f"to {_redact_slash_text(version_available)}")
        download = update.get("download_perc")
        if download is None:
            download = update.get("download_percent")
        if download is not None:
            update_parts.append(f"download {download}%")
        install = update.get("install_perc")
        if install is None:
            install = update.get("install_percent")
        if install is not None:
            update_parts.append(f"install {install}%")
        expected = update.get("expected_duration_sec")
        if expected is not None:
            update_parts.append(f"expected {expected}s")
    elif update:
        update_parts.append(_redact_slash_text(update))

    if update_parts:
        parts.append("update " + ", ".join(update_parts))
    return parts


def _alert_label(alert: Any) -> str:
    if not isinstance(alert, dict):
        return _redact_slash_text(alert)
    severity = (
        alert.get("severity")
        or alert.get("audience")
        or alert.get("level")
        or alert.get("alert_type")
        or alert.get("type")
    )
    message = (
        alert.get("message")
        or alert.get("description")
        or alert.get("name")
        or alert.get("title")
        or alert.get("event")
        or "unnamed alert"
    )
    if severity:
        return f"{_redact_slash_text(severity)}: {_redact_slash_text(message)}"
    return _redact_slash_text(message)


def _summarize_alerts(payload: dict[str, Any]) -> list[str]:
    alerts = _collection_from_payload(payload, "alerts", "recent_alerts")
    if not alerts:
        return ["Alerts: no recent vehicle alerts returned."]
    lines = [f"Alerts: {len(alerts)} recent alert(s)"]
    lines.append(
        "Top alerts: " + "; ".join(_alert_label(alert) for alert in alerts[:3])
    )
    return lines


def _state_flag(value: Any, *, true_text: str, false_text: str) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in _TRUE_VALUES or normalized in {"open", "opened", "on"}:
            return true_text
        if normalized in _FALSE_VALUES or normalized in {"closed", "off"}:
            return false_text
        return _redact_slash_text(value)
    return true_text if bool(value) else false_text


def _security_detail_parts(state: dict[str, Any]) -> list[str]:
    parts: list[str] = []
    locked = _state_flag(state.get("locked"), true_text="locked", false_text="unlocked")
    if locked:
        parts.append(locked)
    sentry = _state_flag(
        state.get("sentry_mode"), true_text="Sentry on", false_text="Sentry off"
    )
    if sentry:
        parts.append(sentry)
    valet = _state_flag(
        state.get("valet_mode"), true_text="valet on", false_text="valet off"
    )
    if valet == "valet on":
        parts.append(valet)
    return parts


def _closure_detail_parts(state: dict[str, Any]) -> list[str]:
    closure_fields = (
        ("df", "driver door"),
        ("pf", "passenger door"),
        ("dr", "rear-left door"),
        ("pr", "rear-right door"),
        ("fd_window", "driver window"),
        ("fp_window", "passenger window"),
        ("rd_window", "rear-left window"),
        ("rp_window", "rear-right window"),
        ("ft", "frunk"),
        ("rt", "trunk"),
        ("charge_port_door_open", "charge port"),
    )
    open_items: list[str] = []
    closed_count = 0
    for key, label in closure_fields:
        if key not in state:
            continue
        value = state.get(key)
        if value is None:
            continue
        if bool(value):
            open_items.append(label)
        else:
            closed_count += 1

    parts: list[str] = []
    if open_items:
        parts.append("open: " + ", ".join(open_items))
    if closed_count and not open_items:
        parts.append("all reported closures closed")
    elif closed_count:
        parts.append(f"{closed_count} reported closed")
    return parts


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
        charge_parts = _charge_detail_parts(charge)
        if charge_parts:
            lines.append("Charge: " + ", ".join(charge_parts))

    charge_action = _charge_action_summary(name, payload)
    if charge_action:
        lines.append(f"Charging action: {charge_action}")

    climate = _payload_section(payload, "climate_state")
    if climate:
        climate_parts = _climate_detail_parts(climate)
        if climate_parts:
            lines.append("Climate: " + ", ".join(climate_parts))

    climate_action = _climate_action_summary(name, payload)
    if climate_action:
        lines.append(f"Climate action: {climate_action}")

    media_action = _media_action_summary(name, payload)
    if media_action:
        lines.append(f"Media action: {media_action}")

    software = _payload_section(payload, "software", "vehicle_state")
    if name == "tescmd-software" and software:
        software_parts = _software_detail_parts(software)
        if software_parts:
            lines.append("Software: " + ", ".join(software_parts))

    security = _payload_section(payload, "security_state", "vehicle_state")
    if name in {"tescmd-security-status", "tescmd-closures"} and security:
        security_parts = _security_detail_parts(security)
        if security_parts:
            lines.append("Security: " + ", ".join(security_parts))

    closures = _payload_section(payload, "closures", "vehicle_state")
    if name == "tescmd-closures" and closures:
        closure_parts = _closure_detail_parts(closures)
        if closure_parts:
            lines.append("Closures: " + ", ".join(closure_parts))

    drive = _payload_section(payload, "drive_state", "location", "location_data")
    if name in {"tescmd-drive", "tescmd-location"} and drive:
        drive_parts = _drive_detail_parts(drive)
        if drive_parts:
            lines.append("Drive: " + ", ".join(drive_parts))

    location = _payload_section(payload, "location", "location_data", "drive_state")
    lat = location.get("latitude") or location.get("lat")
    lon = location.get("longitude") or location.get("lon") or location.get("lng")
    if lat is not None and lon is not None:
        lines.append("Location: available (coordinates redacted)")

    if name == "tescmd-nearby-chargers":
        lines.extend(_summarize_nearby_chargers(payload))

    if name == "tescmd-alerts":
        lines.extend(_summarize_alerts(payload))

    response = _first_dict(
        payload.get("response"), payload.get("result"), payload.get("payload")
    )
    result = (
        response.get("result")
        or response.get("reason")
        or response.get("message")
        or payload.get("message")
    )
    if result:
        if result is True and charge_action:
            lines.append("Result: Tesla accepted the charging command.")
        elif result is True and climate_action:
            lines.append("Result: Tesla accepted the climate command.")
        elif result is True and media_action:
            lines.append("Result: Tesla accepted the media command.")
        else:
            lines.append(f"Result: {_redact_slash_text(_stringify(result))}")
    elif not any(
        line.startswith(
            (
                "Charge:",
                "Climate:",
                "Security:",
                "Closures:",
                "Drive:",
                "Location:",
                "Nearby chargers:",
                "Software:",
                "Alerts:",
            )
        )
        for line in lines
    ):
        lines.append("Result: command accepted by Tesla Fleet API.")

    cache = payload.get("cache")
    if isinstance(cache, dict) and cache.get("hit") is True:
        lines.append("Source: cached vehicle data")
    return lines


def _summarize_failure(name: str, payload: dict[str, Any]) -> list[str]:
    label = _friendly_label(name)
    error = _redact_slash_text(payload.get("error") or "Unknown error")
    lines = [f"/{name}: failed — {label} did not run.", f"Reason: {error}"]
    retry = payload.get("retry_command")
    if retry:
        lines.append(f"Try: {_redact_slash_text(retry)}")
    why = payload.get("why_confirm_is_required")
    if why:
        lines.append(_redact_slash_text(why))
    next_action = payload.get("next_action")
    if next_action:
        lines.append(f"Next action: {_redact_slash_text(next_action)}")
    status_code = payload.get("status_code")
    if status_code:
        lines.append(f"Tesla API status: {_redact_slash_text(status_code)}")
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
        lambda ctx: _format_auth_status(
            _run_tool("tescmd_auth_status", ctx["raw_args"])
        ),
    ),
    "tescmd-onboarding": (
        "Show guided read-only setup phase and next steps.",
        "[profile=default]",
        lambda ctx: _format_onboarding(
            _run_tool("tescmd_onboarding_status", ctx["raw_args"])
        ),
    ),
    "tescmd-key-show": (
        "Show vehicle-command key status and enrollment URLs.",
        "[profile=default]",
        lambda ctx: _format_command(
            "tescmd-key-show", _run_tool("tescmd_key_show", ctx["raw_args"])
        ),
    ),
    "tescmd-key-validate": (
        "Validate configured public vehicle-command key hosting.",
        "[profile=default]",
        lambda ctx: _format_command(
            "tescmd-key-validate", _run_tool("tescmd_key_validate", ctx["raw_args"])
        ),
    ),
    "tescmd-cache-status": (
        "Show plugin-native response cache status.",
        "[profile=default]",
        lambda ctx: _format_command(
            "tescmd-cache-status", _run_tool("tescmd_cache_status", ctx["raw_args"])
        ),
    ),
    "tescmd-cache-clear": (
        "Clear plugin-native response cache; requires confirm=true.",
        "[profile=default] confirm=true",
        lambda ctx: _format_command(
            "tescmd-cache-clear", _run_tool("tescmd_cache_clear", ctx["raw_args"])
        ),
    ),
    "tescmd-audit-log": (
        "Show recent redacted side-effect command and wake audit events.",
        "[limit=20]",
        lambda ctx: _format_audit_log(_run_tool("tescmd_audit_log", ctx["raw_args"])),
    ),
    "tescmd-vehicles": (
        "List Tesla vehicles on the account.",
        "[profile=default] [region=na|eu|cn]",
        lambda ctx: _format_vehicles(_run_tool("tescmd_vehicle_list", ctx["raw_args"])),
    ),
    "tescmd-vehicle-status": (
        "Fetch selected vehicle status. Optional endpoints=a,b limits payload.",
        "[vin] [endpoints=charge_state,drive_state] [wake=true confirm=true]",
        lambda ctx: _format_command(
            "tescmd-vehicle-status", _run_tool("tescmd_vehicle_status", ctx["raw_args"])
        ),
    ),
    "tescmd-charge": (
        "Fetch charge-state data for the selected vehicle.",
        "[vin] [wake=true confirm=true]",
        lambda ctx: _format_command(
            "tescmd-charge", _run_tool("tescmd_charge_status", ctx["raw_args"])
        ),
    ),
    "tescmd-drive": (
        "Fetch drive/route/GPS state for the selected vehicle.",
        "[vin] [wake=true confirm=true]",
        lambda ctx: _format_command(
            "tescmd-drive", _run_tool("tescmd_vehicle_drive_status", ctx["raw_args"])
        ),
    ),
    "tescmd-closures": (
        "Fetch door/window/trunk/charge-port closure state.",
        "[vin] [wake=true confirm=true]",
        lambda ctx: _format_command(
            "tescmd-closures",
            _run_tool("tescmd_vehicle_closures_status", ctx["raw_args"]),
        ),
    ),
    "tescmd-config": (
        "Fetch model/trim/capability metadata.",
        "[vin] [wake=true confirm=true]",
        lambda ctx: _format_command(
            "tescmd-config", _run_tool("tescmd_vehicle_config_status", ctx["raw_args"])
        ),
    ),
    "tescmd-gui": (
        "Fetch GUI/unit preferences.",
        "[vin] [wake=true confirm=true]",
        lambda ctx: _format_command(
            "tescmd-gui", _run_tool("tescmd_vehicle_gui_settings", ctx["raw_args"])
        ),
    ),
    "tescmd-security-status": (
        "Fetch lock/security state.",
        "[vin] [wake=true confirm=true]",
        lambda ctx: _format_command(
            "tescmd-security-status",
            _run_tool("tescmd_security_status", ctx["raw_args"]),
        ),
    ),
    "tescmd-software": (
        "Fetch software/update status.",
        "[vin] [wake=true confirm=true]",
        lambda ctx: _format_command(
            "tescmd-software", _run_tool("tescmd_software_status", ctx["raw_args"])
        ),
    ),
    "tescmd-nearby-chargers": (
        "Fetch nearby charging sites.",
        "[vin]",
        lambda ctx: _format_command(
            "tescmd-nearby-chargers",
            _run_tool("tescmd_vehicle_nearby_chargers", ctx["raw_args"]),
        ),
    ),
    "tescmd-alerts": (
        "Fetch recent vehicle alerts.",
        "[vin]",
        lambda ctx: _format_command(
            "tescmd-alerts", _run_tool("tescmd_vehicle_alerts", ctx["raw_args"])
        ),
    ),
    "tescmd-release-notes": (
        "Fetch firmware release notes.",
        "[vin]",
        lambda ctx: _format_command(
            "tescmd-release-notes",
            _run_tool("tescmd_vehicle_release_notes", ctx["raw_args"]),
        ),
    ),
    "tescmd-climate": (
        "Fetch climate-state data for the selected vehicle.",
        "[vin] [wake=true confirm=true]",
        lambda ctx: _format_command(
            "tescmd-climate", _run_tool("tescmd_climate_status", ctx["raw_args"])
        ),
    ),
    "tescmd-location": (
        "Fetch vehicle location data.",
        "[vin] [wake=true confirm=true]",
        lambda ctx: _format_command(
            "tescmd-location", _run_tool("tescmd_vehicle_location", ctx["raw_args"])
        ),
    ),
    "tescmd-wake": (
        "Wake the selected vehicle; requires confirm=true.",
        "[vin] confirm=true",
        lambda ctx: _format_command(
            "tescmd-wake", _run_tool("tescmd_vehicle_wake", ctx["raw_args"])
        ),
    ),
    "tescmd-flash": (
        "Flash the selected vehicle lights; requires confirm=true.",
        "[vin] confirm=true",
        lambda ctx: _format_command(
            "tescmd-flash", _run_tool("tescmd_security_flash_lights", ctx["raw_args"])
        ),
    ),
    "tescmd-honk": (
        "Honk the selected vehicle horn; requires confirm=true.",
        "[vin] confirm=true",
        lambda ctx: _format_command(
            "tescmd-honk", _run_tool("tescmd_security_honk_horn", ctx["raw_args"])
        ),
    ),
    "tescmd-lock": (
        "Lock the selected vehicle; requires confirm=true.",
        "[vin] confirm=true",
        lambda ctx: _format_command(
            "tescmd-lock", _run_tool("tescmd_security_lock", ctx["raw_args"])
        ),
    ),
    "tescmd-unlock": (
        "Unlock the selected vehicle; requires confirm=true.",
        "[vin] confirm=true",
        lambda ctx: _format_command(
            "tescmd-unlock", _run_tool("tescmd_security_unlock", ctx["raw_args"])
        ),
    ),
    "tescmd-sentry": (
        "Enable or disable Sentry Mode; requires confirm=true.",
        "[vin] enabled=true|false confirm=true",
        lambda ctx: _format_command(
            "tescmd-sentry", _run_tool("tescmd_security_sentry_mode", ctx["raw_args"])
        ),
    ),
    "tescmd-climate-start": (
        "Start climate control; requires confirm=true.",
        "[vin] confirm=true",
        lambda ctx: _format_command(
            "tescmd-climate-start", _run_tool("tescmd_climate_start", ctx["raw_args"])
        ),
    ),
    "tescmd-climate-stop": (
        "Stop climate control; requires confirm=true.",
        "[vin] confirm=true",
        lambda ctx: _format_command(
            "tescmd-climate-stop", _run_tool("tescmd_climate_stop", ctx["raw_args"])
        ),
    ),
    "tescmd-set-temp": (
        "Set driver/passenger cabin temperatures; requires confirm=true.",
        "[vin] driver_temp=70 passenger_temp=70 confirm=true",
        lambda ctx: _format_command(
            "tescmd-set-temp",
            _run_tool(
                "tescmd_climate_set_temps",
                ctx["raw_args"],
                expose_args=("driver_temp", "passenger_temp"),
            ),
        ),
    ),
    "tescmd-charge-start": (
        "Start charging; requires confirm=true.",
        "[vin] confirm=true",
        lambda ctx: _format_command(
            "tescmd-charge-start", _run_tool("tescmd_charge_start", ctx["raw_args"])
        ),
    ),
    "tescmd-charge-stop": (
        "Stop charging; requires confirm=true.",
        "[vin] confirm=true",
        lambda ctx: _format_command(
            "tescmd-charge-stop", _run_tool("tescmd_charge_stop", ctx["raw_args"])
        ),
    ),
    "tescmd-charge-limit": (
        "Set charge limit percentage; requires confirm=true.",
        "[vin] percent=80 confirm=true",
        lambda ctx: _format_command(
            "tescmd-charge-limit",
            _run_tool("tescmd_charge_limit", ctx["raw_args"], expose_args=("percent",)),
        ),
    ),
    "tescmd-charge-amps": (
        "Set charge amperage; requires confirm=true.",
        "[vin] amps=32 confirm=true",
        lambda ctx: _format_command(
            "tescmd-charge-amps",
            _run_tool("tescmd_charge_set_amps", ctx["raw_args"], expose_args=("amps",)),
        ),
    ),
    "tescmd-charge-port-open": (
        "Open charge port; requires confirm=true.",
        "[vin] confirm=true",
        lambda ctx: _format_command(
            "tescmd-charge-port-open",
            _run_tool("tescmd_charge_port_open", ctx["raw_args"]),
        ),
    ),
    "tescmd-charge-port-close": (
        "Close charge port; requires confirm=true.",
        "[vin] confirm=true",
        lambda ctx: _format_command(
            "tescmd-charge-port-close",
            _run_tool("tescmd_charge_port_close", ctx["raw_args"]),
        ),
    ),
    "tescmd-frunk": (
        "Actuate the front trunk; requires confirm=true.",
        "[vin] confirm=true",
        lambda ctx: _format_command(
            "tescmd-frunk",
            _run_tool(
                "tescmd_vehicle_actuate_trunk",
                ctx["raw_args"],
                {"which_trunk": "front"},
            ),
        ),
    ),
    "tescmd-trunk-open": (
        "Open rear trunk; requires confirm=true.",
        "[vin] confirm=true",
        lambda ctx: _format_command(
            "tescmd-trunk-open", _run_tool("tescmd_vehicle_trunk_open", ctx["raw_args"])
        ),
    ),
    "tescmd-trunk-close": (
        "Close rear trunk; requires confirm=true.",
        "[vin] confirm=true",
        lambda ctx: _format_command(
            "tescmd-trunk-close",
            _run_tool("tescmd_vehicle_trunk_close", ctx["raw_args"]),
        ),
    ),
    "tescmd-window-vent": (
        "Vent windows; requires confirm=true.",
        "[vin] confirm=true [lat=.. lon=..]",
        lambda ctx: _format_command(
            "tescmd-window-vent",
            _run_tool(
                "tescmd_vehicle_window_control", ctx["raw_args"], {"command": "vent"}
            ),
        ),
    ),
    "tescmd-window-close": (
        "Close windows; requires confirm=true.",
        "[vin] confirm=true [lat=.. lon=..]",
        lambda ctx: _format_command(
            "tescmd-window-close",
            _run_tool(
                "tescmd_vehicle_window_control", ctx["raw_args"], {"command": "close"}
            ),
        ),
    ),
    "tescmd-media-play": (
        "Toggle media playback; requires confirm=true.",
        "[vin] confirm=true",
        lambda ctx: _format_command(
            "tescmd-media-play",
            _run_tool("tescmd_media_toggle_playback", ctx["raw_args"]),
        ),
    ),
    "tescmd-media-next": (
        "Skip to next track; requires confirm=true.",
        "[vin] confirm=true",
        lambda ctx: _format_command(
            "tescmd-media-next", _run_tool("tescmd_media_next_track", ctx["raw_args"])
        ),
    ),
    "tescmd-media-prev": (
        "Go to previous track; requires confirm=true.",
        "[vin] confirm=true",
        lambda ctx: _format_command(
            "tescmd-media-prev", _run_tool("tescmd_media_prev_track", ctx["raw_args"])
        ),
    ),
    "tescmd-media-volume-up": (
        "Increase media volume; requires confirm=true.",
        "[vin] confirm=true",
        lambda ctx: _format_command(
            "tescmd-media-volume-up",
            _run_tool("tescmd_media_volume_up", ctx["raw_args"]),
        ),
    ),
    "tescmd-media-volume-down": (
        "Decrease media volume; requires confirm=true.",
        "[vin] confirm=true",
        lambda ctx: _format_command(
            "tescmd-media-volume-down",
            _run_tool("tescmd_media_volume_down", ctx["raw_args"]),
        ),
    ),
    "tescmd-media-volume-set": (
        "Set media volume; requires confirm=true.",
        "[vin] volume=3 confirm=true",
        lambda ctx: _format_command(
            "tescmd-media-volume-set",
            _run_tool(
                "tescmd_media_volume_set", ctx["raw_args"], expose_args=("volume",)
            ),
        ),
    ),
    "tescmd-nav": (
        "Send navigation destination string; requires confirm=true.",
        "[vin] destination='address or place' confirm=true",
        lambda ctx: _format_command(
            "tescmd-nav",
            _run_tool(
                "tescmd_navigation_send",
                ctx["raw_args"],
                positional_name="destination",
            ),
        ),
    ),
    "tescmd-nav-search": (
        "Search Google Places for navigation Place IDs.",
        "query='address or place' [limit=5]",
        lambda ctx: _format_command(
            "tescmd-nav-search",
            _run_tool(
                "tescmd_navigation_place_search",
                ctx["raw_args"],
                positional_name="query",
            ),
        ),
    ),
    "tescmd-nav-waypoints": (
        "Send Google Place ID waypoints; requires confirm=true.",
        "[vin] place_ids=id1,id2 confirm=true",
        lambda ctx: _format_command(
            "tescmd-nav-waypoints",
            _run_tool("tescmd_navigation_waypoints", ctx["raw_args"]),
        ),
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
            handler=lambda raw_args, _handler=entry["handler"]: _handler(
                {"raw_args": raw_args}
            ),
            description=entry["description"],
            args_hint=entry["args_hint"],
        )
