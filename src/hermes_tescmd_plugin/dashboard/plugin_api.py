from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from hermes_tescmd_plugin import config, runtime, schemas
from hermes_tescmd_plugin.dashboard import ensure_dashboard_installed
from hermes_tescmd_plugin.slash import _redact_slash_text, _redact_vehicle_identifier

router = APIRouter()

_QUICK_ACTION_TO_TOOL = {
    "wake": "tescmd_vehicle_wake",
    "flash": "tescmd_flash",
    "honk": "tescmd_honk",
    "lock": "tescmd_lock",
    "unlock": "tescmd_unlock",
    "sentry": "tescmd_sentry",
    "charge-start": "tescmd_charge_start",
    "charge-stop": "tescmd_charge_stop",
    "charge-limit": "tescmd_charge_limit",
    "charge-amps": "tescmd_charge_set_amps",
    "charge-port-open": "tescmd_charge_port_open",
    "charge-port-close": "tescmd_charge_port_close",
    "climate-start": "tescmd_climate_start",
    "climate-stop": "tescmd_climate_stop",
    "set-temp": "tescmd_climate_set_temps",
    "frunk": "tescmd_vehicle_actuate_trunk",
    "trunk-open": "tescmd_vehicle_trunk_open",
    "trunk-close": "tescmd_vehicle_trunk_close",
    "window-vent": "tescmd_vehicle_window_control",
    "window-close": "tescmd_vehicle_window_control",
    "media-play": "tescmd_media_toggle_playback",
    "media-next": "tescmd_media_next_track",
    "media-prev": "tescmd_media_prev_track",
    "media-volume-up": "tescmd_media_volume_up",
    "media-volume-down": "tescmd_media_volume_down",
    "media-volume-set": "tescmd_media_volume_set",
    "nav": "tescmd_navigation_send",
    "nav-gps": "tescmd_navigation_gps",
    "nav-waypoints": "tescmd_navigation_waypoints",
}

_ACTION_DEFAULTS: dict[str, dict[str, Any]] = {
    "frunk": {"which_trunk": "front"},
    "window-vent": {"command": "vent"},
    "window-close": {"command": "close"},
}

_ACTION_EXTRA_FIELDS: dict[str, tuple[str, ...]] = {
    "sentry": ("enabled",),
    "charge-limit": ("percent",),
    "charge-amps": ("amps",),
    "set-temp": ("driver_temp", "passenger_temp"),
    "media-volume-set": ("volume",),
    "nav": ("destination", "order"),
    "nav-gps": ("lat", "lon", "order"),
    "nav-waypoints": ("place_ids",),
}

_READ_TOOLS = {
    "status": "tescmd_status",
    "auth-status": "tescmd_auth_status",
    "onboarding": "tescmd_onboarding_status",
    "key-show": "tescmd_key_show",
    "key-validate": "tescmd_key_validate",
    "cache-status": "tescmd_cache_status",
    "vehicles": "tescmd_vehicle_list",
    "vehicle-status": "tescmd_vehicle_status",
    "vehicle": "tescmd_vehicle_get",
    "charge": "tescmd_charge_status",
    "climate": "tescmd_climate_status",
    "location": "tescmd_vehicle_location",
    "drive": "tescmd_vehicle_drive_status",
    "closures": "tescmd_vehicle_closures_status",
    "config": "tescmd_vehicle_config_status",
    "gui": "tescmd_vehicle_gui_settings",
    "security": "tescmd_security_status",
    "software": "tescmd_software_status",
    "nearby-chargers": "tescmd_vehicle_nearby_chargers",
    "alerts": "tescmd_vehicle_alerts",
    "drivers": "tescmd_vehicle_drivers",
    "release-notes": "tescmd_vehicle_release_notes",
    "service": "tescmd_vehicle_service",
    "mobile-access": "tescmd_vehicle_mobile_access",
    "charge-schedule": "tescmd_vehicle_charge_schedule_status",
    "preconditioning-schedule": "tescmd_vehicle_preconditioning_schedule_status",
}


def _specs() -> dict[str, runtime.ToolSpec]:
    return {spec.name: spec for spec in runtime.list_tool_specs()}


def _command_category(spec: runtime.ToolSpec) -> str:
    if spec.name.startswith("tescmd_"):
        remainder = spec.name.removeprefix("tescmd_")
        return remainder.split("_", 1)[0] or spec.operation
    return spec.operation.split("_", 1)[0] or "other"


