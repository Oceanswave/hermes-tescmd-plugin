from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from . import client, tools


@dataclass(frozen=True)
class ParamSpec:
    name: str
    description: str
    value_type: str = "string"
    required: bool = False
    enum: tuple[str, ...] = ()
    minimum: int | float | None = None
    maximum: int | float | None = None
    is_array: bool = False
    item_type: str = "string"
    default: Any = None


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    operation: str
    params: tuple[ParamSpec, ...] = field(default_factory=tuple)
    command_name: str | None = None
    payload_fields: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    fixed_payload: dict[str, Any] = field(default_factory=dict)
    payload_mode: str = "mapped"


_SHARED_OPERATIONAL_PARAMS = (
    ParamSpec("vin", "Vehicle VIN or Fleet vehicle ID (`id_s`). If omitted, the plugin uses the configured default vehicle identifier."),
    ParamSpec("profile", "Plugin auth/config profile to use.", default="default"),
    ParamSpec("region", "Tesla Fleet API region override.", enum=("na", "eu", "cn")),
    ParamSpec("wake", "Wake the vehicle before running the operation when useful. Waking is a real vehicle side effect; only set true when the user explicitly asked to wake/check a sleeping vehicle.", value_type="boolean", default=False),
    ParamSpec("confirm", "Set true to acknowledge high-risk, destructive, or wake side effects before they run.", value_type="boolean", default=False),
    ParamSpec("no_cache", "Bypass the plugin-native response cache for this read operation.", value_type="boolean", default=False),
    ParamSpec("units", "Preferred units hint for downstream formatting.", enum=("us", "metric")),
)

_SHARED_PROFILE_ONLY_PARAMS = (
    ParamSpec("profile", "Plugin auth/config profile to use.", default="default"),
)
_CONFIRM_REQUIRED = ParamSpec("confirm", "Required acknowledgement before this side-effecting operation runs.", value_type="boolean", required=True)


def _with_required_confirm(params: tuple[ParamSpec, ...]) -> tuple[ParamSpec, ...]:
    return tuple(_CONFIRM_REQUIRED if param.name == "confirm" else param for param in params)


_SHARED_VEHICLE_PARAMS = _SHARED_OPERATIONAL_PARAMS[:3]
_SHARED_COMMAND_PARAMS = _with_required_confirm(_SHARED_VEHICLE_PARAMS + (_SHARED_OPERATIONAL_PARAMS[4],))

_ENABLED_REQUIRED = ParamSpec("enabled", "Whether to enable the feature.", value_type="boolean", required=True)
_MANUAL_OVERRIDE = ParamSpec("manual_override", "Whether the vehicle should treat the request as a manual override.", value_type="boolean")
_PASSWORD = ParamSpec("password", "Security PIN/password required by some vehicle features.")
_PIN = ParamSpec("pin", "Security PIN for speed-limit features.")
_ORDER = ParamSpec("order", "Optional 1-based waypoint/navigation order. For multi-stop GPS routes, send the first stop with order=1, second with order=2, etc.", value_type="integer", minimum=1)
_SEAT_POSITION = ParamSpec("seat_position", "Seat position index used by climate seat controls: 0=driver, 1=passenger, 2=rear-left, 4=rear-center, 5=rear-right.", value_type="integer", required=True)
_LEVEL = ParamSpec("level", "Feature intensity/level value. Seat heat/cool commonly uses 0=off through 3=high.", value_type="integer", required=True)
_LAT = ParamSpec("lat", "Latitude in decimal degrees, -90 through 90.", value_type="number", required=True, minimum=-90, maximum=90)
_LON = ParamSpec("lon", "Longitude in decimal degrees, -180 through 180.", value_type="number", required=True, minimum=-180, maximum=180)
_ID = ParamSpec("id", "Schedule identifier.", value_type="integer", required=True)
_START_TIME = ParamSpec("start_time", "Start time in minutes after midnight.", value_type="integer", required=True)
_END_TIME = ParamSpec("end_time", "End time in minutes after midnight.", value_type="integer", required=True)
_HOME = ParamSpec("home", "Apply to the home schedule bucket.", value_type="boolean")
_WORK = ParamSpec("work", "Apply to the work schedule bucket.", value_type="boolean")
_OTHER = ParamSpec("other", "Apply to the other/custom schedule bucket.", value_type="boolean")


def _vehicle_command_tool(
    *,
    name: str,
    description: str,
    command_name: str,
    params: tuple[ParamSpec, ...] = (),
    payload_fields: tuple[tuple[str, str], ...] = (),
    fixed_payload: dict[str, Any] | None = None,
    payload_mode: str = "mapped",
) -> ToolSpec:
    return ToolSpec(
        name=name,
        description=description,
        operation="vehicle_command",
        command_name=command_name,
        params=_SHARED_COMMAND_PARAMS + params,
        payload_fields=payload_fields,
        fixed_payload=fixed_payload or {},
        payload_mode=payload_mode,
    )


def _profile_tool(*, name: str, description: str, operation: str, params: tuple[ParamSpec, ...] = ()) -> ToolSpec:
    return ToolSpec(name=name, description=description, operation=operation, params=_SHARED_PROFILE_ONLY_PARAMS + params)


def _operational_tool(*, name: str, description: str, operation: str, params: tuple[ParamSpec, ...] = ()) -> ToolSpec:
    return ToolSpec(name=name, description=description, operation=operation, params=_SHARED_VEHICLE_PARAMS + params)


def _status_read_tool(*, name: str, description: str, operation: str, params: tuple[ParamSpec, ...] = ()) -> ToolSpec:
    return ToolSpec(name=name, description=description, operation=operation, params=_SHARED_OPERATIONAL_PARAMS + params)


def _energy_tool(*, name: str, description: str, operation: str, params: tuple[ParamSpec, ...] = ()) -> ToolSpec:
    return ToolSpec(
        name=name,
        description=description,
        operation=operation,
        params=_SHARED_PROFILE_ONLY_PARAMS + (ParamSpec("site_id", "Tesla energy site identifier.", value_type="integer", required=True),) + params,
    )


