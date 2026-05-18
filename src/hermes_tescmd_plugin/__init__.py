from __future__ import annotations

import os
from pathlib import Path

from . import auth, client, config, runtime, schemas, tools

__version__ = "0.5.0a10"
PLUGIN_NAME = "hermes-tescmd-plugin"
TOOLSET_NAME = "tescmd"
SKILL_NAME = "tescmd-operator"
TOOL_SURFACE_ENV = "TESCMD_TOOL_SURFACE"

# Keep the default Hermes surface compact so the agent does not pay prompt/tool
# selection latency for every rarely-used Fleet endpoint on unrelated turns.
# Complete API coverage remains available via raw Fleet request tools by default,
# and the exhaustive dedicated tool surface is available with
# TESCMD_TOOL_SURFACE=full.
_COMPACT_TOOL_NAMES = frozenset(
    {
        "tescmd_auth_login",
        "tescmd_auth_complete",
        "tescmd_auth_status",
        "tescmd_auth_refresh",
        "tescmd_auth_register",
        "tescmd_auth_logout",
        "tescmd_status",
        "tescmd_help",
        "tescmd_vehicle_list",
        "tescmd_vehicle_status",
        "tescmd_vehicle_wake",
        "tescmd_vehicle_info",
        "tescmd_vehicle_location",
        "tescmd_charge_status",
        "tescmd_charge_start",
        "tescmd_charge_stop",
        "tescmd_charge_limit",
        "tescmd_charge_port_open",
        "tescmd_charge_port_close",
        "tescmd_climate_status",
        "tescmd_climate_start",
        "tescmd_climate_stop",
        "tescmd_climate_set_temps",
        "tescmd_climate_seat_heater",
        "tescmd_climate_steering_wheel_heater",
        "tescmd_security_status",
        "tescmd_security_lock",
        "tescmd_security_unlock",
        "tescmd_security_honk_horn",
        "tescmd_security_flash_lights",
        "tescmd_media_toggle_playback",
        "tescmd_media_volume_set",
        "tescmd_navigation_send",
        "tescmd_navigation_gps",
        "tescmd_navigation_waypoints",
        "tescmd_navigation_place_search",
        "tescmd_energy_list",
        "tescmd_energy_status",
        "tescmd_energy_live",
        "tescmd_key_generate",
        "tescmd_key_show",
        "tescmd_key_validate",
        "tescmd_key_enroll",
        "tescmd_key_deploy",
        "tescmd_cache_status",
        "tescmd_cache_clear",
        "tescmd_raw_get",
        "tescmd_raw_post",
        "tescmd_raw_delete",
    }
)


def registered_tool_specs() -> tuple[runtime.ToolSpec, ...]:
    surface = os.getenv(TOOL_SURFACE_ENV, "compact").strip().lower()
    specs = runtime.list_tool_specs()
    if surface in {"full", "all", "exhaustive"}:
        return tuple(specs)
    if surface not in {"", "compact", "core", "default"}:
        raise ValueError(f"Unsupported {TOOL_SURFACE_ENV}={surface!r}; use 'compact' or 'full'.")
    return tuple(spec for spec in specs if spec.name in _COMPACT_TOOL_NAMES)


def register(ctx) -> None:
    for spec in registered_tool_specs():
        ctx.register_tool(
            name=spec.name,
            toolset=TOOLSET_NAME,
            schema=schemas.build_schema(spec),
            handler=runtime.make_handler(spec),
            description=spec.description,
        )

    skill_path = Path(__file__).parent / "skills" / SKILL_NAME / "SKILL.md"
    if skill_path.exists():
        ctx.register_skill(SKILL_NAME, skill_path)


__all__ = [
    "PLUGIN_NAME",
    "SKILL_NAME",
    "TOOLSET_NAME",
    "__version__",
    "auth",
    "client",
    "config",
    "register",
    "registered_tool_specs",
    "runtime",
    "schemas",
    "tools",
]