def _command_kind(spec: runtime.ToolSpec) -> str:
    if any(param.name == "confirm" and param.required for param in spec.params):
        return "action"
    if spec.operation.endswith("status") or spec.operation in {
        "status",
        "auth_status",
        "vehicle_list",
        "vehicle_get",
        "vehicle_status",
    }:
        return "read"
    return (
        "admin"
        if _command_category(spec) in {"auth", "key", "cache", "onboarding", "partner"}
        else "read"
    )


_IDENTIFIER_PARAM_NAMES = {"vin", "id_s", "vehicle_id", "vins"}
_LOCATION_PARAM_NAMES = {
    "destination",
    "lat",
    "latitude",
    "lon",
    "lng",
    "longitude",
    "native_latitude",
    "native_longitude",
    "order",
    "place_id",
    "place_ids",
    "query",
}
_SECRET_PARAM_PARTS = (
    "token",
    "secret",
    "authorization",
    "bearer",
    "pin",
    "password",
    "code",
    "state",
)


def _parameter_safety_flags(spec: runtime.ToolSpec) -> dict[str, list[str]]:
    flags: dict[str, list[str]] = {}
    schema = schemas.build_schema(spec)
    properties = schema.get("parameters", {}).get("properties", {})
    for name, param_schema in properties.items():
        lowered = name.lower()
        param_flags: list[str] = []
        if lowered in _IDENTIFIER_PARAM_NAMES:
            param_flags.append("vehicle_identifier")
        if lowered in _LOCATION_PARAM_NAMES:
            param_flags.append("location_or_destination")
        if any(part in lowered for part in _SECRET_PARAM_PARTS):
            param_flags.append("secret_or_oauth_value")
        if isinstance(param_schema, dict) and param_schema.get("x-sensitive"):
            param_flags.append("schema_sensitive")
        if param_flags:
            flags[name] = param_flags
    return flags


def _command_safety_notes(
    spec: runtime.ToolSpec, param_flags: dict[str, list[str]]
) -> list[str]:
    notes: list[str] = []
    if any(param.name == "confirm" and param.required for param in spec.params):
        notes.append("Requires confirm=true before physical or account side effects.")
    elif any(param.name == "confirm" for param in spec.params):
        notes.append("May accept confirm=true for intentional wake/read behavior.")
    if any(param.name == "wake" for param in spec.params):
        notes.append("Wake is available but is a vehicle side effect when enabled.")
    flattened_flags = {flag for flags in param_flags.values() for flag in flags}
    if "vehicle_identifier" in flattened_flags:
        notes.append("Vehicle identifiers should stay redacted in visible output.")
    if "location_or_destination" in flattened_flags:
        notes.append("Locations, destinations, and coordinates are privacy-sensitive.")
    if (
        "secret_or_oauth_value" in flattened_flags
        or "schema_sensitive" in flattened_flags
    ):
        notes.append(
            "OAuth/secrets/PIN-like values must not be displayed or logged raw."
        )
    return notes


def _serialize_command(spec: runtime.ToolSpec) -> dict[str, Any]:
    schema = schemas.build_schema(spec)
    parameters = schema["parameters"]
    param_flags = _parameter_safety_flags(spec)
    safety_notes = _command_safety_notes(spec, param_flags)
    return {
        "name": spec.name,
        "description": spec.description,
        "operation": spec.operation,
        "category": _command_category(spec),
        "kind": _command_kind(spec),
        "command_name": spec.command_name,
        "payload_mode": spec.payload_mode,
        "required": parameters.get("required", []),
        "parameters": parameters.get("properties", {}),
        "confirm_required": any(
            param.name == "confirm" and param.required for param in spec.params
        ),
        "wake_capable": any(param.name == "wake" for param in spec.params),
        "sensitive_parameters": param_flags,
        "safety_notes": safety_notes,
    }


def _run(tool_name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    spec = _specs().get(tool_name)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"Unknown tescmd tool: {tool_name}")
    payload = runtime.make_handler(spec)(args or {})
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=502, detail="tescmd tool returned non-JSON output"
        ) from exc
    if not isinstance(data, dict):
        raise HTTPException(
            status_code=502, detail="tescmd tool returned an unexpected payload"
        )
    return data


class DefaultVehicleBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile: str = "default"
    vin: str | None = Field(
        None,
        description="VIN or Fleet vehicle id_s to save as the profile default. Empty clears the dashboard default.",
    )


class QuickActionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str = Field(
        ..., description="Quick action key, e.g. flash, honk, wake, climate-start."
    )
    vin: str | None = None
    profile: str = "default"
    region: str | None = None
    confirm: bool = False
    enabled: bool | None = None
    percent: int | None = None
    amps: int | None = None
    driver_temp: float | None = None
    passenger_temp: float | None = None
    volume: float | None = None
    destination: str | None = None
    order: int | None = None
    lat: float | None = None
    lon: float | None = None
    place_ids: list[str] | None = None


def _base_vehicle_args(
    profile: str, vin: str | None = None, region: str | None = None
) -> dict[str, Any]:
    args: dict[str, Any] = {"profile": profile}
    if vin:
        args["vin"] = vin
    if region:
        args["region"] = region
    return args


_IDENTIFIER_KEYS = {"vin", "id_s", "vehicle_id"}
_LOCATION_KEYS = {
    "destination",
    "lat",
    "latitude",
    "lon",
    "lng",
    "longitude",
    "native_latitude",
    "native_longitude",
    "place_id",
    "place_ids",
}
_SECRET_KEY_PARTS = ("token", "secret", "authorization", "bearer", "pin", "password")


def _dashboard_display_payload(value: Any) -> Any:
    """Return a JSON-safe dashboard payload suitable for the visible debug panel.

    The dashboard needs raw values internally for maps and targeted actions, but
    the human-facing "Last payload" panel is easy to screenshot or copy. Keep the
    structural debugging breadcrumbs while redacting full vehicle identifiers,
    tokens/secrets/PINs, navigation destinations, and precise coordinates.
    """
    if isinstance(value, dict):
        safe: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            lowered = key_text.lower()
            if lowered in _IDENTIFIER_KEYS:
                safe[key_text] = _redact_vehicle_identifier(item) or "[REDACTED]"
            elif lowered in _LOCATION_KEYS:
                safe[key_text] = "[REDACTED_LOCATION]"
            elif any(part in lowered for part in _SECRET_KEY_PARTS):
                safe[key_text] = "[REDACTED]"
            else:
                safe[key_text] = _dashboard_display_payload(item)
        return safe
    if isinstance(value, list):
        return [_dashboard_display_payload(item) for item in value]
    if isinstance(value, str):
        return _redact_slash_text(value)
    return value


def _with_display_payload(payload: dict[str, Any]) -> dict[str, Any]:
    payload = dict(payload)
    payload["display_payload"] = _dashboard_display_payload(payload)
    return payload


@router.get("/install")
def install_assets() -> dict[str, Any]:
    return ensure_dashboard_installed()


@router.get("/tools")
def tools() -> dict[str, Any]:
    return {
        "ok": True,
        "reads": _READ_TOOLS,
        "quick_actions": _QUICK_ACTION_TO_TOOL,
        "action_defaults": _ACTION_DEFAULTS,
        "action_extra_fields": _ACTION_EXTRA_FIELDS,
        "safety": "Quick actions are physical side effects and require confirm=true.",
    }


@router.get("/commands")
def commands() -> dict[str, Any]:
    """Return the live Hermes tool catalog generated from the plugin runtime specs."""

    command_list = [_serialize_command(spec) for spec in runtime.list_tool_specs()]
    categories: dict[str, int] = {}
    kinds: dict[str, int] = {}
    for command in command_list:
        categories[command["category"]] = categories.get(command["category"], 0) + 1
        kinds[command["kind"]] = kinds.get(command["kind"], 0) + 1
    return {
        "ok": True,
        "source": "runtime.list_tool_specs",
        "count": len(command_list),
        "categories": categories,
        "kinds": kinds,
        "commands": command_list,
    }


@router.get("/status")
def status(profile: str = "default") -> dict[str, Any]:
    return _with_display_payload(_run("tescmd_status", {"profile": profile}))


@router.get("/vehicles")
def vehicles(profile: str = "default", region: str | None = None) -> dict[str, Any]:
    args: dict[str, Any] = {"profile": profile}
    if region:
        args["region"] = region
    return _with_display_payload(_run("tescmd_vehicle_list", args))


@router.post("/default-vehicle")
def set_default_vehicle(body: DefaultVehicleBody) -> dict[str, Any]:
    """Persist the dashboard-selected VIN/Fleet id_s as the profile default target."""

    profile = config.validate_profile(body.profile)
    vehicle_id = body.vin.strip() if isinstance(body.vin, str) else None
    cfg = config.load_config(profile)
    cfg.default_vin = vehicle_id or None
    saved = config.save_config(cfg)
    payload = {
        "ok": True,
        "profile": saved.profile,
        "default_vehicle": _redact_vehicle_identifier(saved.default_vin)
        if saved.default_vin
        else None,
        "message": (
            "Default Tesla vehicle updated."
            if saved.default_vin
            else "Default Tesla vehicle cleared."
        ),
    }
    return _with_display_payload(payload)