_TOOL_SPECS: tuple[ToolSpec, ...] = (
    ToolSpec("tescmd_auth_login", "Admin/bootstrap: start a Hermes-native Tesla OAuth PKCE login flow and return the authorize URL. Uses the configured public HTTPS oauth_redirect_uri or https://<domain>/callback.", "auth_login", _SHARED_PROFILE_ONLY_PARAMS + (
        ParamSpec("scopes", "Optional scope override for this login attempt.", is_array=True, item_type="string"),
    )),
    ToolSpec("tescmd_auth_complete", "Admin/bootstrap: complete the Tesla OAuth login flow using a callback URL or code/state pair.", "auth_complete", _SHARED_PROFILE_ONLY_PARAMS + (
        ParamSpec("callback_url", "Full public OAuth callback URL captured after Tesla redirects back."),
        ParamSpec("code", "Authorization code from Tesla OAuth callback."),
        ParamSpec("state", "OAuth state returned by Tesla OAuth callback."),
        _CONFIRM_REQUIRED,
    )),
    ToolSpec("tescmd_auth_status", "Admin/bootstrap: show plugin-owned Tesla auth, profile config, and stored key status.", "auth_status", _SHARED_PROFILE_ONLY_PARAMS),
    ToolSpec("tescmd_auth_refresh", "Admin/bootstrap: refresh Tesla access tokens using the stored refresh token.", "auth_refresh", _SHARED_PROFILE_ONLY_PARAMS + (_CONFIRM_REQUIRED,)),
    ToolSpec("tescmd_auth_import", "Admin/bootstrap: import previously exported plugin auth state into the selected profile.", "auth_import", _SHARED_PROFILE_ONLY_PARAMS + (
        ParamSpec("auth", "Auth payload previously returned by tescmd_auth_export.", value_type="object", required=True),
        _CONFIRM_REQUIRED,
    )),
    ToolSpec("tescmd_auth_export", "Admin/bootstrap: export the stored Tesla auth state for backup or migration to a 0600 file; token values are never returned in tool output.", "auth_export", _SHARED_PROFILE_ONLY_PARAMS + (
        ParamSpec("confirm", "Required acknowledgement because this writes sensitive auth tokens to disk.", value_type="boolean", required=True),
        ParamSpec("output_path", "Optional export filename/path under the plugin exports directory."),
    )),
    ToolSpec("tescmd_auth_register", "Admin/bootstrap: register the configured Tesla Fleet partner account domain using client credentials.", "auth_register", _SHARED_PROFILE_ONLY_PARAMS + (_CONFIRM_REQUIRED,)),
    ToolSpec("tescmd_vehicle_list", "List vehicles visible to the configured Tesla account.", "vehicle_list", _SHARED_PROFILE_ONLY_PARAMS + (
        ParamSpec("region", "Tesla Fleet API region override.", enum=("na", "eu", "cn")),
    )),
    ToolSpec("tescmd_vehicle_status", "Fetch Tesla vehicle status using the Fleet API vehicle_data endpoint.", "vehicle_status", _SHARED_OPERATIONAL_PARAMS + (
        ParamSpec("endpoints", "Optional vehicle_data endpoint list to limit the payload.", is_array=True, item_type="string"),
    )),
    ToolSpec("tescmd_vehicle_wake", "Wake a Tesla vehicle through the Fleet API. This is a real vehicle side effect and requires confirm=true.", "vehicle_wake", _with_required_confirm(_SHARED_OPERATIONAL_PARAMS)),
    ToolSpec("tescmd_charge_status", "Fetch charge-state data for the selected vehicle.", "charge_status", _SHARED_OPERATIONAL_PARAMS),
    _vehicle_command_tool(name="tescmd_charge_start", description="Start Tesla vehicle charging.", command_name="charge_start"),
    _vehicle_command_tool(name="tescmd_charge_stop", description="Stop Tesla vehicle charging.", command_name="charge_stop"),
    _vehicle_command_tool(
        name="tescmd_charge_limit",
        description="Set Tesla charge limit percentage.",
        command_name="set_charge_limit",
        params=(ParamSpec("percent", "Target charge limit percentage.", value_type="integer", required=True, minimum=50, maximum=100),),
        payload_fields=(("percent", "percent"),),
    ),
    _vehicle_command_tool(name="tescmd_charge_standard", description="Switch charging mode to standard.", command_name="charge_standard"),
    _vehicle_command_tool(name="tescmd_charge_max_range", description="Switch charging mode to max range.", command_name="charge_max_range"),
    _vehicle_command_tool(name="tescmd_charge_port_open", description="Open the charge port door.", command_name="charge_port_door_open"),
    _vehicle_command_tool(name="tescmd_charge_port_close", description="Close the charge port door.", command_name="charge_port_door_close"),
    _vehicle_command_tool(
        name="tescmd_charge_set_amps",
        description="Set the charging amperage target.",
        command_name="set_charging_amps",
        params=(ParamSpec("amps", "Charging amperage to request.", value_type="integer", required=True),),
        payload_fields=(("amps", "charging_amps"),),
    ),
    _vehicle_command_tool(
        name="tescmd_charge_schedule_set",
        description="Enable or update scheduled charging.",
        command_name="set_scheduled_charging",
        params=(
            _ENABLED_REQUIRED,
            ParamSpec("charging_time", "Scheduled charging time in minutes after midnight.", value_type="integer"),
        ),
        payload_fields=(("enabled", "enable"), ("charging_time", "charging_time")),
    ),
    _vehicle_command_tool(
        name="tescmd_charge_departure_set",
        description="Enable or update scheduled departure.",
        command_name="set_scheduled_departure",
        params=(
            _ENABLED_REQUIRED,
            ParamSpec("departure_time", "Scheduled departure time in minutes after midnight.", value_type="integer"),
        ),
        payload_fields=(("enabled", "enable"), ("departure_time", "departure_time")),
    ),
    _vehicle_command_tool(
        name="tescmd_charge_schedule_add",
        description="Add a charge schedule entry.",
        command_name="add_charge_schedule",
        params=(_ID, _START_TIME, _END_TIME),
        payload_fields=(("id", "id"), ("start_time", "start_time"), ("end_time", "end_time")),
    ),
    _vehicle_command_tool(
        name="tescmd_charge_schedule_remove",
        description="Remove a charge schedule entry by ID.",
        command_name="remove_charge_schedule",
        params=(_ID,),
        payload_fields=(("id", "id"),),
    ),
    _vehicle_command_tool(
        name="tescmd_charge_schedules_clear",
        description="Batch-remove charge schedules from one or more buckets.",
        command_name="batch_remove_charge_schedules",
        params=(_HOME, _WORK, _OTHER),
        payload_fields=(("home", "home"), ("work", "work"), ("other", "other")),
    ),
    _vehicle_command_tool(
        name="tescmd_precondition_schedule_add",
        description="Add a cabin preconditioning schedule entry.",
        command_name="add_precondition_schedule",
        params=(_ID, _START_TIME, _END_TIME),
        payload_fields=(("id", "id"), ("start_time", "start_time"), ("end_time", "end_time")),
    ),
    _vehicle_command_tool(
        name="tescmd_precondition_schedule_remove",
        description="Remove a preconditioning schedule entry by ID.",
        command_name="remove_precondition_schedule",
        params=(_ID,),
        payload_fields=(("id", "id"),),
    ),
    _vehicle_command_tool(
        name="tescmd_precondition_schedules_clear",
        description="Batch-remove preconditioning schedules from one or more buckets.",
        command_name="batch_remove_precondition_schedules",
        params=(_HOME, _WORK, _OTHER),
        payload_fields=(("home", "home"), ("work", "work"), ("other", "other")),
    ),
    _vehicle_command_tool(
        name="tescmd_charge_managed_current_set",
        description="Set the managed charging current request.",
        command_name="set_managed_charge_current_request",
        params=(ParamSpec("amps", "Managed charging amperage request.", value_type="integer", required=True),),
        payload_fields=(("amps", "charging_amps"),),
    ),
    _vehicle_command_tool(
        name="tescmd_charge_managed_location_set",
        description="Set the managed charger location coordinates.",
        command_name="set_managed_charger_location",
        params=(_LAT, _LON),
        payload_mode="managed_location",
    ),
    _vehicle_command_tool(
        name="tescmd_charge_managed_schedule_set",
        description="Set the managed scheduled charging time in minutes after midnight.",
        command_name="set_managed_scheduled_charging_time",
        params=(ParamSpec("time_minutes", "Managed charging time in minutes after midnight.", value_type="integer", required=True),),
        payload_fields=(("time_minutes", "time"),),
    ),
    ToolSpec("tescmd_climate_status", "Fetch climate-state data for the selected vehicle.", "climate_status", _SHARED_OPERATIONAL_PARAMS),
    _vehicle_command_tool(name="tescmd_climate_start", description="Start Tesla climate control.", command_name="auto_conditioning_start"),
    _vehicle_command_tool(name="tescmd_climate_stop", description="Stop Tesla climate control.", command_name="auto_conditioning_stop"),
    _vehicle_command_tool(
        name="tescmd_climate_set_temps",
        description="Set driver and passenger cabin temperatures.",
        command_name="set_temps",
        params=(
            ParamSpec("driver_temp", "Driver temperature setpoint.", value_type="number", required=True),
            ParamSpec("passenger_temp", "Passenger temperature setpoint.", value_type="number", required=True),
        ),
        payload_fields=(("driver_temp", "driver_temp"), ("passenger_temp", "passenger_temp")),
    ),
    _vehicle_command_tool(
        name="tescmd_climate_preconditioning_max",
        description="Enable or disable max preconditioning.",
        command_name="set_preconditioning_max",
        params=(_ENABLED_REQUIRED, _MANUAL_OVERRIDE),
        payload_fields=(("enabled", "on"), ("manual_override", "manual_override")),
    ),
    _vehicle_command_tool(
        name="tescmd_climate_seat_heater",
        description="Set seat heater level for a specific seat position.",
        command_name="remote_seat_heater_request",
        params=(_SEAT_POSITION, ParamSpec("level", "Seat heater level.", value_type="integer", required=True, minimum=0, maximum=3)),
        payload_fields=(("seat_position", "seat_position"), ("level", "level")),
    ),
    _vehicle_command_tool(
        name="tescmd_climate_seat_cooler",
        description="Set seat cooler level for a specific seat position.",
        command_name="remote_seat_cooler_request",
        params=(_SEAT_POSITION, ParamSpec("level", "Seat cooler level.", value_type="integer", required=True, minimum=0, maximum=3)),
        payload_fields=(("seat_position", "seat_position"), ("level", "level")),
    ),
    _vehicle_command_tool(
        name="tescmd_climate_steering_wheel_heater",
        description="Enable or disable the steering wheel heater.",
        command_name="remote_steering_wheel_heater_request",
        params=(_ENABLED_REQUIRED,),
        payload_fields=(("enabled", "on"),),
    ),
    _vehicle_command_tool(
        name="tescmd_climate_cabin_overheat_protection",
        description="Enable or disable cabin overheat protection.",
        command_name="set_cabin_overheat_protection",
        params=(_ENABLED_REQUIRED, ParamSpec("fan_only", "Use fan-only mode when supported.", value_type="boolean")),
        payload_fields=(("enabled", "on"), ("fan_only", "fan_only")),
    ),
    _vehicle_command_tool(
        name="tescmd_climate_keeper_mode",
        description="Set climate keeper mode using the vehicle's numeric mode value.",
        command_name="set_climate_keeper_mode",
        params=(ParamSpec("climate_keeper_mode", "Climate keeper mode value.", value_type="integer", required=True), _MANUAL_OVERRIDE),
        payload_fields=(("climate_keeper_mode", "climate_keeper_mode"), ("manual_override", "manual_override")),
    ),
    _vehicle_command_tool(
        name="tescmd_climate_cop_temp",
        description="Set the cabin overheat protection activation temperature.",
        command_name="set_cop_temp",
        params=(ParamSpec("cop_temp", "Cabin overheat protection activation temperature.", value_type="integer", required=True),),
        payload_fields=(("cop_temp", "cop_temp"),),
    ),
    _vehicle_command_tool(
        name="tescmd_climate_auto_seat",
        description="Enable or disable auto seat climate for a specific seat.",
        command_name="remote_auto_seat_climate_request",
        params=(_SEAT_POSITION, _ENABLED_REQUIRED),
        payload_fields=(("seat_position", "seat_position"), ("enabled", "on")),
    ),
    _vehicle_command_tool(
        name="tescmd_climate_auto_steering_wheel_heat",
        description="Enable or disable automatic steering wheel heat climate behavior.",
        command_name="remote_auto_steering_wheel_heat_climate_request",
        params=(_ENABLED_REQUIRED,),
        payload_fields=(("enabled", "on"),),
    ),
    _vehicle_command_tool(
        name="tescmd_climate_steering_wheel_heat_level",
        description="Set the steering wheel heat level.",
        command_name="remote_steering_wheel_heat_level_request",
        params=(ParamSpec("level", "Steering wheel heat level.", value_type="integer", required=True, minimum=0, maximum=3),),
        payload_fields=(("level", "level"),),
    ),
    _vehicle_command_tool(
        name="tescmd_climate_bioweapon_mode",
        description="Enable or disable bioweapon defense mode.",
        command_name="set_bioweapon_mode",
        params=(_ENABLED_REQUIRED, _MANUAL_OVERRIDE),
        payload_fields=(("enabled", "on"), ("manual_override", "manual_override")),
    ),
    _vehicle_command_tool(name="tescmd_security_lock", description="Lock Tesla vehicle doors.", command_name="door_lock"),
    _vehicle_command_tool(name="tescmd_security_unlock", description="Unlock Tesla vehicle doors.", command_name="door_unlock"),
    _vehicle_command_tool(name="tescmd_security_honk_horn", description="Honk the vehicle horn.", command_name="honk_horn"),
    _vehicle_command_tool(name="tescmd_security_flash_lights", description="Flash the vehicle lights.", command_name="flash_lights"),
    _vehicle_command_tool(
        name="tescmd_security_sentry_mode",
        description="Enable or disable Sentry Mode.",
        command_name="set_sentry_mode",
        params=(_ENABLED_REQUIRED,),
        payload_fields=(("enabled", "on"),),
    ),
    _vehicle_command_tool(name="tescmd_security_remote_start_drive", description="Remote-start the vehicle for driving.", command_name="remote_start_drive"),
    _vehicle_command_tool(name="tescmd_security_auto_secure_vehicle", description="Request the vehicle to auto-secure itself.", command_name="auto_secure_vehicle"),
    _vehicle_command_tool(
        name="tescmd_security_valet_mode",
        description="Enable or disable valet mode.",
        command_name="set_valet_mode",
        params=(_ENABLED_REQUIRED, _PASSWORD),
        payload_fields=(("enabled", "on"), ("password", "password")),
    ),
    _vehicle_command_tool(name="tescmd_security_reset_valet_pin", description="Reset the valet PIN.", command_name="reset_valet_pin"),
    _vehicle_command_tool(
        name="tescmd_security_speed_limit_activate",
        description="Activate speed limit mode.",
        command_name="speed_limit_activate",
        params=(_PIN,),
        payload_fields=(("pin", "pin"),),
    ),
    _vehicle_command_tool(
        name="tescmd_security_speed_limit_deactivate",
        description="Deactivate speed limit mode.",
        command_name="speed_limit_deactivate",
        params=(_PIN,),
        payload_fields=(("pin", "pin"),),
    ),
    _vehicle_command_tool(
        name="tescmd_security_speed_limit_set",
        description="Set the speed limit in miles per hour.",
        command_name="speed_limit_set_limit",
        params=(ParamSpec("limit_mph", "Speed limit in miles per hour.", value_type="integer", required=True),),
        payload_fields=(("limit_mph", "limit_mph"),),
    ),
    _vehicle_command_tool(
        name="tescmd_security_speed_limit_clear_pin",
        description="Clear the speed limit PIN using the existing PIN when required.",
        command_name="speed_limit_clear_pin",
        params=(_PIN,),
        payload_fields=(("pin", "pin"),),
    ),
    _vehicle_command_tool(
        name="tescmd_security_pin_to_drive",
        description="Enable or disable PIN to Drive.",
        command_name="set_pin_to_drive",
        params=(_ENABLED_REQUIRED, _PASSWORD),
        payload_fields=(("enabled", "on"), ("password", "password")),
    ),
    _vehicle_command_tool(name="tescmd_security_reset_pin_to_drive_pin", description="Reset the PIN to Drive PIN.", command_name="reset_pin_to_drive_pin"),
    _vehicle_command_tool(name="tescmd_security_clear_pin_to_drive_admin", description="Clear PIN to Drive using admin privileges.", command_name="clear_pin_to_drive_admin"),
    _vehicle_command_tool(name="tescmd_security_speed_limit_clear_pin_admin", description="Clear the speed limit PIN using admin privileges.", command_name="speed_limit_clear_pin_admin"),
    _vehicle_command_tool(
        name="tescmd_security_guest_mode",
        description="Enable or disable guest mode.",
        command_name="guest_mode",
        params=(_ENABLED_REQUIRED,),
        payload_fields=(("enabled", "enable"),),
    ),
    _vehicle_command_tool(name="tescmd_security_erase_user_data", description="Erase user data from the vehicle.", command_name="erase_user_data"),
    _vehicle_command_tool(
        name="tescmd_security_boombox",
        description="Trigger a remote boombox sound/action.",
        command_name="remote_boombox",
        params=(ParamSpec("sound", "Boombox sound/action identifier.", value_type="integer", required=True),),
        payload_fields=(("sound", "sound"),),
    ),
    _vehicle_command_tool(
        name="tescmd_vehicle_actuate_trunk",
        description="Actuate the front or rear trunk.",
        command_name="actuate_trunk",
        params=(ParamSpec("which_trunk", "Which trunk to actuate.", required=True, enum=("front", "rear")),),
        payload_fields=(("which_trunk", "which_trunk"),),
    ),
    _vehicle_command_tool(name="tescmd_vehicle_tonneau_open", description="Open the tonneau cover.", command_name="open_tonneau"),
    _vehicle_command_tool(name="tescmd_vehicle_tonneau_close", description="Close the tonneau cover.", command_name="close_tonneau"),
    _vehicle_command_tool(name="tescmd_vehicle_tonneau_stop", description="Stop tonneau cover movement.", command_name="stop_tonneau"),
    _vehicle_command_tool(name="tescmd_media_toggle_playback", description="Toggle media playback.", command_name="media_toggle_playback"),
    _vehicle_command_tool(name="tescmd_media_next_track", description="Skip to the next media track.", command_name="media_next_track"),
    _vehicle_command_tool(name="tescmd_media_prev_track", description="Go to the previous media track.", command_name="media_prev_track"),
    _vehicle_command_tool(name="tescmd_media_next_favorite", description="Jump to the next favorite media source.", command_name="media_next_fav"),
    _vehicle_command_tool(name="tescmd_media_prev_favorite", description="Jump to the previous favorite media source.", command_name="media_prev_fav"),
    _vehicle_command_tool(name="tescmd_media_volume_up", description="Increase media volume.", command_name="media_volume_up"),
    _vehicle_command_tool(name="tescmd_media_volume_down", description="Decrease media volume.", command_name="media_volume_down"),
    _vehicle_command_tool(
        name="tescmd_media_volume_set",
        description="Set the media volume to an absolute level.",
        command_name="adjust_volume",
        params=(ParamSpec("volume", "Absolute media volume level.", value_type="number", required=True),),
        payload_fields=(("volume", "volume"),),
    ),
    _vehicle_command_tool(
        name="tescmd_navigation_send",
        description="Send a navigation destination string to the vehicle.",
        command_name="navigation_request",
        params=(ParamSpec("destination", "Destination string or address.", required=True), _ORDER),
        payload_fields=(("destination", "destination"), ("order", "order")),
    ),
    _vehicle_command_tool(
        name="tescmd_navigation_gps",
        description="Send raw GPS coordinates to the navigation system.",
        command_name="navigation_gps_request",
        params=(_LAT, _LON, _ORDER),
        payload_fields=(("lat", "lat"), ("lon", "lon"), ("order", "order")),
    ),
    _vehicle_command_tool(
        name="tescmd_navigation_supercharger",
        description="Route to a supercharger by order/index.",
        command_name="navigation_sc_request",
        params=(_ORDER,),
        payload_fields=(("order", "order"),),
    ),
    _vehicle_command_tool(
        name="tescmd_navigation_waypoints",
        description="Send a multi-stop route to Tesla navigation using Google Maps Place IDs. Provide place_ids without refId:; the tool encodes refId:<place_id>,... for Tesla. This does not call Google Maps.",
        command_name="navigation_waypoints_request",
        params=(
            ParamSpec("place_ids", "Google Maps Place IDs, without refId: prefix. Use tescmd_navigation_place_search first if you need to resolve addresses and have configured google_maps_api_key.", required=True, is_array=True, item_type="string"),
        ),
        payload_mode="navigation_place_ids",
    ),
    _vehicle_command_tool(
        name="tescmd_navigation_waypoints_raw",
        description="Advanced: send a pre-encoded Tesla waypoints payload string such as refId:<PLACE_ID_1>,refId:<PLACE_ID_2>.",
        command_name="navigation_waypoints_request",
        params=(ParamSpec("waypoints", "Pre-encoded waypoints payload string, usually refId:<PLACE_ID_1>,refId:<PLACE_ID_2>.", required=True),),
        payload_fields=(("waypoints", "waypoints"),),
    ),
    _vehicle_command_tool(
        name="tescmd_vehicle_homelink_trigger",
        description="Trigger Homelink using the provided coordinates.",
        command_name="trigger_homelink",
        params=(_LAT, _LON),
        payload_fields=(("lat", "lat"), ("lon", "lon")),
    ),
    _vehicle_command_tool(
        name="tescmd_software_update_schedule",
        description="Schedule a software update after the given offset.",
        command_name="schedule_software_update",
        params=(ParamSpec("offset_sec", "Delay before the software update starts, in seconds.", value_type="integer", required=True),),
        payload_fields=(("offset_sec", "offset_sec"),),
    ),
    _vehicle_command_tool(name="tescmd_software_update_cancel", description="Cancel a scheduled software update.", command_name="cancel_software_update"),
    _vehicle_command_tool(
        name="tescmd_vehicle_name_set",
        description="Set the vehicle display name.",
        command_name="set_vehicle_name",
        params=(ParamSpec("name", "Vehicle display name.", required=True),),
        payload_fields=(("name", "vehicle_name"),),
    ),
    _vehicle_command_tool(
        name="tescmd_vehicle_calendar_upcoming",
        description="Push upcoming calendar data to the vehicle.",
        command_name="upcoming_calendar_entries",
        params=(ParamSpec("calendar_data", "Calendar payload string to send to the vehicle.", required=True),),
        payload_fields=(("calendar_data", "calendar_data"),),
    ),
    _vehicle_command_tool(
        name="tescmd_vehicle_window_control",
        description="Vent or close the windows.",
        command_name="window_control",
        params=(
            ParamSpec("command", "Window command.", required=True, enum=("vent", "close")),
            ParamSpec("lat", "Vehicle latitude used when closing windows.", value_type="number"),
            ParamSpec("lon", "Vehicle longitude used when closing windows.", value_type="number"),
        ),
        payload_fields=(("command", "command"), ("lat", "lat"), ("lon", "lon")),
    ),
    _vehicle_command_tool(
        name="tescmd_vehicle_sunroof_control",
        description="Open, vent, close, or stop the sunroof.",
        command_name="sun_roof_control",
        params=(ParamSpec("state", "Sunroof state.", required=True, enum=("open", "vent", "close", "stop")),),
        payload_fields=(("state", "state"),),
    ),
    _vehicle_command_tool(name="tescmd_vehicle_trunk_open", description="Open the rear trunk.", command_name="actuate_trunk", params=(), fixed_payload={"which_trunk": "rear"}),
    _vehicle_command_tool(name="tescmd_vehicle_trunk_close", description="Close the rear trunk.", command_name="actuate_trunk", params=(), fixed_payload={"which_trunk": "rear"}),
    _vehicle_command_tool(name="tescmd_vehicle_calendar", description="Push upcoming calendar data to the vehicle.", command_name="upcoming_calendar_entries", params=(ParamSpec("calendar_data", "Calendar payload string to send to the vehicle.", required=True),), payload_fields=(("calendar_data", "calendar_data"),)),
    _vehicle_command_tool(name="tescmd_vehicle_low_power", description="Enable or disable low power mode.", command_name="set_low_power_mode", params=(_ENABLED_REQUIRED,), payload_fields=(("enabled", "enable"),)),
    _vehicle_command_tool(name="tescmd_vehicle_accessory_power", description="Enable or disable accessory power keep-alive mode.", command_name="keep_accessory_power_mode", params=(_ENABLED_REQUIRED,), payload_fields=(("enabled", "enable"),)),
    _vehicle_command_tool(
        name="tescmd_power_low_power_mode",
        description="Enable or disable low power mode.",
        command_name="set_low_power_mode",
        params=(_ENABLED_REQUIRED,),
        payload_fields=(("enabled", "enable"),),
    ),
    _vehicle_command_tool(
        name="tescmd_power_keep_accessory_mode",
        description="Enable or disable accessory power keep-alive mode.",
        command_name="keep_accessory_power_mode",
        params=(_ENABLED_REQUIRED,),
        payload_fields=(("enabled", "enable"),),
    ),
    ToolSpec("tescmd_status", "Admin/bootstrap: show overall plugin configuration, auth, profile, and key status.", "status", _SHARED_PROFILE_ONLY_PARAMS),
    _profile_tool(name="tescmd_auth_logout", description="Admin/bootstrap: clear stored Tesla OAuth state for the selected profile.", operation="auth_logout", params=(_CONFIRM_REQUIRED,)),
    _profile_tool(name="tescmd_key_generate", description="Admin/bootstrap: generate or replace the plugin-owned Tesla vehicle-command keypair.", operation="key_generate", params=(ParamSpec("force", "Overwrite an existing keypair.", value_type="boolean", default=False), _CONFIRM_REQUIRED)),
    _profile_tool(name="tescmd_key_show", description="Admin/bootstrap: show key paths, fingerprint, and expected hosted key URL.", operation="key_show"),
    _profile_tool(name="tescmd_key_validate", description="Admin/bootstrap: check whether the configured domain serves the public key at Tesla's required well-known path.", operation="key_validate"),
    _profile_tool(name="tescmd_key_enroll", description="Admin/bootstrap: prepare Tesla virtual-key enrollment instructions and URLs for the configured domain.", operation="key_enroll"),
    _profile_tool(name="tescmd_key_unenroll", description="Admin/bootstrap: show instructions for removing the virtual key and revoking OAuth consent.", operation="key_unenroll"),
    _profile_tool(name="tescmd_key_deploy", description="Admin/bootstrap: prepare local public-key hosting files for manual HTTPS deployment.", operation="key_deploy", params=(ParamSpec("method", "Deployment method; only local manual hosting is supported.", enum=("local",), default="local"), _CONFIRM_REQUIRED,)),
    _profile_tool(name="tescmd_user_me", description="Fetch the current Tesla account profile.", operation="user_me"),
    _profile_tool(name="tescmd_user_region", description="Fetch the Tesla account's regional Fleet API information.", operation="user_region"),
    _profile_tool(name="tescmd_user_orders", description="Fetch Tesla vehicle orders for the account.", operation="user_orders"),
    _profile_tool(name="tescmd_user_features", description="Fetch Tesla feature-flag configuration for the account.", operation="user_features"),
    _profile_tool(name="tescmd_partner_public_key", description="Fetch the public key currently registered for a partner domain.", operation="partner_public_key", params=(ParamSpec("domain", "Domain to query. Defaults to the configured profile domain."),)),
    _profile_tool(name="tescmd_partner_telemetry_error_vins", description="List VINs with recent fleet telemetry errors for the partner account.", operation="partner_telemetry_error_vins"),
    _profile_tool(name="tescmd_partner_telemetry_errors", description="Fetch recent partner-account fleet telemetry errors.", operation="partner_telemetry_errors"),
    _profile_tool(name="tescmd_billing_history", description="Fetch Supercharger charging history.", operation="billing_history", params=(ParamSpec("vin_filter", "Optional VIN filter."), ParamSpec("start_time", "ISO-8601 start time."), ParamSpec("end_time", "ISO-8601 end time."), ParamSpec("page", "0-based page number.", value_type="integer"), ParamSpec("page_size", "Results per page.", value_type="integer"))),
    _profile_tool(name="tescmd_billing_sessions", description="Fetch business-account charging sessions.", operation="billing_sessions", params=(ParamSpec("vin_filter", "Optional VIN filter."), ParamSpec("date_from", "ISO-8601 start date."), ParamSpec("date_to", "ISO-8601 end date."), ParamSpec("limit", "Max results.", value_type="integer"), ParamSpec("offset", "Pagination offset.", value_type="integer"))),
    _profile_tool(name="tescmd_billing_invoice", description="Fetch charging invoice metadata or content by invoice ID. If output_path is supplied, confirm=true is required and the file is written locally.", operation="billing_invoice", params=(ParamSpec("invoice_id", "Invoice identifier.", required=True), ParamSpec("output_path", "Optional local file path for saving string invoice content."), ParamSpec("confirm", "Required when output_path is supplied because this writes a local file.", value_type="boolean", default=False))),
    _profile_tool(name="tescmd_energy_list", description="List Tesla energy products on the account.", operation="energy_list"),
    _energy_tool(name="tescmd_energy_live", description="Fetch real-time power flow for an energy site.", operation="energy_live"),
    _energy_tool(name="tescmd_energy_status", description="Fetch site configuration and metadata for an energy site.", operation="energy_status"),
    _energy_tool(name="tescmd_energy_backup", description="Set backup reserve percentage for an energy site.", operation="energy_backup", params=(ParamSpec("percent", "Backup reserve percentage.", value_type="integer", required=True), _CONFIRM_REQUIRED)),
    _energy_tool(name="tescmd_energy_mode", description="Set energy-site operation mode.", operation="energy_mode", params=(ParamSpec("mode", "Operation mode.", required=True, enum=("self_consumption", "backup", "autonomous")), _CONFIRM_REQUIRED)),
    _energy_tool(name="tescmd_energy_storm", description="Enable or disable storm mode for an energy site.", operation="energy_storm", params=(_ENABLED_REQUIRED, _CONFIRM_REQUIRED)),
    _energy_tool(name="tescmd_energy_tou", description="Set time-of-use settings for an energy site.", operation="energy_tou", params=(ParamSpec("settings", "Time-of-use settings JSON object.", value_type="object", required=True), _CONFIRM_REQUIRED)),
    _energy_tool(name="tescmd_energy_calendar", description="Fetch calendar-based energy history.", operation="energy_calendar", params=(ParamSpec("kind", "History kind.", default="energy"), ParamSpec("period", "Aggregation period.", default="day"), ParamSpec("start_date", "Optional RFC3339/ISO-8601 start date-time."), ParamSpec("end_date", "Optional RFC3339/ISO-8601 end date-time."), ParamSpec("time_zone", "IANA timezone name."))),
    _energy_tool(name="tescmd_energy_history", description="Fetch telemetry-based charging history for an energy site.", operation="energy_history", params=(ParamSpec("start_date", "Optional RFC3339/ISO-8601 start date-time; Tesla rejects date-only values for this endpoint."), ParamSpec("end_date", "Optional RFC3339/ISO-8601 end date-time."), ParamSpec("time_zone", "IANA timezone name."))),
    _energy_tool(name="tescmd_energy_off_grid", description="Set off-grid vehicle charging reserve percentage.", operation="energy_off_grid", params=(ParamSpec("reserve", "Reserve percentage.", value_type="integer", required=True), _CONFIRM_REQUIRED)),
    _energy_tool(name="tescmd_energy_grid_config", description="Set grid import/export configuration for an energy site.", operation="energy_grid_config", params=(ParamSpec("config", "Grid import/export JSON object.", value_type="object", required=True), _CONFIRM_REQUIRED)),
    _energy_tool(name="tescmd_energy_telemetry", description="Fetch telemetry history for an energy site.", operation="energy_telemetry", params=(ParamSpec("kind", "Telemetry history kind.", default="charge"), ParamSpec("start_date", "Optional RFC3339/ISO-8601 start date-time; Tesla rejects date-only values for this endpoint."), ParamSpec("end_date", "Optional RFC3339/ISO-8601 end date-time."), ParamSpec("time_zone", "IANA timezone name."))),
    _operational_tool(name="tescmd_vehicle_get", description="Fetch lightweight vehicle information without full vehicle_data.", operation="vehicle_get"),
    _status_read_tool(name="tescmd_vehicle_info", description="Fetch full vehicle data for the selected vehicle.", operation="vehicle_info"),
    _status_read_tool(name="tescmd_vehicle_location", description="Fetch current drive/location data for the selected vehicle.", operation="vehicle_location"),
    _status_read_tool(name="tescmd_vehicle_drive_status", description="Fetch drive_state vehicle data for route, shift, and GPS status.", operation="vehicle_drive_status"),
    _status_read_tool(name="tescmd_vehicle_closures_status", description="Fetch closures_state vehicle data for doors, windows, trunks, and charge-port closure state.", operation="vehicle_closures_status"),
    _status_read_tool(name="tescmd_vehicle_config_status", description="Fetch vehicle_config data for model, trim, option, and capability metadata.", operation="vehicle_config_status"),
    _status_read_tool(name="tescmd_vehicle_gui_settings", description="Fetch gui_settings vehicle data for display units and user interface preferences.", operation="vehicle_gui_settings"),
    _status_read_tool(name="tescmd_vehicle_charge_schedule_status", description="Fetch charge_schedule_data for configured charge schedules.", operation="vehicle_charge_schedule_status"),
    _status_read_tool(name="tescmd_vehicle_preconditioning_schedule_status", description="Fetch preconditioning_schedule_data for configured climate preconditioning schedules.", operation="vehicle_preconditioning_schedule_status"),
    _operational_tool(name="tescmd_vehicle_mobile_access", description="Check whether mobile access is enabled for the selected vehicle.", operation="vehicle_mobile_access"),
    _operational_tool(name="tescmd_vehicle_nearby_chargers", description="Fetch nearby charging sites for the selected vehicle.", operation="vehicle_nearby_chargers"),
    _operational_tool(name="tescmd_vehicle_alerts", description="Fetch recent alerts for the selected vehicle.", operation="vehicle_alerts"),
    _operational_tool(name="tescmd_vehicle_drivers", description="List drivers associated with the selected vehicle.", operation="vehicle_drivers"),
    _operational_tool(name="tescmd_vehicle_release_notes", description="Fetch firmware release notes for the selected vehicle.", operation="vehicle_release_notes"),
    _operational_tool(name="tescmd_vehicle_service", description="Fetch service data for the selected vehicle.", operation="vehicle_service"),
    _operational_tool(name="tescmd_vehicle_specs", description="Fetch specifications for the selected vehicle.", operation="vehicle_specs"),
    _operational_tool(name="tescmd_vehicle_subscriptions", description="Fetch subscription eligibility for the selected vehicle.", operation="vehicle_subscriptions"),
    _operational_tool(name="tescmd_vehicle_upgrades", description="Fetch upgrade eligibility for the selected vehicle.", operation="vehicle_upgrades"),
    _operational_tool(name="tescmd_vehicle_options", description="Fetch option codes for the selected vehicle.", operation="vehicle_options"),
    _operational_tool(name="tescmd_vehicle_warranty", description="Fetch warranty information relevant to the selected vehicle/account.", operation="vehicle_warranty"),
    _profile_tool(name="tescmd_vehicle_pricing", description="Fetch vehicle pricing information from the Fleet API pricing endpoint.", operation="vehicle_pricing", params=(ParamSpec("request", "Pricing request JSON object.", value_type="object", required=True),)),
    _operational_tool(name="tescmd_vehicle_enterprise_roles", description="Fetch enterprise roles for the selected vehicle.", operation="vehicle_enterprise_roles"),
    _operational_tool(name="tescmd_vehicle_enterprise_payer", description="Set enterprise payer information for the selected vehicle.", operation="vehicle_enterprise_payer", params=(ParamSpec("payer", "Enterprise payer request JSON object.", value_type="object", required=True), _CONFIRM_REQUIRED)),
    _profile_tool(name="tescmd_vehicle_fleet_status", description="Fetch fleet status across vehicles. This Tesla endpoint requires full VINs; pass vins if product responses redact VINs.", operation="vehicle_fleet_status", params=(ParamSpec("vins", "Optional array of full 17-character VINs for the Fleet Status endpoint. If omitted, VINs from vehicle_list are used when Tesla exposes them.", is_array=True, item_type="string"),)),
    _operational_tool(name="tescmd_vehicle_telemetry_config", description="Fetch fleet telemetry configuration for the selected vehicle.", operation="vehicle_telemetry_config"),
    _profile_tool(name="tescmd_vehicle_telemetry_create", description="Legacy/direct create or update fleet telemetry configuration using a JSON config payload.", operation="vehicle_telemetry_create", params=(ParamSpec("config", "Telemetry config JSON object.", value_type="object", required=True), ParamSpec("confirm", "Required acknowledgement for telemetry configuration changes.", value_type="boolean", required=True))),
    _profile_tool(name="tescmd_vehicle_telemetry_create_jws", description="Create or update fleet telemetry configuration using a prebuilt signed JWS token.", operation="vehicle_telemetry_create_jws", params=(ParamSpec("token", "Signed fleet telemetry configuration JWS token.", required=True), _CONFIRM_REQUIRED)),
    _operational_tool(name="tescmd_vehicle_telemetry_delete", description="Delete fleet telemetry configuration for the selected vehicle.", operation="vehicle_telemetry_delete", params=(ParamSpec("confirm", "Required confirmation flag.", value_type="boolean", required=True),)),
    _operational_tool(name="tescmd_vehicle_telemetry_errors", description="Fetch fleet telemetry errors for the selected vehicle.", operation="vehicle_telemetry_errors"),
    _status_read_tool(name="tescmd_security_status", description="Fetch current security-related vehicle state.", operation="security_status"),
    _status_read_tool(name="tescmd_software_status", description="Fetch software version and update status for the selected vehicle.", operation="software_status"),
    _operational_tool(name="tescmd_sharing_add_driver", description="Add a driver to the selected vehicle by email.", operation="sharing_add_driver", params=(ParamSpec("email", "Driver email address.", required=True), _CONFIRM_REQUIRED)),
    _operational_tool(name="tescmd_sharing_remove_driver", description="Remove a driver from the selected vehicle by share user ID.", operation="sharing_remove_driver", params=(ParamSpec("share_user_id", "Share user ID to remove.", value_type="integer", required=True), _CONFIRM_REQUIRED)),
    _operational_tool(name="tescmd_sharing_create_invite", description="Create a new sharing invite for the selected vehicle.", operation="sharing_create_invite", params=(_CONFIRM_REQUIRED,)),
    _operational_tool(name="tescmd_sharing_list_invites", description="List active sharing invites for the selected vehicle.", operation="sharing_list_invites"),
    _profile_tool(name="tescmd_sharing_redeem_invite", description="Redeem a Tesla sharing invite code.", operation="sharing_redeem_invite", params=(ParamSpec("code", "Invite code.", required=True), ParamSpec("confirm", "Required acknowledgement before redeeming an invite.", value_type="boolean", required=True))),
    _operational_tool(name="tescmd_sharing_revoke_invite", description="Revoke a sharing invite for the selected vehicle.", operation="sharing_revoke_invite", params=(ParamSpec("invite_id", "Invite identifier.", required=True), _CONFIRM_REQUIRED)),
    _profile_tool(name="tescmd_raw_get", description="Plugin-native escape hatch for raw Fleet API GET requests; requires confirmation because raw reads can expose broad account/vehicle data.", operation="raw_get", params=(ParamSpec("path", "Fleet API path starting with /api/...", required=True), ParamSpec("params", "Optional query params JSON object.", value_type="object"), _CONFIRM_REQUIRED)),
    _profile_tool(name="tescmd_raw_post", description="Plugin-native escape hatch for raw Fleet API POST requests.", operation="raw_post", params=(ParamSpec("path", "Fleet API path starting with /api/...", required=True), ParamSpec("body", "Optional request body JSON object.", value_type="object"), ParamSpec("confirm", "Required acknowledgement for raw POST side effects.", value_type="boolean", required=True))),
    _profile_tool(name="tescmd_raw_delete", description="Advanced escape hatch: send a DELETE to a relative /api/... Fleet API path.", operation="raw_delete", params=(ParamSpec("path", "Relative Fleet API path beginning with /api/. Absolute URLs and path traversal are rejected.", required=True), ParamSpec("body", "Optional JSON request body.", value_type="object"), _CONFIRM_REQUIRED)),
    _profile_tool(name="tescmd_navigation_place_search", description="Advertised navigation helper: search Google Places for Place IDs before using tescmd_navigation_waypoints. Requires google_maps_api_key in plugin config.json; does not contact Tesla or the vehicle.", operation="navigation_place_search", params=(ParamSpec("query", "Address, business, landmark, or place text to search in Google Places.", required=True), ParamSpec("limit", "Maximum candidates to return, 1 through 10.", value_type="integer", minimum=1, maximum=10, default=5))),
    _profile_tool(name="tescmd_help", description="Return an agent-oriented Tesla tool routing guide, readiness checks, and safe workflow hints.", operation="help"),
    _profile_tool(name="tescmd_cache_status", description="Inspect the plugin-native response cache.", operation="cache_status"),
    _profile_tool(name="tescmd_cache_clear", description="Clear plugin-native cache state if present.", operation="cache_clear", params=(_CONFIRM_REQUIRED,)),
    _profile_tool(name="tescmd_serve", description="Plugin-native compatibility tool explaining why no standalone tescmd server is needed inside Hermes.", operation="serve"),
    _profile_tool(name="tescmd_openclaw_bridge", description="Plugin-native compatibility tool for OpenClaw bridge workflows.", operation="openclaw_bridge"),
    _operational_tool(name="tescmd_vehicle_telemetry_stream", description="Plugin-native guidance for telemetry streaming workflows without starting a CLI dashboard inside Hermes.", operation="vehicle_telemetry_stream"),
)


