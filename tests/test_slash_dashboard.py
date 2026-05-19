from __future__ import annotations

import json
from pathlib import Path

from hermes_tescmd_plugin import config, slash
from hermes_tescmd_plugin.dashboard import ensure_dashboard_installed
from hermes_tescmd_plugin.dashboard.plugin_api import QuickActionBody, overview, quick_action, read, tools


class FakeContext:
    def __init__(self) -> None:
        self.commands: list[dict] = []

    def register_command(self, **kwargs) -> None:
        self.commands.append(kwargs)


def test_slash_args_parse_key_values_arrays_and_bare_vin() -> None:
    args = slash.parse_args('5YJ3E1EA7JF000001 endpoints=charge_state,drive_state wake=true region=na percent=80')

    assert args["vin"] == "5YJ3E1EA7JF000001"
    assert args["endpoints"] == ["charge_state", "drive_state"]
    assert args["wake"] is True
    assert args["region"] == "na"
    assert args["percent"] == 80


def test_registers_tescmd_slash_commands_and_status_handler(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    ctx = FakeContext()
    slash.register_commands(ctx)

    by_name = {command["name"]: command for command in ctx.commands}
    expected_commands = {
        "tescmd-status",
        "tescmd-auth-status",
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
    assert by_name["tescmd-charge-limit"]["args_hint"] == "[vin] percent=80 confirm=true"

    config.save_config(config.PluginConfig(profile="default", client_id="client-123"))
    output = by_name["tescmd-status"]["handler"]("")
    assert "Tesla Fleet status" in output
    assert "app_configured: True" in output


def test_side_effect_slash_command_requires_confirm_before_network(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    config.save_config(config.PluginConfig(profile="default", client_id="client-123", default_vin="5YJ3E1EA7JF000001"))
    config.save_auth_state(config.AuthState(profile="default", access_token="token", region="na"))

    calls: list[tuple] = []

    def fail_if_called(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("vehicle command should not be called without confirm=true")

    monkeypatch.setattr("hermes_tescmd_plugin.client.TeslaFleetClient.vehicle_command", fail_if_called)
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
    assert "Vehicle: 5YJ3E1EA7JF000001" in output
    assert "Result: yes" in output
    assert "{" not in output


def test_read_slash_command_success_summarizes_vehicle_data() -> None:
    output = slash._format_command(
        "tescmd-charge",
        {
            "ok": True,
            "vin": "5YJ3E1EA7JF000001",
            "data": {"charge_state": {"battery_level": 65, "charging_state": "Disconnected", "charge_limit_soc": 80}},
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
    assert catalog["reads"]["software"] == "tescmd_software_status"
    assert catalog["reads"]["nearby-chargers"] == "tescmd_vehicle_nearby_chargers"
    assert catalog["quick_actions"]["unlock"] == "tescmd_security_unlock"
    assert catalog["quick_actions"]["charge-limit"] == "tescmd_charge_limit"
    assert catalog["quick_actions"]["window-vent"] == "tescmd_vehicle_window_control"
    assert catalog["quick_actions"]["nav"] == "tescmd_navigation_send"


def test_dashboard_overview_collects_visual_read_sections_without_wake(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []

    def fake_run(tool_name, args=None):
        calls.append((tool_name, args or {}))
        return {"ok": True, "tool": tool_name}

    monkeypatch.setattr("hermes_tescmd_plugin.dashboard.plugin_api._run", fake_run)

    payload = overview(vin="5YJ3E1EA7JF000001", profile="daily", region="na", no_cache=True, units="metric")

    assert payload["ok"] is True
    assert payload["sections"]["charge"]["tool"] == "tescmd_charge_status"
    assert payload["sections"]["location"]["tool"] == "tescmd_vehicle_location"
    assert payload["sections"]["climate"]["tool"] == "tescmd_climate_status"
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


def test_dashboard_quick_action_requires_confirm_before_network(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    config.save_config(config.PluginConfig(profile="default", client_id="client-123", default_vin="5YJ3E1EA7JF000001"))
    config.save_auth_state(config.AuthState(profile="default", access_token="token", region="na"))

    calls: list[tuple] = []

    def fail_if_called(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("vehicle command should not be called without confirm=true")

    monkeypatch.setattr("hermes_tescmd_plugin.client.TeslaFleetClient.vehicle_command", fail_if_called)

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