def _safe_run(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    try:
        payload = _run(tool_name, args)
    except Exception as exc:  # Keep the visual dashboard resilient when one read fails.
        return {"ok": False, "error": str(exc), "tool": tool_name}
    if not isinstance(payload, dict):
        return {
            "ok": False,
            "error": "Unexpected non-object payload",
            "tool": tool_name,
        }
    return payload


@router.get("/overview")
def overview(
    vin: str | None = None,
    profile: str = "default",
    region: str | None = None,
    no_cache: bool = False,
    units: str | None = None,
) -> dict[str, Any]:
    """Visual dashboard snapshot assembled from safe read-only native tools."""
    base_args = _base_vehicle_args(profile, vin, region)
    read_args = dict(base_args)
    read_args.update({"wake": False, "confirm": False, "no_cache": no_cache})
    if units:
        read_args["units"] = units
    sections = {
        "charge": _safe_run("tescmd_charge_status", read_args),
        "location": _safe_run("tescmd_vehicle_location", read_args),
        "drive": _safe_run("tescmd_vehicle_drive_status", read_args),
        "climate": _safe_run("tescmd_climate_status", read_args),
        "closures": _safe_run("tescmd_vehicle_closures_status", read_args),
        "security": _safe_run("tescmd_security_status", read_args),
    }
    payload = {
        "ok": True,
        "profile": profile,
        "vin": vin,
        "region": region,
        "status": _safe_run("tescmd_status", {"profile": profile}),
        "onboarding": _safe_run("tescmd_onboarding_status", {"profile": profile}),
        "vehicles": _safe_run(
            "tescmd_vehicle_list",
            {k: v for k, v in {"profile": profile, "region": region}.items() if v},
        ),
        "sections": sections,
    }
    return _with_display_payload(payload)


@router.get("/vehicle")
def vehicle(
    vin: str | None = None,
    profile: str = "default",
    region: str | None = None,
    endpoints: str | None = Query(
        None, description="Comma-separated vehicle_data endpoints."
    ),
    wake: bool = False,
    confirm: bool = False,
) -> dict[str, Any]:
    args: dict[str, Any] = {"profile": profile, "wake": wake, "confirm": confirm}
    if vin:
        args["vin"] = vin
    if region:
        args["region"] = region
    if endpoints:
        args["endpoints"] = [
            part.strip() for part in endpoints.split(",") if part.strip()
        ]
    return _with_display_payload(_run("tescmd_vehicle_status", args))


@router.get("/read/{read_key}")
def read(
    read_key: str,
    vin: str | None = None,
    profile: str = "default",
    region: str | None = None,
    wake: bool = False,
    confirm: bool = False,
    no_cache: bool = False,
    units: str | None = None,
) -> dict[str, Any]:
    tool_name = _READ_TOOLS.get(read_key)
    if not tool_name:
        raise HTTPException(status_code=404, detail=f"Unknown read key: {read_key}")
    args = _base_vehicle_args(profile, vin, region)
    if tool_name in {
        "tescmd_vehicle_status",
        "tescmd_charge_status",
        "tescmd_climate_status",
        "tescmd_vehicle_location",
        "tescmd_vehicle_drive_status",
        "tescmd_vehicle_closures_status",
        "tescmd_vehicle_config_status",
        "tescmd_vehicle_gui_settings",
        "tescmd_security_status",
        "tescmd_software_status",
        "tescmd_vehicle_charge_schedule_status",
        "tescmd_vehicle_preconditioning_schedule_status",
    }:
        args.update({"wake": wake, "confirm": confirm, "no_cache": no_cache})
        if units:
            args["units"] = units
    return _with_display_payload(_run(tool_name, args))


@router.post("/quick-action")
def quick_action(body: QuickActionBody) -> dict[str, Any]:
    tool_name = _QUICK_ACTION_TO_TOOL.get(body.action)
    if not tool_name:
        raise HTTPException(
            status_code=404, detail=f"Unknown quick action: {body.action}"
        )
    args = _base_vehicle_args(body.profile, body.vin, body.region)
    args["confirm"] = bool(body.confirm)
    args.update(_ACTION_DEFAULTS.get(body.action, {}))
    for field in _ACTION_EXTRA_FIELDS.get(body.action, ()):
        value = getattr(body, field)
        if value is not None:
            args[field] = value
    return _with_display_payload(_run(tool_name, args))