def list_tool_specs() -> list[ToolSpec]:
    return list(_TOOL_SPECS)


SECRET_FIELD_NAMES = {"access_token", "refresh_token", "client_secret", "id_token", "authorization", "token", "code", "code_verifier", "google_maps_api_key", "api_key", "callback_url"}
_SECRET_TEXT_PATTERNS = (
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+"),
    re.compile(r"(?i)\b((?:access_token|refresh_token|client_secret|id_token|code|code_verifier|google_maps_api_key|api_key|callback_url)(?:=|:\s*))[^\s,&}]+"),
    re.compile(r'(?i)("(?:access_token|refresh_token|client_secret|id_token|code|code_verifier|google_maps_api_key|api_key|callback_url)"\s*:\s*")[^"]+"'),
)
_VIN_PATTERN = re.compile(r"\b[A-HJ-NPR-Z0-9]{17}\b")


def _redact_text(value: str) -> str:
    text = value
    for pattern in _SECRET_TEXT_PATTERNS:
        text = pattern.sub(lambda match: f"{match.group(1)}[REDACTED]", text)
    return _VIN_PATTERN.sub("[REDACTED]", text)


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            redacted_key = _redact_text(str(key)) if isinstance(key, str) else key
            key_text = str(redacted_key).lower()
            if key_text in SECRET_FIELD_NAMES or any(part in key_text for part in ("token", "secret", "authorization", "password", "pin", "code", "api_key")):
                redacted[redacted_key] = "[REDACTED]" if item is not None else None
            elif key_text in {"vin", "default_vin"}:
                redacted[redacted_key] = "[REDACTED]" if item is not None else None
            elif key_text == "private_key_path":
                redacted[redacted_key] = "[REDACTED]" if item is not None else None
            else:
                redacted[redacted_key] = _redact(item)
        return redacted
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        return _redact_text(value)
    return value


