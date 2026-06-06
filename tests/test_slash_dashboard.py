from __future__ import annotations

import json
from pathlib import Path

import pytest

from hermes_tescmd_plugin import config, slash
from hermes_tescmd_plugin.dashboard import ensure_dashboard_installed
from hermes_tescmd_plugin.dashboard.plugin_api import (
    DefaultVehicleBody,
    QuickActionBody,
    _dashboard_display_payload,
    _overview_section_health,
    commands,
    overview,
    quick_action,
    read,
    set_default_vehicle,
    tools,
)


class FakeContext:
    def __init__(self) -> None:
        self.commands: list[dict] = []

    def register_command(self, **kwargs) -> None:
        self.commands.append(kwargs)


def test_slash_args_parse_key_values_arrays_and_bare_vin() -> None:
    args = slash.parse_args(
        "5YJ3E1EA7JF000001 endpoints=charge_state,drive_state wake=true region=na percent=80"
    )

    assert args["vin"] == "5YJ3E1EA7JF000001"
    assert args["endpoints"] == ["charge_state", "drive_state"]
    assert args["wake"] is True
    assert args["region"] == "na"
    assert args["percent"] == 80


def test_navigation_slash_commands_treat_bare_text_as_destination_or_query(
    monkeypatch,
) -> None:
    calls: list[tuple[str, str, dict | None, str]] = []

    def fake_run_tool(
        tool_name: str,
        raw_args: str = "",
        defaults: dict | None = None,
        *,
        positional_name: str = "vin",
    ) -> dict:
        calls.append((tool_name, raw_args, defaults, positional_name))
        return {"ok": True, "response": {"result": True}}

    monkeypatch.setattr(slash, "_run_tool", fake_run_tool)
    commands = slash.command_definitions()

    nav_output = commands["tescmd-nav"]["handler"](
        {"raw_args": "'123 Main St' confirm=true"}
    )
    search_output = commands["tescmd-nav-search"]["handler"](
        {"raw_args": "'coffee shop' limit=3"}
    )

    assert nav_output.startswith("/tescmd-nav: success")
    assert search_output.startswith("/tescmd-nav-search: success")
    assert calls == [
        (
            "tescmd_navigation_send",
            "'123 Main St' confirm=true",
            None,
            "destination",
        ),
        (
            "tescmd_navigation_place_search",
            "'coffee shop' limit=3",
            None,
            "query",
        ),
    ]


def test_navigation_positional_parsing_preserves_explicit_named_vin() -> None:
    assert slash.parse_args("'123 Main St'", positional_name="destination") == {
        "destination": "123 Main St"
    }
    assert slash.parse_args(
        "vin=5YJ3E1EA7JF000001 destination='123 Main St' confirm=true",
        positional_name="destination",
    ) == {
        "destination": "123 Main St",
        "vin": "5YJ3E1EA7JF000001",
        "confirm": True,
    }


def test_run_tool_navigation_keeps_explicit_vin_and_joins_unquoted_destination(
    monkeypatch,
) -> None:
    captured: dict = {}
    spec = slash.runtime.ToolSpec(
        name="tescmd_navigation_send",
        description="Send navigation destination.",
        operation="navigation_send",
    )

    def fake_handler(args: dict) -> str:
        captured.update(args)
        return json.dumps({"ok": True, "response": {"result": True}})

    monkeypatch.setattr(slash.runtime, "list_tool_specs", lambda: [spec])
    monkeypatch.setattr(slash.runtime, "make_handler", lambda _spec: fake_handler)

    result = slash._run_tool(
        "tescmd_navigation_send",
        "vin=5YJ3E1EA7JF000001 123 Main St confirm=true",
        positional_name="destination",
    )

    assert result["ok"] is True
    assert captured == {
        "vin": "5YJ3E1EA7JF000001",
        "destination": "123 Main St",
        "confirm": True,
    }


