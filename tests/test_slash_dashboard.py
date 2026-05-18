from __future__ import annotations

import json
from pathlib import Path

from hermes_tescmd_plugin import config, slash
from hermes_tescmd_plugin.dashboard import ensure_dashboard_installed
from hermes_tescmd_plugin.dashboard.plugin_api import QuickActionBody, quick_action


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
    assert "tescmd-status" in by_name
    assert by_name["tescmd-honk"]["args_hint"] == "[vin] confirm=true"

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
    payload_text = output.split("\n", 1)[1]
    payload = json.loads(payload_text)

    assert payload["ok"] is False
    assert "confirm=true is required" in payload["error"]
    assert calls == []


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