def _coerce_and_validate_param(param: ParamSpec, value: Any) -> Any:
    if value is None:
        return value
    try:
        if param.is_array:
            if not isinstance(value, list):
                raise ValueError(f"{param.name} must be an array")
            if param.item_type == "string" and any(not isinstance(item, str) for item in value):
                raise ValueError(f"{param.name} items must be strings")
            return value
        if param.value_type == "boolean":
            if not isinstance(value, bool):
                raise ValueError(f"{param.name} must be a boolean")
        elif param.value_type == "integer":
            if isinstance(value, bool):
                raise ValueError(f"{param.name} must be an integer")
            value = int(value)
        elif param.value_type == "number":
            if isinstance(value, bool):
                raise ValueError(f"{param.name} must be a number")
            value = float(value)
        elif param.value_type == "object":
            if not isinstance(value, (dict, str)):
                raise ValueError(f"{param.name} must be a JSON object")
        elif param.value_type == "string":
            if not isinstance(value, str):
                raise ValueError(f"{param.name} must be a string")
    except (TypeError, ValueError) as exc:
        raise client.TeslaAPIError(str(exc)) from exc
    if param.enum and value not in param.enum:
        raise client.TeslaAPIError(f"{param.name} must be one of: {', '.join(param.enum)}")
    if param.minimum is not None and value < param.minimum:
        raise client.TeslaAPIError(f"{param.name} must be >= {param.minimum}")
    if param.maximum is not None and value > param.maximum:
        raise client.TeslaAPIError(f"{param.name} must be <= {param.maximum}")
    return value