def test_registers_tescmd_slash_commands_and_status_handler(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    ctx = FakeContext()
    slash.register_commands(ctx)

    by_name = {command["name"]: command for command in ctx.commands}
    expected_commands = {
        "tescmd-status",
        "tescmd-auth-status",
        "tescmd-onboarding",
        "tescmd-key-show",
        "tescmd-key-validate",
        "tescmd-cache-status",
        "tescmd-cache-clear",
        "tescmd-audit-log",
        "tescmd-vehicles",
        "tescmd-vehicle-status",
        "tescmd-drive",
        "tescmd-closures",
        "tescmd-config",
        "tescmd-gui",
        "tescmd-security-status",
        "tescmd-software",
        "tescmd-nearby-chargers",
        "tescmd-alerts",
        "tescmd-release-notes",
        "tescmd-charge",
        "tescmd-climate",
        "tescmd-location",
        "tescmd-wake",
        "tescmd-flash",
        "tescmd-honk",
        "tescmd-lock",
        "tescmd-unlock",
        "tescmd-sentry",
        "tescmd-climate-start",
        "tescmd-climate-stop",
        "tescmd-set-temp",
        "tescmd-charge-start",
        "tescmd-charge-stop",
        "tescmd-charge-limit",
        "tescmd-charge-amps",
        "tescmd-charge-port-open",
        "tescmd-charge-port-close",
        "tescmd-frunk",
        "tescmd-trunk-open",
        "tescmd-trunk-close",
        "tescmd-window-vent",
        "tescmd-window-close",
        "tescmd-media-play",
        "tescmd-media-next",
        "tescmd-media-prev",
        "tescmd-media-volume-up",
        "tescmd-media-volume-down",
        "tescmd-media-volume-set",
        "tescmd-nav",
        "tescmd-nav-search",
        "tescmd-nav-waypoints",
    }
    assert expected_commands <= set(by_name)
    assert by_name["tescmd-honk"]["args_hint"] == "[vin] confirm=true"
    assert (
        by_name["tescmd-charge-limit"]["args_hint"] == "[vin] percent=80 confirm=true"
    )

    config.save_config(config.PluginConfig(profile="default", client_id="client-123"))
    output = by_name["tescmd-status"]["handler"]("")
    assert "Tesla Fleet status" in output
    assert "app_configured: True" in output


def test_status_slash_output_redacts_next_action_and_steps() -> None:
    output = slash._format_status(  # noqa: SLF001
        {
            "ok": True,
            "bootstrap": {
                "app_configured": True,
                "authenticated": False,
            },
            "next_action": "Complete OAuth for vehicle 5YJ3E1EA7JF000001",
            "next_steps": [
                "Open https://cars.example.com/callback?code=secret-token-123456&vin=5YJ3E1EA7JF000001",
                "Then run tescmd_auth_complete for Fleet vehicle 12345678901234567.",
            ],
        }
    )

    assert output.startswith("Tesla Fleet status")
    assert "vehicle …0001" in output
    assert "Fleet vehicle …4567" in output
    assert "5YJ3E1EA7JF000001" not in output
    assert "12345678901234567" not in output
    assert "secret-token-123456" not in output
    assert "{" not in output


def test_onboarding_slash_output_is_human_readable_and_read_only() -> None:
    output = slash._format_onboarding(  # noqa: SLF001
        {
            "ok": True,
            "phase": "auth_login",
            "next_action": "auth_login",
            "next_tool": "tescmd_auth_login",
            "docs_anchor": "docs/ONBOARDING.md#oauth-login",
            "missing_prerequisites": [
                "authenticated",
                "ready_for_vehicle_commands",
                "vehicle 5YJ3E1EA7JF000001",
            ],
            "next_steps": [
                "Run tescmd_auth_login before using vehicle 12345678901234567.",
                "Do not paste Bearer secret-token-123456 into chat.",
            ],
            "readiness": {
                "app_configured": True,
                "authenticated": False,
                "ready_for_vehicle_reads": False,
                "ready_for_vehicle_commands": False,
                "ready_for_signed_commands": False,
                "key_hosting_ready": True,
            },
            "redirect_uri": "https://cars.example.com/callback",
            "mutates_state": False,
        }
    )

    assert output.startswith("Tesla onboarding status")
    assert "- phase: auth_login" in output
    assert "- next tool: tescmd_auth_login" in output
    assert "Missing prerequisites:" in output
    assert "vehicle …0001" in output
    assert "Run tescmd_auth_login before using vehicle …4567." in output
    assert "Bearer [REDACTED]" in output
    assert "authenticated=no" in output
    assert "ready_for_vehicle_commands=no" in output
    assert "Safety: read-only" in output
    assert "5YJ3E1EA7JF000001" not in output
    assert "12345678901234567" not in output
    assert "secret-token-123456" not in output
    assert "{" not in output


def test_auth_status_slash_output_summarizes_scope_readiness() -> None:
    output = slash._format_auth_status(  # noqa: SLF001
        {
            "ok": True,
            "profile": "default",
            "configured": True,
            "authenticated": True,
            "pending_login": False,
            "region": "na",
            "domain": "cars.example.com",
            "default_vin": "5YJ3E1EA7JF000001",
            "configured_user_scopes": [
                "openid",
                "offline_access",
                "vehicle_device_data",
                "vehicle_cmds",
            ],
            "vehicle_command_key": {
                "private_key_path": "/tmp/hermes/plugins/tescmd/private.pem",
                "public_key_path": "/tmp/hermes/plugins/tescmd/public.pem",
            },
            "bootstrap": {
                "scope_readiness": {
                    "grant_scope_source": "token",
                    "missing_granted_user_scopes": ["vehicle_device_data"],
                    "capabilities": {
                        "vehicle_reads": {
                            "ready": False,
                            "missing_scopes": ["vehicle_device_data"],
                        },
                        "vehicle_commands": {
                            "ready": True,
                            "missing_scopes": [],
                        },
                    },
                }
            },
        }
    )

    assert output.startswith("Tesla auth status")
    assert "authenticated: yes" in output
    assert "pending_login: no" in output
    assert "default vehicle: …0001" in output
    assert "scope source: token" in output
    assert "missing granted scopes: vehicle_device_data" in output
    assert "vehicle_reads=missing (needs vehicle_device_data)" in output
    assert "vehicle_commands=ready" in output
    assert "Configured user scopes: openid, offline_access" in output
    assert "Vehicle-command key paths: private=configured, public=configured" in output
    assert "5YJ3E1EA7JF000001" not in output
    assert "/tmp/hermes" not in output
    assert "{" not in output


def test_auth_status_slash_command_uses_human_formatter(monkeypatch) -> None:
    def fake_run_tool(
        tool_name: str, raw_args: str = "", defaults=None, **kwargs
    ) -> dict:
        assert tool_name == "tescmd_auth_status"
        return {
            "ok": True,
            "configured": True,
            "authenticated": True,
            "pending_login": False,
            "scopes": ["openid"],
            "bootstrap": {
                "scope_readiness": {
                    "grant_scope_source": "token",
                    "missing_granted_user_scopes": [],
                    "capabilities": {
                        "vehicle_reads": {"ready": True, "missing_scopes": []}
                    },
                }
            },
        }

    monkeypatch.setattr(slash, "_run_tool", fake_run_tool)

    output = slash.command_definitions()["tescmd-auth-status"]["handler"](
        {"raw_args": ""}
    )

    assert output.startswith("Tesla auth status")
    assert "missing granted scopes: none detected" in output
    assert "vehicle_reads=ready" in output
    assert "command accepted by Tesla Fleet API" not in output
    assert "{" not in output


def test_side_effect_slash_command_requires_confirm_before_network(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    config.save_config(
        config.PluginConfig(
            profile="default", client_id="client-123", default_vin="5YJ3E1EA7JF000001"
        )
    )
    config.save_auth_state(
        config.AuthState(profile="default", access_token="token", region="na")
    )

    calls: list[tuple] = []

    def fail_if_called(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError(
            "vehicle command should not be called without confirm=true"
        )

    monkeypatch.setattr(
        "hermes_tescmd_plugin.client.TeslaFleetClient.vehicle_command", fail_if_called
    )
    ctx = FakeContext()
    slash.register_commands(ctx)
    by_name = {command["name"]: command for command in ctx.commands}

    output = by_name["tescmd-honk"]["handler"]("")

    assert "/tescmd-honk: failed" in output
    assert "Reason: confirm=true is required" in output
    assert "Try: /tescmd-honk confirm=true" in output
    assert "real-world vehicle side effect" in output
    assert "{" not in output
    assert calls == []


def test_slash_command_failure_redacts_sensitive_context() -> None:
    output = slash._format_command(
        "tescmd-lock",
        {
            "ok": False,
            "error": (
                "Tesla rejected VIN 5YJ3E1EA7JF000001 for fleet id "
                "12345678901234567 with Bearer secret-token-123456"
            ),
            "retry_command": "/tescmd-lock 5YJ3E1EA7JF000001 confirm=true",
            "next_action": "Check vehicle 12345678901234567 enrollment.",
            "status_code": 403,
        },
    )

    assert "/tescmd-lock: failed" in output
    assert "…0001" in output
    assert "…4567" in output
    assert "Bearer [REDACTED]" in output
    assert "5YJ3E1EA7JF000001" not in output
    assert "12345678901234567" not in output
    assert "secret-token-123456" not in output
    assert "Try: /tescmd-lock …0001 confirm=true" in output


def test_side_effect_slash_command_success_is_human_readable() -> None:
    output = slash._format_command(
        "tescmd-honk",
        {
            "ok": True,
            "profile": "default",
            "region": "na",
            "vin": "5YJ3E1EA7JF000001",
            "response": {"result": True},
        },
    )

    assert output.startswith("/tescmd-honk: success")
    assert "Vehicle: …0001" in output
    assert "5YJ3E1EA7JF000001" not in output
    assert "Result: yes" in output
    assert "{" not in output


def test_slash_command_success_redacts_named_vehicle_identifier() -> None:
    output = slash._format_command(
        "tescmd-lock",
        {
            "ok": True,
            "vehicle": {
                "display_name": "seaQuest",
                "id_s": "12345678901234567",
            },
            "response": {"result": True},
        },
    )

    assert "Vehicle: seaQuest (…4567)" in output
    assert "12345678901234567" not in output
    assert "{" not in output


def test_dashboard_visible_vehicle_identity_helpers_redact_identifiers() -> None:
    asset = Path("src/hermes_tescmd_plugin/dashboard/assets/index.js").read_text()

    assert "function redactVisibleIdentifierText(value)" in asset
    assert "function sanitizeDashboardText(value, fallback)" in asset
    assert "function dashboardErrorMessage(err)" in asset
    assert "Bearer [REDACTED]" in asset
    assert "[A-HJ-NPR-Z0-9]{17}" in asset
    assert "\\d{12,20}" in asset
    assert "access_token|refresh_token|id_token|client_secret|token" in asset
    assert "[coordinates redacted]" in asset
    assert "destination|address|query|place_id|place_ids" in asset

    picker_body = asset.split("function vehiclePickerLabel", 1)[1].split(
        "function vehicleIdentitySummary", 1
    )[0]
    identity_body = asset.split("function vehicleIdentitySummary", 1)[1].split(
        "function VehicleIdentityCard", 1
    )[0]

    assert "visibleVehicleText(vehicle.display_name" in picker_body
    assert "visibleVehicleText(vehicle.state" in picker_body
    assert "vehicleModelHint(vehicle)" in picker_body
    assert "visibleVehicleText(vehicle.display_name" in identity_body
    assert "visibleVehicleText(vehicle.state" in identity_body


def test_dashboard_navigation_actions_require_targets_and_clear_route_fields() -> None:
    asset = Path("src/hermes_tescmd_plugin/dashboard/assets/index.js").read_text()

    assert "function NavigationGuardPanel" in asset
    assert (
        "Navigation buttons stay unavailable until their required destination fields are present"
        in asset
    )
    assert "After a navigation action is sent, route fields are cleared" in asset
    assert "actionDisabledReason(action)" in asset
    assert "const disabledReason = actionDisabledReason(action);" in asset
    assert "Enter a destination before sending navigation." in asset
    assert "Enter both latitude and longitude before sending GPS navigation." in asset
    assert "Enter at least one place ID before sending waypoints." in asset
    assert "Physical actions are locked again." in asset
    assert "body.destination = destination.trim()" in asset
    assert "function clearNavigationFields(action)" in asset
    assert 'setDestination("")' in asset
    assert 'setLat("")' in asset
    assert 'setLon("")' in asset
    assert 'setPlaceIds("")' in asset
    assert "if (navigationAction) clearNavigationFields(action);" in asset
    assert "route fields were cleared and physical actions are locked again" in asset
    assert (
        "route fields were cleared and confirmation is locked off after the request"
        in asset
    )


def test_dashboard_user_visible_errors_are_sanitized_before_rendering() -> None:
    asset = Path("src/hermes_tescmd_plugin/dashboard/assets/index.js").read_text()

    assert "setError(dashboardErrorMessage(err));" in asset
    assert "setError(String((err && err.message) || err));" not in asset
    assert "setLastActionStatus(sanitizeDashboardText(payload.message" in asset
    assert "Tesla dashboard request failed." in asset
    assert "code|state|access_token|refresh_token|id_token|client_secret|token" in asset
    assert "lat(?:itude)?|lon(?:gitude)?|lng" in asset
    assert "destination|address|query|place_id|place_ids" in asset
    error_card_body = asset.split('className: "tescmd-error-card"', 1)[0]
    assert "dashboardErrorMessage(err)" in error_card_body


def test_vehicle_list_redacts_identifiers() -> None:
    output = slash._format_vehicles(
        {
            "ok": True,
            "vehicles": [
                {
                    "display_name": "Cybertruck",
                    "state": "online",
                    "vin": "5YJ3E1EA7JF000001",
                }
            ],
        }
    )

    assert "Tesla vehicles: 1" in output
    assert "Cybertruck — online — …0001" in output
    assert "5YJ3E1EA7JF000001" not in output


def test_vehicle_list_includes_safe_model_hints_for_target_selection() -> None:
    output = slash._format_vehicles(
        {
            "ok": True,
            "vehicles": [
                {
                    "display_name": "seaQuest",
                    "state": "asleep",
                    "id_s": "12345678901234567",
                    "vehicle_config": {
                        "car_type": "cybertruck",
                        "trim_badging": "AWD",
                    },
                },
                {
                    "display_name": "Roadtrip 5YJ3E1EA7JF000001",
                    "state": "online",
                    "vin": "5YJ3E1EA7JF000001",
                    "car_type": "models",
                    "trim": "12345678901234567",
                },
            ],
        }
    )

    assert "seaQuest — asleep — …4567 — type=cybertruck, trim=AWD" in output
    assert "Roadtrip …0001 — online — …0001 — type=models, trim=…4567" in output
    assert "5YJ3E1EA7JF000001" not in output
    assert "12345678901234567" not in output
    assert "{" not in output


def test_vehicle_list_redacts_embedded_identifiers_in_names_and_raw_entries() -> None:
    output = slash._format_vehicles(
        {
            "ok": True,
            "vehicles": [
                {
                    "display_name": "Loaner 5YJ3E1EA7JF000001",
                    "state": "linked to fleet 12345678901234567",
                    "id_s": "12345678901234567",
                },
                "raw vehicle 5YJ3E1EA7JF000002 with Bearer secret-token-123456",
            ],
        }
    )

    assert "Loaner …0001 — linked to fleet …4567 — …4567" in output
    assert "raw vehicle …0002 with Bearer [REDACTED]" in output
    assert "5YJ3E1EA7JF000001" not in output
    assert "5YJ3E1EA7JF000002" not in output
    assert "12345678901234567" not in output
    assert "secret-token-123456" not in output


def test_success_vehicle_hint_redacts_identifier_in_vehicle_name() -> None:
    output = slash._format_command(
        "tescmd-security-status",
        {
            "ok": True,
            "vehicle": {
                "display_name": "Cybertruck 5YJ3E1EA7JF000001",
                "id_s": "12345678901234567",
            },
            "response": {"result": True},
        },
    )

    assert "Vehicle: Cybertruck …0001 (…4567)" in output
    assert "5YJ3E1EA7JF000001" not in output
    assert "12345678901234567" not in output


def test_status_failure_is_human_readable_and_redacted() -> None:
    output = slash._format_status(
        {
            "ok": False,
            "error": (
                "Tesla setup failed for VIN 5YJ3E1EA7JF000001 with "
                "Bearer setup-token-123456"
            ),
            "next_action": "Re-check vehicle 12345678901234567 enrollment.",
            "status_code": 401,
        }
    )

    assert output.startswith("/tescmd-status: failed")
    assert "Reason: Tesla setup failed for VIN …0001" in output
    assert "Bearer [REDACTED]" in output
    assert "Next action: Re-check vehicle …4567 enrollment." in output
    assert "Tesla API status: 401" in output
    assert "5YJ3E1EA7JF000001" not in output
    assert "12345678901234567" not in output
    assert "setup-token-123456" not in output
    assert "{" not in output


def test_vehicle_list_failure_is_human_readable_and_redacted() -> None:
    output = slash._format_vehicles(
        {
            "ok": False,
            "error": "Fleet API rejected vehicle 5YJ3E1EA7JF000001",
            "retry_command": "/tescmd-vehicles profile=default",
            "status_code": 403,
        }
    )

    assert output.startswith("/tescmd-vehicles: failed")
    assert "Reason: Fleet API rejected vehicle …0001" in output
    assert "Try: /tescmd-vehicles profile=default" in output
    assert "Tesla API status: 403" in output
    assert "5YJ3E1EA7JF000001" not in output
    assert "{" not in output


def test_audit_log_slash_output_is_human_readable_and_redacted() -> None:
    output = slash._format_audit_log(  # noqa: SLF001
        {
            "ok": True,
            "path": "/tmp/hermes/plugins/hermes-tescmd-plugin/audit/commands.jsonl",
            "events": [
                {
                    "tool": "tescmd_security_lock",
                    "stage": "result",
                    "ok": False,
                    "command_name": "door_lock",
                    "target": {"provided": True, "suffix": "0001"},
                    "confirm": True,
                    "wake": True,
                    "status_code": 408,
                    "error": "Vehicle 5YJ3E1EA7JF000001 rejected Bearer secret-token-123456",
                    "args": {"vin": "[REDACTED]"},
                }
            ],
        }
    )

    assert output.startswith("Tesla command audit log: 1 event(s)")
    assert "tescmd_security_lock result failed" in output
    assert "command=door_lock" in output
    assert "target=…0001" in output
    assert "confirm=yes" in output
    assert "wake=yes" in output
    assert "status=408" in output
    assert "Vehicle …0001 rejected Bearer [REDACTED]" in output
    assert "5YJ3E1EA7JF000001" not in output
    assert "secret-token-123456" not in output
    assert "commands.jsonl" not in output
    assert "{" not in output


def test_audit_log_slash_output_handles_empty_log() -> None:
    output = slash._format_audit_log({"ok": True, "events": []})  # noqa: SLF001

    assert output == (
        "Tesla command audit log: 0 event(s)\n"
        "No wake or vehicle-control attempts are recorded yet."
    )


def test_read_slash_command_success_summarizes_vehicle_data() -> None:
    output = slash._format_command(
        "tescmd-charge",
        {
            "ok": True,
            "vin": "5YJ3E1EA7JF000001",
            "data": {
                "charge_state": {
                    "battery_level": 65,
                    "charging_state": "Disconnected",
                    "charge_limit_soc": 80,
                }
            },
            "cache": {"hit": True},
        },
    )

    assert output.startswith("/tescmd-charge: success")
    assert "Charge: 65%, Disconnected, limit 80%" in output
    assert "Source: cached vehicle data" in output
    assert "{" not in output


def test_charge_slash_summary_includes_operator_details_without_location_or_ids() -> (
    None
):
    output = slash._format_command(
        "tescmd-charge",
        {
            "ok": True,
            "vin": "5YJ3E1EA7JF000001",
            "data": {
                "charge_state": {
                    "battery_level": 44,
                    "charging_state": "Charging",
                    "charge_limit_soc": 85,
                    "battery_range": 126.5,
                    "charger_power": 7,
                    "charger_actual_current": 32,
                    "time_to_full_charge": 2.25,
                    "conn_charge_cable": "SAE 5YJ3E1EA7JF000002",
                    "charge_port_door_open": True,
                    "latitude": 37.7749295,
                    "longitude": -122.4194155,
                }
            },
        },
    )

    assert output.startswith("/tescmd-charge: success")
    assert (
        "Charge: 44%, Charging, limit 85%, range 126.5 mi, 7 kW, "
        "32 A, 2.25 h to full, cable SAE …0002, port open"
    ) in output
    assert "5YJ3E1EA7JF000001" not in output
    assert "5YJ3E1EA7JF000002" not in output
    assert "37.7749295" not in output
    assert "-122.4194155" not in output
    assert "{" not in output


def test_charge_action_summary_includes_safe_requested_value() -> None:
    output = slash._format_command(
        "tescmd-charge-limit",
        {
            "ok": True,
            "profile": "default",
            "region": "na",
            "vin": "5YJ3E1EA7JF000001",
            "command": "set_charge_limit",
            "request": {"percent": 85, "confirm": True, "vin": "5YJ3E1EA7JF000001"},
            "response": {"result": True},
        },
    )

    assert output.startswith("/tescmd-charge-limit: success")
    assert "Charging action: set charge limit to 85%." in output
    assert "Result: Tesla accepted the charging command." in output
    assert "confirm" not in output
    assert "5YJ3E1EA7JF000001" not in output
    assert "{" not in output


def test_charge_action_slash_handler_exposes_only_safe_request_details(
    monkeypatch,
) -> None:
    def fake_run_tool(
        tool_name, raw_args="", defaults=None, *, positional_name="vin", expose_args=()
    ):
        assert tool_name == "tescmd_charge_limit"
        assert raw_args == "5YJ3E1EA7JF000001 percent=85 confirm=true"
        assert expose_args == ("percent",)
        return {
            "ok": True,
            "vin": "…0001",
            "command": "set_charge_limit",
            "request": {"percent": 85},
            "response": {"result": True},
        }

    monkeypatch.setattr(slash, "_run_tool", fake_run_tool)

    output = slash.command_definitions()["tescmd-charge-limit"]["handler"](
        {"raw_args": "5YJ3E1EA7JF000001 percent=85 confirm=true"}
    )

    assert "Charging action: set charge limit to 85%." in output
    assert "Result: Tesla accepted the charging command." in output
    assert "confirm" not in output
    assert "5YJ3E1EA7JF000001" not in output
    assert "{" not in output


def test_media_action_summary_is_human_readable() -> None:
    output = slash._format_command(
        "tescmd-media-next",
        {
            "ok": True,
            "vin": "5YJ3E1EA7JF000001",
            "request": {"confirm": True, "vin": "5YJ3E1EA7JF000001"},
            "response": {"result": True},
        },
    )

    assert output.startswith("/tescmd-media-next: success")
    assert "Media action: skip to the next media track." in output
    assert "Result: Tesla accepted the media command." in output
    assert "Result: yes" not in output
    assert "confirm" not in output
    assert "5YJ3E1EA7JF000001" not in output
    assert "{" not in output


def test_media_volume_set_slash_handler_exposes_only_safe_request_details(
    monkeypatch,
) -> None:
    def fake_run_tool(
        tool_name, raw_args="", defaults=None, *, positional_name="vin", expose_args=()
    ):
        assert tool_name == "tescmd_media_volume_set"
        assert raw_args == "5YJ3E1EA7JF000001 volume=4 confirm=true"
        assert expose_args == ("volume",)
        return {
            "ok": True,
            "vin": "…0001",
            "request": {"volume": 4},
            "response": {"result": True},
        }

    monkeypatch.setattr(slash, "_run_tool", fake_run_tool)

    output = slash.command_definitions()["tescmd-media-volume-set"]["handler"](
        {"raw_args": "5YJ3E1EA7JF000001 volume=4 confirm=true"}
    )

    assert "Media action: set media volume to 4." in output
    assert "Result: Tesla accepted the media command." in output
    assert "confirm" not in output
    assert "5YJ3E1EA7JF000001" not in output
    assert "{" not in output


def test_body_action_summary_is_human_readable() -> None:
    output = slash._format_command(
        "tescmd-window-close",
        {
            "ok": True,
            "vin": "5YJ3E1EA7JF000001",
            "request": {"confirm": True, "vin": "5YJ3E1EA7JF000001"},
            "response": {"result": True},
        },
    )

    assert output.startswith("/tescmd-window-close: success")
    assert "Body action: close the windows." in output
    assert "Result: Tesla accepted the body command." in output
    assert "Result: yes" not in output
    assert "confirm" not in output
    assert "5YJ3E1EA7JF000001" not in output
    assert "{" not in output


def test_navigation_action_summary_redacts_destination() -> None:
    output = slash._format_command(
        "tescmd-nav",
        {
            "ok": True,
            "vin": "5YJ3E1EA7JF000001",
            "request": {
                "destination": "123 Main St, Springfield",
                "confirm": True,
            },
            "response": {"result": True},
        },
    )

    assert output.startswith("/tescmd-nav: success")
    assert (
        "Navigation action: send a navigation destination (destination redacted)."
        in output
    )
    assert "Result: Tesla accepted the navigation command." in output
    assert "123 Main St" not in output
    assert "confirm" not in output
    assert "5YJ3E1EA7JF000001" not in output
    assert "Result: yes" not in output
    assert "{" not in output


def test_navigation_search_summary_redacts_place_ids_and_coordinates() -> None:
    output = slash._format_command(
        "tescmd-nav-search",
        {
            "ok": True,
            "response": {
                "places": [
                    {
                        "display_name": {"text": "Coffee & Charge"},
                        "place_id": "ChIJsecretPlaceId123",
                        "latitude": 37.7749295,
                        "longitude": -122.4194155,
                    },
                    {"formatted_address": "456 Example Ave"},
                ]
            },
        },
    )

    assert output.startswith("/tescmd-nav-search: success")
    assert "Navigation search: 2 place candidate(s) returned." in output
    assert "Top places: #1 Coffee & Charge; #2 456 Example Ave" in output
    assert "place_ids=..." in output
    assert "ChIJsecretPlaceId123" not in output
    assert "37.7749295" not in output
    assert "-122.4194155" not in output
    assert "{" not in output


def test_release_notes_slash_summary_is_human_readable_and_privacy_safe() -> None:
    output = slash._format_command(
        "tescmd-release-notes",
        {
            "ok": True,
            "vin": "5YJ3E1EA7JF000001",
            "response": {
                "version": "2026.14.3",
                "status": "available",
                "release_notes": [
                    {
                        "title": "Improved Autopark for vehicle 5YJ3E1EA7JF000002",
                        "body": "Park near 123 Main St at 37.7749295,-122.4194155",
                    },
                    {
                        "heading": "Charge on Solar",
                        "url": "https://cars.example.com/callback?code=secret-token-123456",
                    },
                ],
            },
        },
    )

    assert output.startswith("/tescmd-release-notes: success")
    assert "Release notes: 2 note(s) — version 2026.14.3, status available" in output
    assert (
        "Top notes: #1 Improved Autopark for vehicle …0002; #2 Charge on Solar"
        in output
    )
    assert "Result: command accepted" not in output
    assert "5YJ3E1EA7JF000001" not in output
    assert "5YJ3E1EA7JF000002" not in output
    assert "123 Main St" not in output
    assert "37.7749295" not in output
    assert "secret-token-123456" not in output
    assert "{" not in output


def test_climate_slash_summary_is_human_readable_and_privacy_safe() -> None:
    output = slash._format_command(
        "tescmd-climate",
        {
            "ok": True,
            "vin": "5YJ3E1EA7JF000001",
            "data": {
                "climate_state": {
                    "is_climate_on": True,
                    "inside_temp": 21.5,
                    "outside_temp": 8,
                    "driver_temp_setting": 22,
                    "passenger_temp_setting": 22.5,
                    "fan_status": 3,
                    "is_front_defroster_on": True,
                    "is_rear_defroster_on": False,
                    "steering_wheel_heater": True,
                    "seat_heater_left": 2,
                    "seat_heater_right": 0,
                    "latitude": 37.7749295,
                    "longitude": -122.4194155,
                }
            },
        },
    )

    assert output.startswith("/tescmd-climate: success")
    assert (
        "Climate: on, inside 21.5°, outside 8°, driver target 22°, "
        "passenger target 22.5°, fan 3, front defroster on, "
        "steering heat on, seat heat driver"
    ) in output
    assert "Result: command accepted" not in output
    assert "5YJ3E1EA7JF000001" not in output
    assert "37.7749295" not in output
    assert "-122.4194155" not in output
    assert "{" not in output


def test_climate_set_temp_action_summary_uses_exposed_request(monkeypatch) -> None:
    captured: dict = {}
    spec = slash.runtime.ToolSpec(
        name="tescmd_climate_set_temps",
        description="Set climate temperatures.",
        operation="vehicle_command",
    )

    def fake_handler(args: dict) -> str:
        captured.update(args)
        return json.dumps({"ok": True, "response": {"result": True}})

    monkeypatch.setattr(slash.runtime, "list_tool_specs", lambda: [spec])
    monkeypatch.setattr(slash.runtime, "make_handler", lambda _spec: fake_handler)

    output = slash.command_definitions()["tescmd-set-temp"]["handler"](
        {"raw_args": "5YJ3E1EA7JF000001 driver_temp=70 passenger_temp=71 confirm=true"}
    )

    assert captured == {
        "vin": "5YJ3E1EA7JF000001",
        "driver_temp": 70,
        "passenger_temp": 71,
        "confirm": True,
    }
    assert (
        "Climate action: set cabin targets to driver 70° and passenger 71°." in output
    )
    assert "Result: Tesla accepted the climate command." in output
    assert "confirm" not in output
    assert "5YJ3E1EA7JF000001" not in output
    assert "{" not in output


def test_drive_slash_summary_redacts_precise_coordinates() -> None:
    output = slash._format_command(
        "tescmd-drive",
        {
            "ok": True,
            "vin": "5YJ3E1EA7JF000001",
            "data": {
                "drive_state": {
                    "shift_state": "D",
                    "speed": 0,
                    "heading": 271,
                    "power": -2,
                    "latitude": 37.7749295,
                    "longitude": -122.4194155,
                    "native_latitude": 37.7749,
                    "native_longitude": -122.4194,
                }
            },
        },
    )

    assert (
        "Drive: shift drive, speed 0 mph, heading 271°, power -2 kW, "
        "native location available (coordinates redacted)"
    ) in output
    assert "Location: available (coordinates redacted)" in output
    assert "Result: command accepted" not in output
    assert "37.7749295" not in output
    assert "-122.4194155" not in output
    assert "37.7749" not in output
    assert "-122.4194" not in output
    assert "5YJ3E1EA7JF000001" not in output
    assert "{" not in output


def test_location_slash_summary_includes_safe_drive_context_only() -> None:
    output = slash._format_command(
        "tescmd-location",
        {
            "ok": True,
            "vin": "5YJ3E1EA7JF000001",
            "data": {
                "location_data": {
                    "shift_state": "P",
                    "speed": 0,
                    "heading": 0,
                    "latitude": 34.052235,
                    "longitude": -118.243683,
                }
            },
        },
    )

    assert "Drive: shift parked, speed 0 mph, heading 0°" in output
    assert "Location: available (coordinates redacted)" in output
    assert "Result: command accepted" not in output
    assert "34.052235" not in output
    assert "-118.243683" not in output
    assert "5YJ3E1EA7JF000001" not in output
    assert "{" not in output


def test_location_slash_summary_treats_zero_coordinates_as_present() -> None:
    output = slash._format_command(
        "tescmd-location",
        {
            "ok": True,
            "data": {
                "location_data": {
                    "shift_state": "P",
                    "speed": 0,
                    "heading": 0,
                    "latitude": 0,
                    "longitude": 0,
                }
            },
        },
    )

    assert "Drive: shift parked, speed 0 mph, heading 0°" in output
    assert "Location: available (coordinates redacted)" in output
    assert "Result: command accepted" not in output
    assert "{" not in output


def test_nearby_chargers_slash_summary_is_human_readable_and_location_safe() -> None:
    output = slash._format_command(
        "tescmd-nearby-chargers",
        {
            "ok": True,
            "vin": "5YJ3E1EA7JF000001",
            "sites": {
                "superchargers": [
                    {
                        "name": "Downtown Supercharger 5YJ3E1EA7JF000002",
                        "available_stalls": 4,
                        "total_stalls": 8,
                        "distance_miles": 3.2,
                        "latitude": 37.7749295,
                        "longitude": -122.4194155,
                    },
                    {"name": "Mall Supercharger", "available_stalls": 0},
                ],
                "destination_charging": [
                    {
                        "name": "Hotel destination charger",
                        "distance_km": 12,
                        "lat": 37.1,
                        "lng": -122.1,
                    }
                ],
            },
        },
    )

    assert output.startswith("/tescmd-nearby-chargers: success")
    assert "Nearby chargers: 2 Supercharger(s), 1 destination charger(s)" in output
    assert (
        "Top Superchargers: #1 Downtown Supercharger …0002 (4/8 stalls, 3.2 mi); #2 Mall Supercharger (0 stalls available)"
        in output
    )
    assert (
        "Navigation: use tescmd_navigation_supercharger order=N confirm=true "
        "with the matching Supercharger number."
    ) in output
    assert "Top destination chargers: Hotel destination charger (12 km)" in output
    assert "Result: command accepted" not in output
    assert "5YJ3E1EA7JF000001" not in output
    assert "5YJ3E1EA7JF000002" not in output
    assert "37.7749295" not in output
    assert "-122.4194155" not in output
    assert "37.1" not in output
    assert "-122.1" not in output
    assert "{" not in output


def test_security_status_slash_summary_reports_lock_and_sentry_privately() -> None:
    output = slash._format_command(
        "tescmd-security-status",
        {
            "ok": True,
            "vin": "5YJ3E1EA7JF000001",
            "data": {
                "vehicle_state": {
                    "locked": "locked",
                    "sentry_mode": "off",
                    "valet_mode": False,
                    "latitude": 37.7749295,
                    "longitude": -122.4194155,
                }
            },
        },
    )

    assert output.startswith("/tescmd-security-status: success")
    assert "Security: locked, Sentry off" in output
    assert "Result: command accepted" not in output
    assert "valet off" not in output
    assert "5YJ3E1EA7JF000001" not in output
    assert "37.7749295" not in output
    assert "-122.4194155" not in output
    assert "{" not in output


def test_closures_slash_summary_reports_open_items_privately() -> None:
    output = slash._format_command(
        "tescmd-closures",
        {
            "ok": True,
            "vehicle": {
                "display_name": "Cybertruck 5YJ3E1EA7JF000001",
                "id_s": "12345678901234567",
            },
            "data": {
                "vehicle_state": {
                    "locked": False,
                    "sentry_mode": True,
                    "df": 0,
                    "pf": 1,
                    "dr": 0,
                    "pr": 0,
                    "fd_window": 0,
                    "fp_window": 0,
                    "rd_window": 1,
                    "rp_window": 0,
                    "ft": 0,
                    "rt": 0,
                    "charge_port_door_open": True,
                }
            },
        },
    )

    assert output.startswith("/tescmd-closures: success")
    assert "Vehicle: Cybertruck …0001 (…4567)" in output
    assert "Security: unlocked, Sentry on" in output
    assert (
        "Closures: open: passenger door, rear-left window, charge port, "
        "8 reported closed"
    ) in output
    assert "Result: command accepted" not in output
    assert "5YJ3E1EA7JF000001" not in output
    assert "12345678901234567" not in output
    assert "{" not in output


def test_closures_slash_summary_reports_string_states_without_truthiness_noise() -> (
    None
):
    output = slash._format_command(
        "tescmd-closures",
        {
            "ok": True,
            "data": {
                "vehicle_state": {
                    "locked": "unlocked",
                    "sentry_mode": "off",
                    "df": "closed",
                    "pf": "open",
                    "dr": "closed",
                    "pr": "closed",
                    "fd_window": "closed",
                    "fp_window": "closed",
                    "rd_window": "opened",
                    "rp_window": "closed",
                    "ft": "closed",
                    "rt": "closed",
                    "charge_port_door_open": "closed",
                }
            },
        },
    )

    assert "Security: unlocked, Sentry off" in output
    assert (
        "Closures: open: passenger door, rear-left window, 9 reported closed" in output
    )
    assert "driver door" not in output
    assert "charge port" not in output
    assert "{" not in output


def test_software_slash_summary_reports_version_and_update_privately() -> None:
    output = slash._format_command(
        "tescmd-software",
        {
            "ok": True,
            "vin": "5YJ3E1EA7JF000001",
            "vehicle": {"display_name": "seaQuest"},
            "software": {
                "car_version": "2026.20.1 5YJ3E1EA7JF000001",
                "software_update": {
                    "status": "downloading",
                    "version": "2026.24.1",
                    "download_perc": 42,
                    "install_perc": 0,
                    "expected_duration_sec": 1800,
                },
            },
            "data": {
                "vehicle_state": {
                    "latitude": 37.7749295,
                    "longitude": -122.4194155,
                }
            },
        },
    )

    assert output.startswith("/tescmd-software: success")
    assert (
        "Software: version 2026.20.1 …0001, update downloading, "
        "to 2026.24.1, download 42%, install 0%, expected 1800s"
    ) in output
    assert "Result: command accepted" not in output
    assert "5YJ3E1EA7JF000001" not in output
    assert "37.7749295" not in output
    assert "-122.4194155" not in output
    assert "{" not in output


def test_alerts_slash_summary_reports_top_alerts_without_ids_or_raw_json() -> None:
    output = slash._format_command(
        "tescmd-alerts",
        {
            "ok": True,
            "vin": "5YJ3E1EA7JF000001",
            "alerts": [
                {
                    "severity": "critical",
                    "message": "Tire pressure low on 5YJ3E1EA7JF000001",
                    "latitude": 37.7749295,
                },
                {"level": "info", "description": "Software update ready"},
            ],
        },
    )

    assert output.startswith("/tescmd-alerts: success")
    assert "Alerts: 2 recent alert(s)" in output
    assert (
        "Top alerts: critical: Tire pressure low on …0001; info: Software update ready"
    ) in output
    assert "Result: command accepted" not in output
    assert "5YJ3E1EA7JF000001" not in output
    assert "37.7749295" not in output
    assert "{" not in output


def test_success_result_redacts_sensitive_identifiers() -> None:
    output = slash._format_command(
        "tescmd-nav",
        {
            "ok": True,
            "vin": "5YJ3E1EA7JF000001",
            "response": {
                "message": (
                    "sent destination for 5YJ3E1EA7JF000001 via "
                    "Bearer nav-token-123456789"
                )
            },
        },
    )

    assert "Result: sent destination for …0001 via Bearer [REDACTED]" in output
    assert "5YJ3E1EA7JF000001" not in output
    assert "nav-token-123456789" not in output
    assert "{" not in output


def test_dashboard_redacts_visible_debug_payload_privacy_fields() -> None:
    payload = {
        "vin": "5YJ3E1EA7JF000001",
        "vins": ["5YJ3E1EA7JF000002"],
        "default_vin": "5YJ3E1EA7JF000003",
        "target_vehicle": "12345678901234568",
        "vehicle": {
            "id": 12345678901234567,
            "id_s": "12345678901234567",
            "vehicle_id": 98765432109876543,
            "display_name": "seaQuest",
        },
        "drive_state": {"latitude": 37.33182, "longitude": -122.03118},
        "navigation": {
            "destination": "1 Infinite Loop, Cupertino",
            "address": "123 Main St, Springfield",
            "formatted_address": "456 Example Ave, Los Angeles",
            "query": "coffee shop near home",
            "route": "home to work",
            "waypoints": ["Home", "Office"],
            "place_ids": ["abc"],
        },
        "auth": {
            "access_token": "secret-access-token-123456",
            "message": "Bearer nav-token-123456789 for 5YJ3E1EA7JF000001",
        },
    }

    redacted = _dashboard_display_payload(payload)
    rendered = json.dumps(redacted)

    assert redacted["vin"] == "…0001"
    assert redacted["vins"] == ["…0002"]
    assert redacted["default_vin"] == "…0003"
    assert redacted["target_vehicle"] == "…4568"
    assert redacted["vehicle"]["id"] == "…4567"
    assert redacted["vehicle"]["id_s"] == "…4567"
    assert redacted["vehicle"]["vehicle_id"] == "…6543"
    assert redacted["vehicle"]["display_name"] == "seaQuest"
    assert redacted["drive_state"]["latitude"] == "[REDACTED_LOCATION]"
    assert redacted["drive_state"]["longitude"] == "[REDACTED_LOCATION]"
    assert redacted["navigation"]["destination"] == "[REDACTED_LOCATION]"
    assert redacted["navigation"]["address"] == "[REDACTED_LOCATION]"
    assert redacted["navigation"]["formatted_address"] == "[REDACTED_LOCATION]"
    assert redacted["navigation"]["query"] == "[REDACTED_LOCATION]"
    assert redacted["navigation"]["route"] == "[REDACTED_LOCATION]"
    assert redacted["navigation"]["waypoints"] == "[REDACTED_LOCATION]"
    assert redacted["navigation"]["place_ids"] == "[REDACTED_LOCATION]"
    assert redacted["auth"]["access_token"] == "[REDACTED]"
    assert "5YJ3E1EA7JF000001" not in rendered
    assert "5YJ3E1EA7JF000002" not in rendered
    assert "5YJ3E1EA7JF000003" not in rendered
    assert "12345678901234567" not in rendered
    assert "12345678901234568" not in rendered
    assert "98765432109876543" not in rendered
    assert "secret...3456" not in rendered
    assert "nav-token-123456789" not in rendered
    assert "37.33182" not in rendered
    assert "1 Infinite Loop" not in rendered
    assert "123 Main St" not in rendered
    assert "456 Example Ave" not in rendered
    assert "coffee shop" not in rendered
    assert "home to work" not in rendered
    assert "Office" not in rendered


def test_dashboard_payload_panel_uses_redacted_display_payload() -> None:
    asset = Path("src/hermes_tescmd_plugin/dashboard/assets/index.js").read_text()

    assert (
        "const displayData = data && data.display_payload ? data.display_payload : data;"
        in asset
    )
    assert "Redacted last payload" in asset
    assert "Debug view hides full vehicle identifiers" in asset


def test_dashboard_catalog_includes_expanded_reads_and_actions() -> None:
    catalog = tools()

    assert catalog["reads"]["closures"] == "tescmd_vehicle_closures_status"
    assert catalog["reads"]["onboarding"] == "tescmd_onboarding_status"
    assert catalog["reads"]["software"] == "tescmd_software_status"
    assert catalog["reads"]["nearby-chargers"] == "tescmd_vehicle_nearby_chargers"
    assert catalog["quick_actions"]["unlock"] == "tescmd_unlock"
    assert catalog["quick_actions"]["honk"] == "tescmd_honk"
    assert catalog["quick_actions"]["charge-limit"] == "tescmd_charge_limit"
    assert catalog["quick_actions"]["window-vent"] == "tescmd_vehicle_window_control"
    assert catalog["quick_actions"]["nav"] == "tescmd_navigation_send"


def test_dashboard_command_catalog_is_generated_from_runtime_specs() -> None:
    catalog = commands()
    by_name = {command["name"]: command for command in catalog["commands"]}

    assert catalog["ok"] is True
    assert catalog["source"] == "runtime.list_tool_specs"
    assert catalog["count"] == len(catalog["commands"])
    assert "tescmd_charge_limit" in by_name
    assert by_name["tescmd_charge_limit"]["category"] == "charge"
    assert by_name["tescmd_charge_limit"]["confirm_required"] is True
    assert by_name["tescmd_charge_limit"]["wake_capable"] is False
    assert by_name["tescmd_charge_limit"]["sensitive_parameters"]["vin"] == [
        "vehicle_identifier",
        "schema_sensitive",
    ]
    assert "Requires confirm=true" in by_name["tescmd_charge_limit"]["safety_notes"][0]
    assert (
        "Vehicle identifiers should stay redacted"
        in by_name["tescmd_charge_limit"]["safety_notes"][1]
    )
    assert by_name["tescmd_charge_limit"]["parameters"]["percent"]["type"] == "integer"
    assert (
        by_name["tescmd_charge_limit"]["parameters"]["confirm"][
            "x-confirmation-required"
        ]
        is True
    )
    assert "tescmd_auth_status" in by_name
    auth_complete = by_name["tescmd_auth_complete"]
    assert "secret_or_oauth_value" in auth_complete["sensitive_parameters"]["code"]
    assert "secret_or_oauth_value" in auth_complete["sensitive_parameters"]["state"]
    assert any(
        "OAuth/secrets/PIN-like" in note for note in auth_complete["safety_notes"]
    )
    nav = by_name["tescmd_navigation_gps"]
    assert nav["sensitive_parameters"]["lat"] == ["location_or_destination"]
    assert nav["sensitive_parameters"]["lon"] == ["location_or_destination"]
    assert any("Locations, destinations" in note for note in nav["safety_notes"])
    assert catalog["categories"]["charge"] >= 1


def test_dashboard_commands_tab_uses_dynamic_catalog_endpoint() -> None:
    asset = Path("src/hermes_tescmd_plugin/dashboard/assets/index.js").read_text()
    style = Path("src/hermes_tescmd_plugin/dashboard/assets/style.css").read_text()

    assert 'api("/commands")' in asset
    assert "CommandCatalog" in asset
    assert "activeTab" in asset
    assert "Tesla dashboard tabs" in asset
    assert "Live catalog pulled from the plugin runtime tool specs" in asset
    assert "not maintained by dashboard copy" in asset
    assert "commandSafetyBadges" in asset
    assert "privacy:" in asset
    assert "redact ID" in asset
    assert "location" in asset
    assert "secret-safe" in asset
    assert ".tescmd-command-safety" in style
    assert "runtime.list_tool_specs" not in asset
    assert "tescmd_command_catalog_static" not in asset
    assert ".tescmd-command-grid" in style
    assert ".tescmd-tabs" in style


def test_dashboard_command_search_includes_safety_and_parameter_terms() -> None:
    asset = Path("src/hermes_tescmd_plugin/dashboard/assets/index.js").read_text()

    assert "function commandSearchCorpus(command)" in asset
    assert "Object.keys(command.parameters)" in asset
    assert "command.sensitive_parameters" in asset
    assert "command.safety_notes" in asset
    assert "commandSearchCorpus(command).includes(queryText)" in asset
    assert "value).toLowerCase().includes(queryText)" not in asset


def test_dashboard_overview_collects_visual_read_sections_without_wake(
    monkeypatch,
) -> None:
    calls: list[tuple[str, dict]] = []

    def fake_run(tool_name, args=None):
        calls.append((tool_name, args or {}))
        return {"ok": True, "tool": tool_name}

    monkeypatch.setattr("hermes_tescmd_plugin.dashboard.plugin_api._run", fake_run)

    payload = overview(
        vin="5YJ3E1EA7JF000001",
        profile="daily",
        region="na",
        no_cache=True,
        units="metric",
    )

    assert payload["ok"] is True
    assert payload["display_payload"]["vin"] == "…0001"
    assert payload["sections"]["charge"]["tool"] == "tescmd_charge_status"
    assert payload["sections"]["location"]["tool"] == "tescmd_vehicle_location"
    assert payload["sections"]["climate"]["tool"] == "tescmd_climate_status"
    assert payload["section_health"] == {
        "ok": True,
        "issue_count": 0,
        "issues": [],
        "privacy_note": "Section errors are summarized without VINs, tokens, destinations, or precise location data.",
    }
    assert payload["onboarding"]["tool"] == "tescmd_onboarding_status"
    assert (
        "tescmd_charge_status",
        {
            "profile": "daily",
            "vin": "5YJ3E1EA7JF000001",
            "region": "na",
            "wake": False,
            "confirm": False,
            "no_cache": True,
            "units": "metric",
        },
    ) in calls


def test_dashboard_hides_operational_onboarding_banner() -> None:
    asset = Path("src/hermes_tescmd_plugin/dashboard/assets/index.js").read_text()

    assert "if (onboardingOperational(onboarding)) return null;" in asset
    assert "Operational status" not in asset
    assert "Vehicle reads and commands ready" not in asset
    assert "setup complete for operations" not in asset
    assert "Tesla OAuth app setup complete for dashboard operations." not in asset
    assert "Maintenance check:" not in asset
    assert "Optional maintenance:" not in asset
    assert '["OAuth app key", bootstrap.key_hosting_ready, "check"]' in asset


def test_dashboard_shows_sleep_status_with_wake_button() -> None:
    asset = Path("src/hermes_tescmd_plugin/dashboard/assets/index.js").read_text()
    style = Path("src/hermes_tescmd_plugin/dashboard/assets/style.css").read_text()

    assert "function vehicleAvailability" in asset
    assert "VehicleSleepStatus" in asset
    assert "is asleep" in asset
    assert "Wake vehicle" in asset
    assert 'runAction("wake")' in asset
    assert "Turn on action confirmation to wake the vehicle." in asset
    assert (
        "const rawName = vehicle && (vehicle.display_name || vehicle.vehicle_name || vehicle.name);"
        in asset
    )
    assert 'const name = visibleVehicleText(rawName, "Vehicle");' in asset
    assert "`${name} is asleep`" in asset
    assert (
        "h(VehicleSnapshot, { overview, runAction, loading, confirm, locationPrecision })"
        in asset
    )
    assert ".tescmd-sleep-status" in style
    assert (
        'const name = (vehicle && (vehicle.display_name || vehicle.vehicle_name || vehicle.name)) || "Vehicle";'
        not in asset
    )


def test_dashboard_location_display_defaults_to_approximate_coordinates() -> None:
    asset = Path("src/hermes_tescmd_plugin/dashboard/assets/index.js").read_text()

    assert "function displayLocation" in asset
    assert 'useState("approximate")' in asset
    assert "Location display" in asset
    assert "Approximate area" in asset
    assert "Precise coordinates" in asset
    assert "Approximate mode rounds visible map text and marker position" in asset
    assert '{ value: "us" }, "US"' in asset
    assert "Number(lat.toFixed(2))" in asset
    assert "Number(lon.toFixed(2))" in asset
    assert "precise coordinates hidden" in asset
    assert "precise coordinates visible" in asset
    assert "Approximate vehicle area" in asset
    assert 'precise ? "Vehicle map" : "Approximate area"' in asset
    assert "visibleLocation.label" in asset
    assert "visibleLocation.zoom || 10" in asset
    assert 'visibleLocation.popup || "Approximate vehicle area"' in asset
    assert "h(LeafletMap, { visibleLocation })" in asset
    assert "`${location.lat.toFixed(4)}, ${location.lon.toFixed(4)}`" not in asset
    assert 'h("span", null, label)' in asset


def test_dashboard_vehicle_picker_uses_safe_model_hints_not_visible_ids() -> None:
    asset = Path("src/hermes_tescmd_plugin/dashboard/assets/index.js").read_text()

    assert "function vehicleModelHint" in asset
    assert "vehicle_config" in asset
    assert "config.car_type" in asset
    assert "config.trim_badging" in asset
    assert "vehiclePickerLabel(vehicle, index)" in asset
    assert "Vehicle menu labels show safe model hints only" in asset
    assert "full VIN/Fleet IDs stay out of visible option text" in asset
    assert "`${name} — ${hint} — ${state}`" in asset
    assert "`${name} — ${state}`" in asset
    assert "`${name} — ${id} — ${state}`" not in asset
    assert "`${name} — ${vehicle.vin}" not in asset
    assert "`${name} — ${vehicle.id_s}" not in asset


def test_dashboard_overview_shows_safe_selected_target_summary() -> None:
    asset = Path("src/hermes_tescmd_plugin/dashboard/assets/index.js").read_text()
    style = Path("src/hermes_tescmd_plugin/dashboard/assets/style.css").read_text()

    assert "function vehicleIdentitySummary" in asset
    assert "function VehicleIdentityCard" in asset
    assert "Selected target" in asset
    assert "Vehicle override active" in asset
    assert "Configured default target" in asset
    assert "model hint unavailable" in asset
    assert "Visible target summary omits VIN and Fleet IDs" in asset
    assert "use the vehicle menu to change target safely" in asset
    assert "h(VehicleIdentityCard, { identity })" in asset
    assert 'identity.state === "online"' in asset
    assert ".tescmd-identity-card" in style
    assert ".tescmd-identity-meta" in style
    assert "identity.vin" not in asset
    assert "identity.id_s" not in asset


def test_dashboard_overview_summarizes_section_read_health_privately() -> None:
    health = _overview_section_health(
        {
            "charge": {"ok": True},
            "location": {
                "ok": False,
                "error": "Vehicle unavailable for 5YJ3E1EA7JF000001 near 1 Infinite Loop",
                "status_code": 408,
            },
            "security": {
                "ok": False,
                "payload": {"error": "Auth token expired for Bearer secret-token"},
                "response": {"status_code": 401},
            },
        }
    )
    rendered_health = json.dumps(health)

    assert health["ok"] is False
    assert health["issue_count"] == 2
    assert health["issues"] == [
        {"name": "location", "reason": "vehicle unavailable · status 408"},
        {"name": "security", "reason": "auth/login required · status 401"},
    ]
    assert (
        "VINs, tokens, destinations, or precise location data" in health["privacy_note"]
    )
    assert "5YJ3E1EA7JF000001" not in rendered_health
    assert "1 Infinite Loop" not in rendered_health
    assert "secret-token" not in rendered_health

    asset = Path("src/hermes_tescmd_plugin/dashboard/assets/index.js").read_text()
    style = Path("src/hermes_tescmd_plugin/dashboard/assets/style.css").read_text()

    assert "function sectionIssueLabel" in asset
    assert "function sectionHealthItems" in asset
    assert "overview.section_health.issues" in asset
    assert "overview.section_health.privacy_note" in asset
    assert "function SectionHealthPanel" in asset
    assert "Read health" in asset
    assert "overview read issue" in asset
    assert "Overview reads look clean" in asset
    assert "+${hiddenCount} more" in asset
    assert (
        "Section errors are summarized without VINs, tokens, destinations, or precise location data"
        in asset
    )
    assert "auth/login required" in asset
    assert "vehicle asleep" in asset
    assert "vehicle unavailable" in asset
    assert "rate limited" in asset
    assert "missing scope" in asset
    assert "h(SectionHealthPanel, { overview })" in asset
    assert ".tescmd-section-health" in style
    assert ".tescmd-section-health-warn" in style
    assert "5YJ3E1EA7JF000001" not in asset
    assert "1 Infinite Loop" not in asset


def test_dashboard_shows_busy_banner_during_refresh() -> None:
    asset = Path("src/hermes_tescmd_plugin/dashboard/assets/index.js").read_text()
    style = Path("src/hermes_tescmd_plugin/dashboard/assets/style.css").read_text()

    assert "BusyBanner" in asset
    assert "Loading Tesla dashboard…" in asset
    assert "Fetching setup and vehicle status." in asset
    assert "Updating Tesla data…" in asset
    assert "This can take a moment while Tesla responds." in asset
    assert "controls are disabled" not in asset
    assert "command is not reissued" not in asset
    assert "h(BusyBanner, { loading, mode: loadingMode })" in asset
    assert 'refresh("initial")' in asset
    assert 'refresh("refresh")' in asset
    assert ".tescmd-busy-banner" in style


def test_dashboard_quick_actions_explain_locked_and_armed_states() -> None:
    asset = Path("src/hermes_tescmd_plugin/dashboard/assets/index.js").read_text()
    style = Path("src/hermes_tescmd_plugin/dashboard/assets/style.css").read_text()

    assert "function ActionSafetyPanel" in asset
    assert "Physical actions are locked" in asset
    assert "Physical actions are armed" in asset
    assert "Read panels stay available" in asset
    assert "require the confirmation checkbox" in asset
    assert "Buttons below can wake or change the vehicle" in asset
    assert "Confirmation automatically turns off after one quick action" in asset
    assert "physical actions are locked again" in asset
    assert "confirmation is still locked off after the request" in asset
    assert "setConfirm(false)" in asset
    assert "h(ActionSafetyPanel, { confirm, loading, lastActionStatus })" in asset
    assert 'role: "status", "aria-live": "polite"' in asset
    assert ".tescmd-action-safety" in style
    assert ".tescmd-action-safety-armed" in style
    assert "duplicate command prevention" not in asset
    assert "controls disabled" not in asset


def test_dashboard_empty_states_give_actionable_safe_guidance() -> None:
    asset = Path("src/hermes_tescmd_plugin/dashboard/assets/index.js").read_text()
    style = Path("src/hermes_tescmd_plugin/dashboard/assets/style.css").read_text()

    assert "function EmptyState" in asset
    assert "No vehicle overview loaded" in asset
    assert "Start with a read-only refresh" in asset
    assert "does not arm quick actions or run physical Tesla side effects" in asset
    assert "Only enable wake + confirm" in asset
    assert "No payload selected" in asset
    assert "confirm-gated quick action" in asset
    assert "No location fix yet" in asset
    assert "Precise coordinates stay inside the dashboard payload" in asset
    assert 'role: "region"' in asset
    assert ".tescmd-empty-state" in style
    assert ".tescmd-empty-action" in style
    assert ".tescmd-map-empty .tescmd-empty-state" in style
    assert "No payload yet." not in asset
    assert "Refresh to load charge, climate, security, and map widgets." not in asset
    assert "No vehicle coordinates yet" not in asset


def test_dashboard_read_passes_wake_confirm_no_cache_and_units(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []

    def fake_run(tool_name, args=None):
        calls.append((tool_name, args or {}))
        return {"ok": True}

    monkeypatch.setattr("hermes_tescmd_plugin.dashboard.plugin_api._run", fake_run)

    payload = read(
        "software",
        vin="5YJ3E1EA7JF000001",
        profile="daily",
        region="eu",
        wake=True,
        confirm=True,
        no_cache=True,
        units="metric",
    )

    assert payload == {"ok": True, "display_payload": {"ok": True}}
    assert calls == [
        (
            "tescmd_software_status",
            {
                "profile": "daily",
                "vin": "5YJ3E1EA7JF000001",
                "region": "eu",
                "wake": True,
                "confirm": True,
                "no_cache": True,
                "units": "metric",
            },
        )
    ]


def test_dashboard_quick_action_passes_extra_action_arguments(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []

    def fake_run(tool_name, args=None):
        calls.append((tool_name, args or {}))
        return {"ok": True}

    monkeypatch.setattr("hermes_tescmd_plugin.dashboard.plugin_api._run", fake_run)

    payload = quick_action(
        QuickActionBody(
            action="charge-limit",
            vin="5YJ3E1EA7JF000001",
            profile="daily",
            region="na",
            confirm=True,
            percent=80,
        )
    )

    assert payload == {"ok": True, "display_payload": {"ok": True}}
    assert calls == [
        (
            "tescmd_charge_limit",
            {
                "profile": "daily",
                "confirm": True,
                "vin": "5YJ3E1EA7JF000001",
                "region": "na",
                "percent": 80,
            },
        )
    ]


def test_dashboard_quick_action_rejects_unmodeled_fields() -> None:
    with pytest.raises(ValueError, match="unexpected"):
        QuickActionBody.model_validate(
            {"action": "honk", "confirm": True, "unexpected": "ignored"}
        )


def test_dashboard_quick_action_requires_confirm_before_network(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    config.save_config(
        config.PluginConfig(
            profile="default", client_id="client-123", default_vin="5YJ3E1EA7JF000001"
        )
    )
    config.save_auth_state(
        config.AuthState(profile="default", access_token="token", region="na")
    )

    calls: list[tuple] = []

    def fail_if_called(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError(
            "vehicle command should not be called without confirm=true"
        )

    monkeypatch.setattr(
        "hermes_tescmd_plugin.client.TeslaFleetClient.vehicle_command", fail_if_called
    )

    payload = quick_action(QuickActionBody(action="honk", confirm=False))

    assert payload["ok"] is False
    assert "confirm=true is required" in payload["error"]
    assert calls == []


def test_dashboard_default_vehicle_endpoint_persists_redacted_default(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    config.save_config(config.PluginConfig(profile="daily", client_id="client-123"))

    payload = set_default_vehicle(
        DefaultVehicleBody(profile="daily", vin="5YJ3E1EA7JF000001")
    )

    assert payload["ok"] is True
    assert payload["profile"] == "daily"
    assert payload["default_vehicle"] == "…0001"
    assert payload["display_payload"]["default_vehicle"] == "…0001"
    assert config.load_config("daily").default_vin == "5YJ3E1EA7JF000001"
    assert "5YJ3E1EA7JF000001" not in json.dumps(payload)


def test_dashboard_default_vehicle_endpoint_can_clear_default(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    config.save_config(
        config.PluginConfig(profile="daily", default_vin="5YJ3E1EA7JF000001")
    )

    payload = set_default_vehicle(DefaultVehicleBody(profile="daily", vin=""))

    assert payload["ok"] is True
    assert payload["default_vehicle"] is None
    assert "cleared" in payload["message"]
    assert config.load_config("daily").default_vin is None


def test_dashboard_assets_include_default_vehicle_controls() -> None:
    asset = Path("src/hermes_tescmd_plugin/dashboard/assets/index.js").read_text()
    style = Path("src/hermes_tescmd_plugin/dashboard/assets/style.css").read_text()

    assert 'api("/default-vehicle"' in asset
    assert "Make selected default" in asset
    assert "Clear dashboard default" in asset
    assert "tescmd-inline-actions" in style


def test_dashboard_assets_install_to_hermes_plugin_tree(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    result = ensure_dashboard_installed()

    assert result["ok"] is True
    dashboard_dir = Path(result["path"])
    assert dashboard_dir == tmp_path / "plugins" / "hermes-tescmd-plugin" / "dashboard"
    assert (dashboard_dir / "manifest.json").exists()
    assert (dashboard_dir / "plugin_api.py").exists()
    assert (dashboard_dir / "assets" / "index.js").exists()
    assert json.loads((dashboard_dir / "manifest.json").read_text())["label"] == "Tesla"
