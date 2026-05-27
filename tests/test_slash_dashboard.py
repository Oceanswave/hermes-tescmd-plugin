from __future__ import annotations

import json
from pathlib import Path

import pytest

from hermes_tescmd_plugin import config, slash
from hermes_tescmd_plugin.dashboard import ensure_dashboard_installed
from hermes_tescmd_plugin.dashboard.plugin_api import (
    QuickActionBody,
    overview,
    quick_action,
    read,
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


def test_dashboard_catalog_includes_expanded_reads_and_actions() -> None:
    catalog = tools()

    assert catalog["reads"]["closures"] == "tescmd_vehicle_closures_status"
    assert catalog["reads"]["onboarding"] == "tescmd_onboarding_status"
    assert catalog["reads"]["software"] == "tescmd_software_status"
    assert catalog["reads"]["nearby-chargers"] == "tescmd_vehicle_nearby_chargers"
    assert catalog["quick_actions"]["unlock"] == "tescmd_security_unlock"
    assert catalog["quick_actions"]["charge-limit"] == "tescmd_charge_limit"
    assert catalog["quick_actions"]["window-vent"] == "tescmd_vehicle_window_control"
    assert catalog["quick_actions"]["nav"] == "tescmd_navigation_send"


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
    assert payload["sections"]["charge"]["tool"] == "tescmd_charge_status"
    assert payload["sections"]["location"]["tool"] == "tescmd_vehicle_location"
    assert payload["sections"]["climate"]["tool"] == "tescmd_climate_status"
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

    assert payload == {"ok": True}
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

    assert payload == {"ok": True}
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