def _validate_args(spec: ToolSpec, args: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(args, dict):
        raise client.TeslaAPIError("Tool arguments must be a JSON object.")
    params = {param.name: param for param in spec.params}
    unknown = sorted(set(args) - set(params))
    if unknown:
        raise client.TeslaAPIError(f"Unsupported argument(s) for {spec.name}: {', '.join(unknown)}")
    validated = dict(args)
    for name, param in params.items():
        if param.required and name not in args:
            if name == "confirm":
                raise client.TeslaAPIError("confirm=true is required before this side-effecting operation will run.")
            raise client.TeslaAPIError(f"{name} is required.")
        if name in validated:
            validated[name] = _coerce_and_validate_param(param, validated[name])
    if validated.get("wake") and params.get("confirm") is not None and not validated.get("confirm"):
        raise client.TeslaAPIError("confirm=true is required before this side-effecting operation will run.")
    return validated


def _error_payload(exc: Exception, operation: str) -> dict[str, Any]:
    if isinstance(exc, client.TeslaAPIError):
        return {
            "ok": False,
            "operation": operation,
            "error": _redact(str(exc)),
            "status_code": exc.status_code,
            "payload": _redact(exc.payload),
        }
    return {
        "ok": False,
        "operation": operation,
        "error": _redact(str(exc)),
    }


def make_handler(spec: ToolSpec) -> Callable[[dict[str, Any]], str]:
    def _handler(args: dict[str, Any], **kwargs: Any) -> str:
        try:
            payload = tools.execute(spec, _validate_args(spec, args))
        except Exception as exc:  # pragma: no cover - verified by handler contract tests indirectly
            payload = _error_payload(exc, spec.operation)
        return json.dumps(_redact(payload))

    return _handler
