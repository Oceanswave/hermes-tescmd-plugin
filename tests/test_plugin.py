from __future__ import annotations

import base64
import hashlib
import hmac
import json
import stat
import sys
import types
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from hermes_tescmd_plugin import register, registered_tool_specs
from hermes_tescmd_plugin import auth
from hermes_tescmd_plugin import client
from hermes_tescmd_plugin import config
from hermes_tescmd_plugin import runtime
from hermes_tescmd_plugin import schemas
from hermes_tescmd_plugin import tools
from hermes_tescmd_plugin.protocol.encoder import encode_routable_message
from hermes_tescmd_plugin.protocol.commands import COMMAND_REGISTRY
from hermes_tescmd_plugin.protocol.metadata import TAG_CHALLENGE, TAG_PERSONALIZATION, TAG_SIGNATURE_TYPE, encode_tlv
from hermes_tescmd_plugin.protocol.protobuf.messages import (
    Destination,
    Domain,
    HMACPersonalizedData,
    HMACSignatureData,
    KeyIdentity,
    MessageFault,
    MessageStatus,
    OperationStatus,
    RoutableMessage,
    SignatureData,
    _encode_fixed32_field,
    _encode_length_delimited,
    _encode_varint_field,
)
from hermes_tescmd_plugin.protocol.signer import derive_session_info_key


class FakeContext:
    def __init__(self) -> None:
        self.tools: list[dict] = []
        self.skills: list[tuple[str, Path]] = []
        self.commands: list[dict] = []

    def register_tool(self, **kwargs) -> None:
        self.tools.append(kwargs)

    def register_skill(self, name: str, path: Path, description: str | None = None) -> None:
        self.skills.append((name, path))

    def register_command(self, **kwargs) -> None:
        self.commands.append(kwargs)


def make_response(method: str, url: str, *, status_code: int = 200, json_body: dict | list | None = None) -> httpx.Response:
    request = httpx.Request(method, url)
    return httpx.Response(status_code, json=json_body, request=request)


def test_register_adds_full_native_tools_and_skill_by_default(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    ctx = FakeContext()
    register(ctx)

    registered_names = [tool["name"] for tool in ctx.tools]
    assert registered_names == [spec.name for spec in runtime.list_tool_specs()]
    assert registered_names == [spec.name for spec in registered_tool_specs()]
    assert len(ctx.tools) == 174
    assert "tescmd_auth_status" in registered_names
    assert "tescmd_vehicle_status" in registered_names
    assert "tescmd_raw_get" in registered_names
    assert "tescmd_raw_post" in registered_names
    assert "tescmd_key_deploy" in registered_names
    assert "tescmd_vehicle_enterprise_roles" in registered_names
    assert ctx.skills
    assert ctx.skills[0][0] == "tescmd-operator"
    assert ctx.skills[0][1].name == "SKILL.md"
    registered_commands = {command["name"] for command in ctx.commands}
    assert {
        "tescmd-status",
        "tescmd-vehicles",
        "tescmd-vehicle-status",
        "tescmd-charge",
        "tescmd-climate",
        "tescmd-location",
        "tescmd-wake",
        "tescmd-flash",
        "tescmd-honk",
        "tescmd-lock",
    } <= registered_commands
    dashboard_manifest = tmp_path / "plugins" / "hermes-tescmd-plugin" / "dashboard" / "manifest.json"
    assert dashboard_manifest.exists()
    assert json.loads(dashboard_manifest.read_text())["tab"]["path"] == "/tescmd"


def test_runtime_keeps_parity_critical_native_tools() -> None:
    names = {spec.name for spec in runtime.list_tool_specs()}

    command_names = {spec.command_name for spec in runtime.list_tool_specs() if spec.operation == "vehicle_command"}
    assert None not in command_names
    assert command_names <= set(COMMAND_REGISTRY)

    assert "tescmd_setup" not in names
    assert "tescmd_setup_wizard" not in names
    assert "tescmd_mcp_serve" not in names
    assert "tescmd_auth_complete" in names
    assert "tescmd_precondition_schedule_add" in names
    assert "tescmd_precondition_schedule_remove" in names
    assert "tescmd_precondition_schedules_clear" in names
    assert "tescmd_power_keep_accessory_mode" in names
    assert "tescmd_power_low_power_mode" in names
    for name in {
        "tescmd_vehicle_drive_status",
        "tescmd_vehicle_closures_status",
        "tescmd_vehicle_config_status",
        "tescmd_vehicle_gui_settings",
        "tescmd_vehicle_charge_schedule_status",
        "tescmd_vehicle_preconditioning_schedule_status",
    }:
        assert name in names


def test_runtime_redacts_vin_dictionary_keys() -> None:
    redacted = runtime._redact({"7SAYGDEE5PF662181": {"vin": "5YJ3E1EA7JF000001"}})  # noqa: SLF001
    assert "7SAYGDEE5PF662181" not in redacted
    assert "[REDACTED]" in redacted
    assert redacted["[REDACTED]"]["vin"] == "[REDACTED]"


def test_schema_uses_native_tool_metadata(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    tools = {spec.name: spec for spec in runtime.list_tool_specs()}

    wake_schema = schemas.build_schema(tools["tescmd_vehicle_wake"])
    assert set(wake_schema["parameters"]["required"]) == {"confirm"}

    waypoint_schema = schemas.build_schema(tools["tescmd_navigation_waypoints"])
    waypoint_props = waypoint_schema["parameters"]["properties"]
    assert waypoint_schema["parameters"]["required"] == ["confirm", "place_ids"]
    assert waypoint_props["place_ids"]["type"] == "array"
    assert waypoint_props["place_ids"]["items"]["type"] == "string"

    billing_schema = schemas.build_schema(tools["tescmd_billing_invoice"])
    assert "confirm" in billing_schema["parameters"]["properties"]

    auth_complete_props = schemas.build_schema(tools["tescmd_auth_complete"])["parameters"]["properties"]
    assert auth_complete_props["callback_url"]["x-sensitive"] is True
    assert auth_complete_props["callback_url"]["writeOnly"] is True
    assert auth_complete_props["state"]["x-sensitive"] is True

    vehicle_schema = schemas.build_schema(tools["tescmd_vehicle_status"])
    vehicle_props = vehicle_schema["parameters"]["properties"]
    assert "vin" in vehicle_props
    assert "wake" in vehicle_props
    assert vehicle_props["endpoints"]["type"] == "array"
    assert vehicle_props["endpoints"]["items"]["type"] == "string"

    vehicle_get_props = schemas.build_schema(tools["tescmd_vehicle_get"])["parameters"]["properties"]
    assert "wake" not in vehicle_get_props
    assert "no_cache" not in vehicle_get_props

    unsupported_wake = json.loads(runtime.make_handler(tools["tescmd_vehicle_get"])(({"wake": True})))
    assert unsupported_wake["ok"] is False
    assert "Unsupported argument" in unsupported_wake["error"]

    fleet_status_schema = schemas.build_schema(tools["tescmd_vehicle_fleet_status"])
    assert fleet_status_schema["parameters"]["properties"]["vins"]["type"] == "array"
    assert fleet_status_schema["parameters"]["properties"]["vins"]["items"]["type"] == "string"

    charge_schema = schemas.build_schema(tools["tescmd_charge_limit"])
    charge_props = charge_schema["parameters"]["properties"]
    assert charge_schema["parameters"]["required"] == ["confirm", "percent"]
    assert charge_props["percent"]["type"] == "integer"
    assert charge_props["percent"]["minimum"] == 50
    assert charge_props["percent"]["maximum"] == 100

    sentry_schema = schemas.build_schema(tools["tescmd_security_sentry_mode"])
    sentry_props = sentry_schema["parameters"]["properties"]
    assert sentry_schema["parameters"]["required"] == ["confirm", "enabled"]
    assert sentry_props["enabled"]["type"] == "boolean"

    assert "tescmd_setup_wizard" not in tools
    assert "tescmd_mcp_serve" not in tools

    key_deploy_schema = schemas.build_schema(tools["tescmd_key_deploy"])
    key_deploy_props = key_deploy_schema["parameters"]["properties"]
    assert key_deploy_props["method"]["enum"] == ["local"]

    for tool_name, required in {
        "tescmd_energy_backup": ["confirm", "percent", "site_id"],
        "tescmd_energy_mode": ["confirm", "mode", "site_id"],
        "tescmd_energy_storm": ["confirm", "enabled", "site_id"],
        "tescmd_energy_tou": ["confirm", "settings", "site_id"],
        "tescmd_energy_off_grid": ["confirm", "reserve", "site_id"],
        "tescmd_energy_grid_config": ["confirm", "config", "site_id"],
        "tescmd_sharing_add_driver": ["confirm", "email"],
        "tescmd_sharing_remove_driver": ["confirm", "share_user_id"],
        "tescmd_sharing_create_invite": ["confirm"],
        "tescmd_sharing_revoke_invite": ["confirm", "invite_id"],
    }.items():
        assert set(schemas.build_schema(tools[tool_name])["parameters"]["required"]) == set(required)


def test_manual_config_file_contract_and_vehicle_key_generation(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    cfg = config.save_config(
        config.PluginConfig(
            profile="default",
            client_id="client-123",
            client_secret="secret-abc",
            google_maps_api_key="gmaps-secret",
            region="eu",
            domain="cars.example.com",
            default_vin="5YJ3E1EA7JF000001",
        )
    )
    key_payload = auth.generate_vehicle_command_keypair("default", domain=cfg.domain)
    cfg = config.load_config("default")

    assert cfg.client_id == "client-123"
    assert cfg.client_secret == "secret-abc"
    assert cfg.google_maps_api_key == "gmaps-secret"
    assert cfg.region == "eu"
    assert cfg.domain == "cars.example.com"
    assert cfg.default_vin == "5YJ3E1EA7JF000001"
    assert cfg.vehicle_command_key_private_path is not None
    assert cfg.vehicle_command_key_private_path.endswith("vehicle-command-key.pem")
    assert Path(cfg.vehicle_command_key_private_path).exists()
    assert Path(key_payload["public_key_path"]).exists()
    assert key_payload["enrollment_url"] == "https://tesla.com/_ak/cars.example.com"



class DummyLock:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def install_fake_hermes_auth(monkeypatch, store: dict) -> None:
    fake_auth = types.ModuleType("hermes_cli.auth")

    def _load_auth_store():
        return store

    def _save_auth_store(updated):
        snapshot = dict(updated)
        store.clear()
        store.update(snapshot)
        return Path("/tmp/auth.json")

    fake_auth._load_auth_store = _load_auth_store
    fake_auth._save_auth_store = _save_auth_store
    fake_auth._auth_store_lock = DummyLock
    fake_hermes_cli = types.ModuleType("hermes_cli")
    fake_hermes_cli.auth = fake_auth
    monkeypatch.setitem(sys.modules, "hermes_cli", fake_hermes_cli)
    monkeypatch.setitem(sys.modules, "hermes_cli.auth", fake_auth)


def test_auth_state_uses_hermes_auth_store_when_available(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    store = {"version": 1, "providers": {}}
    install_fake_hermes_auth(monkeypatch, store)

    state = config.AuthState(
        profile="default",
        access_token="access-token",
        refresh_token="refresh-token",
        expires_at=123456,
        scopes=["vehicle_device_data"],
        region="na",
    )
    config.save_auth_state(state)

    provider_state = store["providers"][config.HERMES_AUTH_PROVIDER_ID]
    assert provider_state["auth_type"] == "oauth"
    assert provider_state["source"] == config.HERMES_AUTH_SOURCE
    assert provider_state["profiles"]["default"]["access_token"] == "access-token"
    assert store.get("active_provider") is None

    plugin_auth_file = tmp_path / "plugins" / "hermes-tescmd-plugin" / "auth.json"
    assert plugin_auth_file.exists()
    assert config.load_auth_state("default").refresh_token == "refresh-token"


def test_auth_state_prefers_hermes_auth_store_over_legacy_plugin_mirror(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    config.save_auth_state(config.AuthState(profile="default", access_token="legacy", region="na"))
    store = {
        "version": 1,
        "providers": {
            config.HERMES_AUTH_PROVIDER_ID: {
                "profiles": {
                    "default": {
                        "profile": "default",
                        "access_token": "hermes",
                        "refresh_token": "hermes-refresh",
                        "expires_at": None,
                        "scopes": [],
                        "region": "eu",
                        "token_type": "Bearer",
                    }
                }
            }
        },
    }
    install_fake_hermes_auth(monkeypatch, store)

    loaded = config.load_auth_state("default")

    assert loaded.access_token == "hermes"
    assert loaded.refresh_token == "hermes-refresh"
    assert loaded.region == "eu"


def test_clear_auth_state_removes_hermes_and_plugin_auth(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    store = {"version": 1, "providers": {}}
    install_fake_hermes_auth(monkeypatch, store)
    config.save_auth_state(config.AuthState(profile="default", access_token="access-token", region="na"))

    config.clear_auth_state("default")

    assert config.HERMES_AUTH_PROVIDER_ID not in store["providers"]
    assert config.load_auth_state("default").access_token is None


def test_bootstrap_status_reports_hermes_auth_store(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    install_fake_hermes_auth(monkeypatch, {"version": 1, "providers": {}})
    cfg = config.save_config(config.PluginConfig(profile="default", client_id="client-123"))

    bootstrap = tools._bootstrap_status(profile="default", cfg=cfg)  # noqa: SLF001

    assert bootstrap["auth_store"] == "hermes"
    assert bootstrap["auth_mirrored_to_plugin_state"] is True


def test_navigation_waypoints_accepts_place_ids_and_encodes_ref_ids(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    config.save_config(config.PluginConfig(profile="default", client_id="client-123", region="na", default_vin="5YJ3E1EA7JF000001"))
    config.save_auth_state(config.AuthState(profile="default", access_token="token", region="na"))
    spec = next(spec for spec in runtime.list_tool_specs() if spec.name == "tescmd_navigation_waypoints")

    calls = []

    def fake_command(self, vin, command_name, body=None):
        calls.append((vin, command_name, body))
        return {"result": True}

    monkeypatch.setattr(client.TeslaFleetClient, "vehicle_command", fake_command)
    payload = json.loads(
        runtime.make_handler(spec)(
            {"place_ids": ["ChIJIQBpAG2ahYAR_6128GcTUEo", "refId:ChIJw____96GhYARCVVwg5cT7c0"], "confirm": True}
        )
    )

    assert payload["ok"] is True
    assert calls == [
        (
            "5YJ3E1EA7JF000001",
            "navigation_waypoints_request",
            {"waypoints": "refId:ChIJIQBpAG2ahYAR_6128GcTUEo,refId:ChIJw____96GhYARCVVwg5cT7c0"},
        )
    ]


def test_navigation_place_search_requires_key_and_returns_candidates(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    tools_by_name = {spec.name: runtime.make_handler(spec) for spec in runtime.list_tool_specs()}

    missing = json.loads(tools_by_name["tescmd_navigation_place_search"]({"query": "Tesla Fremont Factory"}))
    assert missing["ok"] is False
    assert "google_maps_api_key" in missing["error"]

    config.save_config(config.PluginConfig(profile="default", client_id="client-123", google_maps_api_key="gmaps-secret"))

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "places": [
                    {
                        "id": "ChIJIQBpAG2ahYAR_6128GcTUEo",
                        "displayName": {"text": "Tesla Fremont Factory"},
                        "formattedAddress": "Fremont, CA",
                        "location": {"latitude": 37.4947, "longitude": -121.9440},
                    }
                ]
            }

    calls = []

    def fake_post(url, *, headers, json, timeout):
        calls.append((url, headers, json, timeout))
        return FakeResponse()

    monkeypatch.setattr(tools.httpx, "post", fake_post)
    payload = json.loads(tools_by_name["tescmd_navigation_place_search"]({"query": "Tesla Fremont Factory", "limit": 1}))

    assert payload["ok"] is True
    assert payload["candidates"][0]["place_id"] == "ChIJIQBpAG2ahYAR_6128GcTUEo"
    assert payload["next_tool"] == "tescmd_navigation_waypoints"
    assert payload["next_args_hint"] == {"place_ids": ["ChIJIQBpAG2ahYAR_6128GcTUEo"]}
    assert calls[0][1]["X-Goog-Api-Key"] == "gmaps-secret"
    assert calls[0][2] == {"textQuery": "Tesla Fremont Factory", "maxResultCount": 1}


def test_help_returns_agentic_routing_and_status_readiness(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    spec = next(spec for spec in runtime.list_tool_specs() if spec.name == "tescmd_help")
    payload = json.loads(runtime.make_handler(spec)({}))

    assert payload["ok"] is True
    assert payload["routing"]["where_is_my_car"] == "tescmd_vehicle_location"
    assert payload["bootstrap"]["ready_for_vehicle_reads"] is False
    assert "Do not invent Google Place IDs" in payload["safety"][2]


def test_status_returns_guided_bootstrap_status_and_key_urls_from_manual_config(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    tools_by_name = {spec.name: runtime.make_handler(spec) for spec in runtime.list_tool_specs()}

    config.save_config(config.PluginConfig(profile="default", client_id="client-123", domain="cars.example.com"))
    auth.generate_vehicle_command_keypair("default", domain="cars.example.com")
    payload = json.loads(tools_by_name["tescmd_status"]({}))

    assert payload["ok"] is True
    assert payload["bootstrap"]["app_configured"] is True
    assert payload["bootstrap"]["login_ready"] is True
    assert payload["bootstrap"]["key_present"] is True
    assert payload["redirect_uri"] == "https://cars.example.com/callback"
    assert payload["next_action"] == "auth_login"
    assert payload["next_steps"][0].startswith("Tesla app credentials are saved")
    assert payload["expected_public_key_url"] == "https://cars.example.com/.well-known/appspecific/com.tesla.3p.public-key.pem"
    assert payload["enrollment_url"] == "https://tesla.com/_ak/cars.example.com"
    assert payload["bootstrap"]["key_hosting_ready"] is False

    config.save_config(config.PluginConfig(profile="default", client_id="client-123", client_secret="secret-123", domain="cars.example.com", vehicle_command_key_private_path=config.load_config("default").vehicle_command_key_private_path, vehicle_command_key_public_path=config.load_config("default").vehicle_command_key_public_path))
    partner_ready = json.loads(tools_by_name["tescmd_status"]({}))
    assert partner_ready["bootstrap"]["partner_ready"] is True


def test_status_without_client_id_returns_docs_only_configuration_steps(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    tools_by_name = {spec.name: runtime.make_handler(spec) for spec in runtime.list_tool_specs()}

    payload = json.loads(tools_by_name["tescmd_status"]({}))

    assert payload["ok"] is True
    assert payload["configured"] is False
    assert payload["next_action"] == "configure_app"
    assert "README" in payload["next_steps"][2]
    assert "tescmd_setup" not in " ".join(payload["next_steps"])
    assert "tescmd_setup_wizard" not in " ".join(payload["next_steps"])


def test_bootstrap_key_steps_require_real_hosting_and_client_secret(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    tools_by_name = {spec.name: runtime.make_handler(spec) for spec in runtime.list_tool_specs()}

    config.save_config(config.PluginConfig(profile="default", client_id="client-123", domain="cars.example.com"))
    auth.generate_vehicle_command_keypair("default", domain="cars.example.com")
    setup_payload = json.loads(tools_by_name["tescmd_status"]({}))
    assert setup_payload["next_action"] == "auth_login"

    config.save_auth_state(
        config.AuthState(
            profile="default",
            access_token="access-1",
            refresh_token="refresh-1",
            expires_at=9999999999,
            scopes=["openid", "vehicle_cmds"],
            region="na",
        )
    )

    status_payload = json.loads(tools_by_name["tescmd_status"]({}))
    assert status_payload["bootstrap"]["public_key_accessible"] is False
    assert status_payload["bootstrap"]["key_hosting_ready"] is False
    assert status_payload["bootstrap"]["enrollment_ready"] is False

    deploy_payload = json.loads(tools_by_name["tescmd_key_deploy"]({"method": "local", "confirm": True}))
    assert deploy_payload["ok"] is True

    after_local = json.loads(tools_by_name["tescmd_status"]({}))
    assert after_local["bootstrap"]["key_hosting_ready"] is False
    assert after_local["bootstrap"]["enrollment_ready"] is False
    assert after_local["bootstrap"]["public_key_accessible"] is False
    assert after_local["bootstrap"]["public_key_matches_local_key"] is False

    public_key_path = config.load_config("default").vehicle_command_key_public_path
    assert public_key_path is not None
    public_key_pem = Path(public_key_path).read_text()

    def fake_get(url: str, **kwargs):
        return httpx.Response(200, text=public_key_pem, request=httpx.Request("GET", url))

    monkeypatch.setattr(client.httpx, "get", fake_get)
    hosted = json.loads(tools_by_name["tescmd_status"]({}))
    assert hosted["bootstrap"]["key_hosting_ready"] is True
    assert hosted["bootstrap"]["enrollment_ready"] is False

    prior_cfg = config.load_config("default")
    config.save_config(config.PluginConfig(profile="default", client_id="client-123", client_secret="secret-123", domain="cars.example.com", vehicle_command_key_private_path=prior_cfg.vehicle_command_key_private_path, vehicle_command_key_public_path=prior_cfg.vehicle_command_key_public_path))
    ready = json.loads(tools_by_name["tescmd_status"]({}))
    assert ready["next_action"] == "auth_register"
    assert ready["bootstrap"]["enrollment_ready"] is True


def test_auth_login_without_client_id_points_to_readme_setup(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    tools_by_name = {spec.name: runtime.make_handler(spec) for spec in runtime.list_tool_specs()}

    payload = json.loads(tools_by_name["tescmd_auth_login"]({}))

    assert payload["ok"] is False
    assert "README" in payload["error"]
    assert "tescmd_setup_wizard" not in payload["error"]
    assert "https://<your-domain>/callback" in payload["error"]
    assert "vehicle_cmds" in payload["error"]


def test_removed_bootstrap_wizard_and_tailscale_surfaces(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    names = {spec.name for spec in runtime.list_tool_specs()}

    assert "tescmd_setup_wizard" not in names
    assert "tescmd_mcp_serve" not in names

    tools_by_name = {spec.name: runtime.make_handler(spec) for spec in runtime.list_tool_specs()}
    config.save_config(config.PluginConfig(profile="default", client_id="client-123", domain="cars.example.com"))
    failed = json.loads(tools_by_name["tescmd_key_deploy"]({"method": "tailscale"}))
    assert failed["ok"] is False
    assert "local" in failed["error"]


def test_vehicle_status_uses_response_cache_until_bypassed_or_cleared(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    config.save_config(config.PluginConfig(profile="default", client_id="client-123", default_vin="5YJ3E1EA7JF000001"))
    config.save_auth_state(config.AuthState(profile="default", access_token="access-1", refresh_token="refresh-1", expires_at=9999999999, region="na"))
    tools_by_name = {spec.name: runtime.make_handler(spec) for spec in runtime.list_tool_specs()}

    calls: list[str] = []

    def fake_request(method: str, url: str, **kwargs):
        calls.append(url)
        return make_response(method, url, json_body={"response": {"charge_state": {"battery_level": len(calls)}}})

    monkeypatch.setattr(client.httpx, "request", fake_request)

    first = json.loads(tools_by_name["tescmd_vehicle_status"]({"endpoints": ["charge_state"]}))
    second = json.loads(tools_by_name["tescmd_vehicle_status"]({"endpoints": ["charge_state"]}))
    bypassed = json.loads(tools_by_name["tescmd_vehicle_status"]({"endpoints": ["charge_state"], "no_cache": True}))
    after_bypass = json.loads(tools_by_name["tescmd_vehicle_status"]({"endpoints": ["charge_state"]}))
    status = json.loads(tools_by_name["tescmd_cache_status"]({}))
    cleared = json.loads(tools_by_name["tescmd_cache_clear"]({"confirm": True}))
    after_clear = json.loads(tools_by_name["tescmd_vehicle_status"]({"endpoints": ["charge_state"]}))

    assert first["data"]["charge_state"]["battery_level"] == 1
    assert first["cache"]["hit"] is False
    assert second["data"]["charge_state"]["battery_level"] == 1
    assert second["cache"]["hit"] is True
    assert bypassed["data"]["charge_state"]["battery_level"] == 2
    assert bypassed["cache"]["bypassed"] is True
    assert after_bypass["data"]["charge_state"]["battery_level"] == 1
    assert after_bypass["cache"]["hit"] is True
    assert status["enabled"] is True
    assert status["entries"] >= 1
    assert cleared["cleared"] >= 1
    assert after_clear["data"]["charge_state"]["battery_level"] == 3
    assert len(calls) == 3


def test_public_oauth_redirect_uri_validation_and_override(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    saved = config.save_config(
        config.PluginConfig(
            profile="default",
            client_id="client-123",
            domain="cars.example.com",
            oauth_redirect_uri="https://auth.example.com/tesla/callback",
        )
    )
    assert saved.oauth_redirect_uri == "https://auth.example.com/tesla/callback"

    tools_by_name = {spec.name: runtime.make_handler(spec) for spec in runtime.list_tool_specs()}
    status = json.loads(tools_by_name["tescmd_status"]({}))
    assert status["redirect_uri"] == "https://auth.example.com/tesla/callback"

    for bad_uri in [
        "http://auth.example.com/callback",
        "https://localhost/callback",
        "https://auth.example.com:8443/callback",
        "https://auth.example.com/callback?code=bad",
    ]:
        with pytest.raises(config.PluginStateError):
            config.save_config(config.PluginConfig(profile="bad", client_id="client-123", oauth_redirect_uri=bad_uri))


def test_auth_login_start_and_complete_persist_tokens(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    config.save_config(
        config.PluginConfig(
            profile="default",
            client_id="client-123",
            client_secret=None,
            region="na",
            domain="cars.example.com",
        )
    )

    calls: list[dict] = []

    def fake_request(method: str, url: str, **kwargs):
        calls.append({"method": method, "url": url, "kwargs": kwargs})
        assert method == "POST"
        assert url == "https://fleet-auth.prd.vn.cloud.tesla.com/oauth2/v3/token"
        data = kwargs["data"]
        assert data["grant_type"] == "authorization_code"
        assert data["audience"] == "https://fleet-api.prd.na.vn.cloud.tesla.com"
        assert data["code"] == "auth-code"
        return make_response(
            method,
            url,
            json_body={
                    "access_token": "test-access-1",
                    "refresh_token": "test-refresh-1",
                "expires_in": 3600,
                "scope": "openid offline_access vehicle_cmds",
                "token_type": "Bearer",
            },
        )

    monkeypatch.setattr(client.httpx, "request", fake_request)

    login_spec = next(spec for spec in runtime.list_tool_specs() if spec.name == "tescmd_auth_login")
    start_payload = json.loads(runtime.make_handler(login_spec)({}))
    assert start_payload["ok"] is True
    parsed = urlparse(start_payload["auth_url"])
    query = parse_qs(parsed.query)
    assert parsed.netloc == "auth.tesla.com"
    assert query["client_id"] == ["client-123"]
    assert query["redirect_uri"] == ["https://cars.example.com/callback"]
    assert "state" in query

    complete_spec = next(spec for spec in runtime.list_tool_specs() if spec.name == "tescmd_auth_complete")
    callback_url = "https://cars.example.com/callback?" + "code=" + "auth-code" + f"&state={query['state'][0]}"
    complete_payload = json.loads(runtime.make_handler(complete_spec)({"callback_url": callback_url, "confirm": True}))

    assert complete_payload["ok"] is True
    token_state = config.load_auth_state("default")
    assert token_state.access_token == "test-access-1"
    assert token_state.refresh_token == "test-refresh-1"
    assert token_state.region == "na"
    assert token_state.scopes == ["openid", "offline_access", "vehicle_cmds"]
    assert calls


def test_auth_refresh_export_import_and_status(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    config.save_config(config.PluginConfig(profile="default", client_id="client-123", region="na"))
    config.save_auth_state(
        config.AuthState(
            profile="default",
            access_token="access-old",
            refresh_token="refresh-old",
            expires_at=1234,
            scopes=["openid"],
            region="na",
        )
    )

    def fake_request(method: str, url: str, **kwargs):
        assert method == "POST"
        assert url == "https://fleet-auth.prd.vn.cloud.tesla.com/oauth2/v3/token"
        data = kwargs["data"]
        assert data["grant_type"] == "refresh_token"
        assert data["audience"] == "https://fleet-api.prd.na.vn.cloud.tesla.com"
        assert data["refresh_token"] == "refresh-old"
        return make_response(
            method,
            url,
            json_body={
                    "access_token": "test-access-new",
                    "refresh_token": "test-refresh-new",
                "expires_in": 7200,
                "scope": "openid vehicle_cmds",
                "token_type": "Bearer",
            },
        )

    monkeypatch.setattr(client.httpx, "request", fake_request)

    refresh_spec = next(spec for spec in runtime.list_tool_specs() if spec.name == "tescmd_auth_refresh")
    refresh_payload = json.loads(runtime.make_handler(refresh_spec)({"confirm": True}))
    assert refresh_payload["ok"] is True
    assert config.load_auth_state("default").access_token == "test-access-new"

    export_spec = next(spec for spec in runtime.list_tool_specs() if spec.name == "tescmd_auth_export")
    exported = json.loads(runtime.make_handler(export_spec)({"confirm": True}))
    assert exported["ok"] is True
    assert "auth" not in exported
    blob = json.loads(Path(exported["exported_to"]).read_text())

    config.clear_auth_state("default")

    import_spec = next(spec for spec in runtime.list_tool_specs() if spec.name == "tescmd_auth_import")
    imported = json.loads(runtime.make_handler(import_spec)({"auth": blob, "confirm": True}))
    assert imported["ok"] is True

    status_spec = next(spec for spec in runtime.list_tool_specs() if spec.name == "tescmd_auth_status")
    status = json.loads(runtime.make_handler(status_spec)({}))
    assert status["ok"] is True
    assert status["configured"] is True
    assert "access-old" not in json.dumps(status)
    assert "test-access-new" not in json.dumps(status)
    assert status["authenticated"] is True
    assert status["profile"] == "default"
    assert status["region"] == "na"


def test_auth_import_rejects_invalid_payloads(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    spec = next(spec for spec in runtime.list_tool_specs() if spec.name == "tescmd_auth_import")

    payload = json.loads(runtime.make_handler(spec)({"auth": []}))
    assert payload["ok"] is False
    assert "JSON object" in payload["error"]


def test_corrupted_persisted_config_returns_controlled_error(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    plugin_home = config.get_plugin_home()
    (plugin_home / "config.json").write_text("{bad json")

    spec = next(spec for spec in runtime.list_tool_specs() if spec.name == "tescmd_auth_status")
    payload = json.loads(runtime.make_handler(spec)({}))

    assert payload["ok"] is False
    assert "Stored plugin state is corrupted" in payload["error"]


def test_auth_register_uses_partner_token_and_partner_account_endpoint(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    config.save_config(
        config.PluginConfig(
            profile="default",
            client_id="client-123",
            client_secret="secret-abc",
            region="eu",
            domain="cars.example.com",
        )
    )

    calls: list[tuple[str, str, dict]] = []

    def fake_request(method: str, url: str, **kwargs):
        calls.append((method, url, kwargs))
        if url == "https://fleet-auth.prd.vn.cloud.tesla.com/oauth2/v3/token":
            assert kwargs["data"]["grant_type"] == "client_credentials"
            assert kwargs["data"]["audience"] == "https://fleet-api.prd.eu.vn.cloud.tesla.com"
            return make_response(method, url, json_body={"access_token": "partner-token", "expires_in": 3600})

        assert url == "https://fleet-api.prd.eu.vn.cloud.tesla.com/api/1/partner_accounts"
        assert kwargs["headers"]["Authorization"] == "Bearer partner-token"
        assert kwargs["json"] == {"domain": "cars.example.com"}
        return make_response(method, url, json_body={"response": {"domain": "cars.example.com"}})

    monkeypatch.setattr(client.httpx, "request", fake_request)

    spec = next(spec for spec in runtime.list_tool_specs() if spec.name == "tescmd_auth_register")
    payload = json.loads(runtime.make_handler(spec)({"confirm": True}))

    assert payload["ok"] is True
    assert len(calls) == 2


def test_auth_state_decodes_scopes_from_jwt_when_scope_field_missing() -> None:
    claims = base64.urlsafe_b64encode(json.dumps({"scp": ["openid", "vehicle_device_data"]}).encode()).decode().rstrip("=")
    token = f"header.{claims}.signature"

    state = client.auth_state_from_token_response(
        "default",
        "na",
        {"access_token": token, "expires_in": 3600, "token_type": "Bearer"},
    )

    assert state.scopes == ["openid", "vehicle_device_data"]


def test_vehicle_and_command_tools_use_native_fleet_api(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    config.save_config(config.PluginConfig(profile="default", client_id="client-123", region="na", default_vin="5YJ3E1EA7JF000001"))
    config.save_auth_state(
        config.AuthState(
            profile="default",
            access_token="access-1",
            refresh_token="refresh-1",
            expires_at=9999999999,
            scopes=["openid", "vehicle_cmds"],
            region="na",
        )
    )

    calls: list[tuple[str, str, dict]] = []

    def fake_request(method: str, url: str, **kwargs):
        calls.append((method, url, kwargs))
        if url.endswith("/api/1/vehicles") and method == "GET":
            return make_response(method, url, json_body={"response": [{"vin": "5YJ3E1EA7JF000001", "display_name": "Roadster"}]})
        if url.endswith("/api/1/vehicles/5YJ3E1EA7JF000001/vehicle_data") and method == "GET":
            assert kwargs["params"] == {"endpoints": "charge_state;climate_state"}
            return make_response(method, url, json_body={"response": {"state": "online"}})
        if url.endswith("/api/1/vehicles/5YJ3E1EA7JF000001/wake_up") and method == "POST":
            return make_response(method, url, json_body={"response": {"state": "online"}})
        if url.endswith("/api/1/vehicles/fleet_status") and method == "POST":
            assert kwargs["json"] == {"vins": ["5YJ3E1EA7JF000001"]}
            return make_response(method, url, json_body={"response": {"5YJ3E1EA7JF000001": {"state": "online"}}})
        if url.endswith("/api/1/dx/warranty/details") and method == "GET":
            assert kwargs["params"] == {"vin": "5YJ3E1EA7JF000001"}
            return make_response(method, url, json_body={"response": {"warranty": []}})
        raise AssertionError(f"unexpected request: {method} {url}")

    monkeypatch.setattr(client.httpx, "request", fake_request)

    tools = {spec.name: runtime.make_handler(spec) for spec in runtime.list_tool_specs()}

    vehicle_list = json.loads(tools["tescmd_vehicle_list"]({}))
    assert vehicle_list["ok"] is True
    assert vehicle_list["vehicles"][0]["vin"] == "[REDACTED]"

    vehicle_status = json.loads(tools["tescmd_vehicle_status"]({"endpoints": ["charge_state", "climate_state"]}))
    assert vehicle_status["ok"] is True
    assert vehicle_status["data"]["state"] == "online"

    vehicle_wake = json.loads(tools["tescmd_vehicle_wake"]({"confirm": True}))
    assert vehicle_wake["ok"] is True

    fleet_status = json.loads(tools["tescmd_vehicle_fleet_status"]({"vins": ["5YJ3E1EA7JF000001"]}))
    assert fleet_status["ok"] is True
    warranty = json.loads(tools["tescmd_vehicle_warranty"]({}))
    assert warranty["ok"] is True

    redacted_default = config.PluginConfig(profile="redacted", client_id="client-123", region="na", default_vin="1234567890123456")
    config.save_config(redacted_default)
    config.save_auth_state(
        config.AuthState(
            profile="redacted",
            access_token="access-1",
            refresh_token="refresh-1",
            expires_at=9999999999,
            scopes=["openid", "vehicle_device_data"],
            region="na",
        )
    )
    rejected = json.loads(tools["tescmd_vehicle_warranty"]({"profile": "redacted"}))
    assert rejected["ok"] is False
    assert "requires a full 17-character VIN" in rejected["error"]

    urls = [url for _, url, _ in calls]
    assert "https://fleet-api.prd.na.vn.cloud.tesla.com/api/1/vehicles" in urls
    assert "https://fleet-api.prd.na.vn.cloud.tesla.com/api/1/vehicles/5YJ3E1EA7JF000001/vehicle_data" in urls
    assert not any("/command/" in url for url in urls)


def test_command_audit_logs_wake_attempts_and_redacts_target(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    config.save_config(config.PluginConfig(profile="default", client_id="client-123", region="na", default_vin="5YJ3E1EA7JF000001"))
    config.save_auth_state(config.AuthState(profile="default", access_token="access-1", expires_at=9999999999, region="na"))

    requests: list[tuple[str, str]] = []

    def fake_request(method: str, url: str, **kwargs):
        requests.append((method, url))
        if url.endswith("/api/1/vehicles/5YJ3E1EA7JF000001/wake_up") and method == "POST":
            return make_response(method, url, json_body={"response": {"state": "online"}})
        raise AssertionError(f"unexpected request: {method} {url}")

    monkeypatch.setattr(client.httpx, "request", fake_request)
    tools_by_name = {spec.name: runtime.make_handler(spec) for spec in runtime.list_tool_specs()}

    denied = json.loads(tools_by_name["tescmd_vehicle_wake"]({}))
    assert denied["ok"] is False
    assert requests == []

    allowed = json.loads(tools_by_name["tescmd_vehicle_wake"]({"confirm": True}))
    assert allowed["ok"] is True

    audit_payload = json.loads(tools_by_name["tescmd_audit_log"]({"limit": 10}))
    assert audit_payload["ok"] is True
    events = audit_payload["events"]
    assert [event["stage"] for event in events] == ["denied", "attempt", "result"]
    assert all(event["tool"] == "tescmd_vehicle_wake" for event in events)
    assert all(event["wake"] is True for event in events)
    assert all(event["target"] == {"provided": True, "hash": hashlib.sha256(b"5YJ3E1EA7JF000001").hexdigest()[:16], "suffix": "0001"} for event in events)
    assert "5YJ3E1EA7JF000001" not in (tmp_path / "plugins/hermes-tescmd-plugin/audit/commands.jsonl").read_text()
    assert stat.S_IMODE((tmp_path / "plugins/hermes-tescmd-plugin/audit/commands.jsonl").stat().st_mode) == 0o600


def test_full_vin_endpoints_resolve_default_fleet_id_from_vehicle_list(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    config.save_config(config.PluginConfig(profile="default", client_id="client-123", region="na", default_vin="1234567890123456"))
    config.save_auth_state(config.AuthState(profile="default", access_token="access-1", expires_at=9999999999, region="na"))

    def fake_request(method: str, url: str, **kwargs):
        if url.endswith("/api/1/vehicles") and method == "GET":
            return make_response(method, url, json_body={"response": [{"id_s": "1234567890123456", "vin": "5YJ3E1EA7JF000001"}]})
        if url.endswith("/api/1/dx/warranty/details") and method == "GET":
            assert kwargs["params"] == {"vin": "5YJ3E1EA7JF000001"}
            return make_response(method, url, json_body={"response": {"warranty": []}})
        raise AssertionError(f"unexpected request: {method} {url}")

    monkeypatch.setattr(client.httpx, "request", fake_request)
    spec = next(spec for spec in runtime.list_tool_specs() if spec.name == "tescmd_vehicle_warranty")
    payload = json.loads(runtime.make_handler(spec)({}))

    assert payload["ok"] is True


def test_signed_required_commands_do_not_fallback_to_legacy_rest_without_key(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    config.save_config(config.PluginConfig(profile="default", client_id="client-123", region="na", default_vin="5YJ3E1EA7JF000001"))
    config.save_auth_state(
        config.AuthState(
            profile="default",
            access_token="access-1",
            refresh_token="refresh-1",
            expires_at=9999999999,
            scopes=["openid", "vehicle_cmds"],
            region="na",
        )
    )
    calls: list[tuple[str, str, dict]] = []

    def fake_request(method: str, url: str, **kwargs):
        calls.append((method, url, kwargs))
        raise AssertionError(f"signed-required command made an unexpected network request: {method} {url}")

    monkeypatch.setattr(client.httpx, "request", fake_request)
    tools = {spec.name: runtime.make_handler(spec) for spec in runtime.list_tool_specs()}

    for tool_name, args in (
        ("tescmd_security_lock", {"confirm": True}),
        ("tescmd_charge_limit", {"percent": 80, "confirm": True}),
    ):
        payload = json.loads(tools[tool_name](args))
        assert payload["ok"] is False
        assert "Vehicle Command Protocol" in payload["error"]

    assert calls == []


def _build_session_info_bytes(*, counter: int, vehicle_public_key: bytes, epoch: bytes, clock_time: int) -> bytes:
    return b"".join(
        [
            _encode_varint_field(1, counter),
            _encode_length_delimited(2, vehicle_public_key),
            _encode_length_delimited(3, epoch),
            _encode_fixed32_field(4, clock_time),
        ]
    )


def _build_signed_response_for_handshake(client_private_key, vehicle_private_key, *, epoch: bytes, counter: int = 11, clock_time: int = 30) -> str:
    vehicle_public_key = vehicle_private_key.public_key().public_bytes(
        encoding=auth.serialization.Encoding.X962,
        format=auth.serialization.PublicFormat.UncompressedPoint,
    )
    session_info = _build_session_info_bytes(
        counter=counter,
        vehicle_public_key=vehicle_public_key,
        epoch=epoch,
        clock_time=clock_time,
    )
    from hermes_tescmd_plugin.crypto.ecdh import derive_session_key

    session_key = derive_session_key(client_private_key, vehicle_public_key)
    session_info_key = derive_session_info_key(session_key)
    challenge = b"request-uuid-1234"
    metadata = b"".join(
        (
            encode_tlv(TAG_SIGNATURE_TYPE, bytes([6])),
            encode_tlv(TAG_PERSONALIZATION, b"5YJ3E1EA7JF000001"),
            encode_tlv(TAG_CHALLENGE, challenge),
        )
    )
    tag = hmac.new(session_info_key, metadata + b"\xff" + session_info, hashlib.sha256).digest()
    msg = RoutableMessage(
        to_destination=Destination(domain=Domain.DOMAIN_INFOTAINMENT),
        session_info=session_info,
        message_status=MessageStatus(),
        signature_data=SignatureData(session_info_tag=HMACSignatureData(tag=tag)),
        request_uuid=challenge,
    )
    return encode_routable_message(msg)


def _build_signed_success_response() -> str:
    msg = RoutableMessage(
        message_status=MessageStatus(signed_message_fault=MessageFault.ERROR_NONE),
        signature_data=SignatureData(
            signer_identity=KeyIdentity(public_key=b"vehicle-key"),
            hmac_personalized_data=HMACPersonalizedData(epoch=b"epoch", counter=1, expires_at=1, tag=b"ok"),
        ),
    )
    return encode_routable_message(msg)


def test_security_commands_use_signed_command_protocol_and_reuse_session(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    config.save_config(config.PluginConfig(profile="default", client_id="client-123", region="na", default_vin="5YJ3E1EA7JF000001"))
    config.save_auth_state(
        config.AuthState(
            profile="default",
            access_token="access-1",
            refresh_token="refresh-1",
            expires_at=9999999999,
            scopes=["openid", "vehicle_cmds"],
            region="na",
        )
    )
    auth.generate_vehicle_command_keypair("default", domain="cars.example.com")
    client_private_key = client.load_private_key("default")
    vehicle_private_key = auth.ec.generate_private_key(auth.ec.SECP256R1())
    calls: list[tuple[str, str, dict]] = []
    handshake_response = _build_signed_response_for_handshake(client_private_key, vehicle_private_key, epoch=b"epoch-1")
    success_response = _build_signed_success_response()

    def fake_request(method: str, url: str, **kwargs):
        calls.append((method, url, kwargs))
        assert url.endswith("/api/1/vehicles/5YJ3E1EA7JF000001/signed_command")
        if len(calls) == 1:
            return make_response(method, url, json_body={"response": handshake_response})
        return make_response(method, url, json_body={"response": success_response})

    monkeypatch.setattr(client.httpx, "request", fake_request)

    tools = {spec.name: runtime.make_handler(spec) for spec in runtime.list_tool_specs()}
    lock = json.loads(tools["tescmd_security_lock"]({"confirm": True}))
    unlock = json.loads(tools["tescmd_security_unlock"]({"confirm": True}))

    assert lock["ok"] is True
    assert unlock["ok"] is True
    assert len(calls) == 3
    assert all(url.endswith("/signed_command") for _, url, _ in calls)


def test_charge_limit_uses_signed_protocol_when_vehicle_command_key_exists(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    config.save_config(config.PluginConfig(profile="default", client_id="client-123", region="na", default_vin="5YJ3E1EA7JF000001"))
    config.save_auth_state(
        config.AuthState(
            profile="default",
            access_token="access-1",
            refresh_token="refresh-1",
            expires_at=9999999999,
            scopes=["openid", "vehicle_cmds"],
            region="na",
        )
    )
    auth.generate_vehicle_command_keypair("default", domain="cars.example.com")
    client_private_key = client.load_private_key("default")
    vehicle_private_key = auth.ec.generate_private_key(auth.ec.SECP256R1())
    handshake_response = _build_signed_response_for_handshake(client_private_key, vehicle_private_key, epoch=b"epoch-2")
    success_response = _build_signed_success_response()
    calls: list[str] = []

    def fake_request(method: str, url: str, **kwargs):
        calls.append(url)
        assert url.endswith("/api/1/vehicles/5YJ3E1EA7JF000001/signed_command")
        return make_response(method, url, json_body={"response": handshake_response if len(calls) == 1 else success_response})

    monkeypatch.setattr(client.httpx, "request", fake_request)

    tools = {spec.name: runtime.make_handler(spec) for spec in runtime.list_tool_specs()}
    payload = json.loads(tools["tescmd_charge_limit"]({"percent": 80, "confirm": True}))

    assert payload["ok"] is True
    assert len(calls) == 2


def test_runtime_exposes_full_native_command_surface() -> None:
    actual_tools = {spec.name for spec in runtime.list_tool_specs()}

    required_core = {
        "tescmd_status",
        "tescmd_auth_login",
        "tescmd_auth_complete",
        "tescmd_auth_status",
        "tescmd_auth_refresh",
        "tescmd_auth_import",
        "tescmd_auth_export",
        "tescmd_auth_register",
        "tescmd_auth_logout",
        "tescmd_key_generate",
        "tescmd_key_show",
        "tescmd_key_validate",
        "tescmd_key_enroll",
        "tescmd_key_unenroll",
        "tescmd_key_deploy",
        "tescmd_vehicle_list",
        "tescmd_vehicle_get",
        "tescmd_vehicle_status",
        "tescmd_vehicle_info",
        "tescmd_vehicle_location",
        "tescmd_vehicle_wake",
        "tescmd_vehicle_mobile_access",
        "tescmd_vehicle_nearby_chargers",
        "tescmd_vehicle_alerts",
        "tescmd_vehicle_drivers",
        "tescmd_vehicle_release_notes",
        "tescmd_vehicle_service",
        "tescmd_vehicle_specs",
        "tescmd_vehicle_subscriptions",
        "tescmd_vehicle_upgrades",
        "tescmd_vehicle_options",
        "tescmd_vehicle_warranty",
        "tescmd_vehicle_fleet_status",
        "tescmd_vehicle_telemetry_config",
        "tescmd_vehicle_telemetry_create",
        "tescmd_vehicle_telemetry_delete",
        "tescmd_vehicle_telemetry_errors",
        "tescmd_security_status",
        "tescmd_software_status",
        "tescmd_user_me",
        "tescmd_user_region",
        "tescmd_user_orders",
        "tescmd_user_features",
        "tescmd_billing_history",
        "tescmd_billing_sessions",
        "tescmd_billing_invoice",
        "tescmd_energy_list",
        "tescmd_energy_live",
        "tescmd_energy_status",
        "tescmd_energy_backup",
        "tescmd_energy_mode",
        "tescmd_energy_storm",
        "tescmd_energy_tou",
        "tescmd_energy_calendar",
        "tescmd_energy_history",
        "tescmd_energy_off_grid",
        "tescmd_energy_grid_config",
        "tescmd_energy_telemetry",
        "tescmd_partner_public_key",
        "tescmd_partner_telemetry_error_vins",
        "tescmd_partner_telemetry_errors",
        "tescmd_sharing_add_driver",
        "tescmd_sharing_remove_driver",
        "tescmd_sharing_create_invite",
        "tescmd_sharing_list_invites",
        "tescmd_sharing_redeem_invite",
        "tescmd_sharing_revoke_invite",
        "tescmd_raw_get",
        "tescmd_raw_post",
    }

    required_existing_controls = {
        "tescmd_charge_start",
        "tescmd_charge_stop",
        "tescmd_charge_limit",
        "tescmd_climate_start",
        "tescmd_climate_stop",
        "tescmd_security_lock",
        "tescmd_security_unlock",
        "tescmd_navigation_send",
        "tescmd_media_volume_set",
        "tescmd_vehicle_trunk_open",
        "tescmd_vehicle_trunk_close",
        "tescmd_vehicle_window_control",
        "tescmd_vehicle_sunroof_control",
        "tescmd_power_low_power_mode",
        "tescmd_power_keep_accessory_mode",
    }

    assert required_core <= actual_tools
    assert required_existing_controls <= actual_tools
    assert len(actual_tools) >= 150


def test_extended_native_command_tools_use_expected_payloads(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    config.save_config(config.PluginConfig(profile="default", client_id="client-123", region="na", default_vin="5YJ3E1EA7JF000001"))
    config.save_auth_state(
        config.AuthState(
            profile="default",
            access_token="access-1",
            refresh_token="refresh-1",
            expires_at=9999999999,
            scopes=["openid", "vehicle_cmds"],
            region="na",
        )
    )

    calls: list[tuple[str, str, dict]] = []

    def fake_request(method: str, url: str, **kwargs):
        calls.append((method, url, kwargs))
        if url.endswith("/api/1/vehicles/5YJ3E1EA7JF000001/command/set_managed_charger_location") and method == "POST":
            assert kwargs["json"] == {"location": {"lat": 10.0, "lon": 20.0}}
            return make_response(method, url, json_body={"response": {"result": True}})
        if url.endswith("/api/1/vehicles/5YJ3E1EA7JF000001/command/upcoming_calendar_entries") and method == "POST":
            assert kwargs["json"] == {"calendar_data": "meeting @ 9"}
            return make_response(method, url, json_body={"response": {"result": True}})
        raise AssertionError(f"unexpected request: {method} {url}")

    monkeypatch.setattr(client.httpx, "request", fake_request)

    tools_by_name = {spec.name: runtime.make_handler(spec) for spec in runtime.list_tool_specs()}

    amps = json.loads(tools_by_name["tescmd_charge_set_amps"]({"amps": 24, "confirm": True}))
    valet = json.loads(tools_by_name["tescmd_security_valet_mode"]({"enabled": True, "password": "***", "confirm": True}))
    gps = json.loads(tools_by_name["tescmd_navigation_gps"]({"lat": 37.5, "lon": -122.2, "order": 2, "confirm": True}))
    managed_location = json.loads(tools_by_name["tescmd_charge_managed_location_set"]({"lat": 10.0, "lon": 20.0, "confirm": True}))
    calendar = json.loads(tools_by_name["tescmd_vehicle_calendar_upcoming"]({"calendar_data": "meeting @ 9", "confirm": True}))
    volume = json.loads(tools_by_name["tescmd_media_volume_set"]({"volume": 7.5, "confirm": True}))
    clear_schedules = json.loads(tools_by_name["tescmd_charge_schedules_clear"]({"home": True, "work": False, "other": True, "confirm": True}))

    for signed_required in (amps, valet, gps, volume, clear_schedules):
        assert signed_required["ok"] is False
        assert "Vehicle Command Protocol" in signed_required["error"]
    assert managed_location["ok"] is True
    assert calendar["ok"] is True
    urls = [url for _, url, _ in calls]
    assert all("set_charging_amps" not in url and "set_valet_mode" not in url and "navigation_gps_request" not in url and "adjust_volume" not in url and "batch_remove_charge_schedules" not in url for url in urls)


def test_plugin_native_status_logout_and_key_tooling(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    config.save_config(config.PluginConfig(profile="default", client_id="client-123", region="na", domain="cars.example.com"))
    config.save_auth_state(
        config.AuthState(
            profile="default",
            access_token="access-1",
            refresh_token="refresh-1",
            expires_at=9999999999,
            scopes=["openid", "vehicle_cmds"],
            region="na",
        )
    )

    tools_by_name = {spec.name: runtime.make_handler(spec) for spec in runtime.list_tool_specs()}

    key_payload = json.loads(tools_by_name["tescmd_key_generate"]({"confirm": True}))
    assert key_payload["ok"] is True
    assert key_payload["status"] in {"generated", "exists"}

    public_key_path = config.load_config("default").vehicle_command_key_public_path
    assert public_key_path is not None
    public_key_pem = Path(public_key_path).read_text()

    def fake_get(url: str, **kwargs):
        assert url == "https://cars.example.com/.well-known/appspecific/com.tesla.3p.public-key.pem"
        return httpx.Response(200, text=public_key_pem, request=httpx.Request("GET", url))

    monkeypatch.setattr(client.httpx, "get", fake_get)

    status_payload = json.loads(tools_by_name["tescmd_status"]({}))
    assert status_payload["ok"] is True
    assert status_payload["authenticated"] is True
    assert status_payload["key"]["present"] is True

    deploy_payload = json.loads(tools_by_name["tescmd_key_deploy"]({"method": "local", "confirm": True}))
    assert deploy_payload["ok"] is True
    assert deploy_payload["method"] == "local"
    assert Path(deploy_payload["public_key_file"]).read_text() == public_key_pem
    assert "does not run a hosting service" in deploy_payload["message"]

    validate_payload = json.loads(tools_by_name["tescmd_key_validate"]({}))
    assert validate_payload["ok"] is True
    assert validate_payload["accessible"] is True
    assert validate_payload["matches_local_key"] is True

    def mismatch_get(url: str, **kwargs):
        return httpx.Response(200, text="-----BEGIN PUBLIC KEY-----\nDIFFERENT\n-----END PUBLIC KEY-----\n", request=httpx.Request("GET", url))

    monkeypatch.setattr(client.httpx, "get", mismatch_get)
    mismatch_payload = json.loads(tools_by_name["tescmd_key_validate"]({}))
    assert mismatch_payload["accessible"] is False
    assert mismatch_payload["matches_local_key"] is False

    github_payload = json.loads(tools_by_name["tescmd_key_deploy"]({"method": "github"}))
    assert github_payload["ok"] is False
    assert "method must be one of" in github_payload["error"]

    logout_payload = json.loads(tools_by_name["tescmd_auth_logout"]({"confirm": True}))
    assert logout_payload["ok"] is True
    assert config.load_auth_state("default").access_token is None


def test_raw_requests_and_vehicle_status_helpers(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    config.save_config(config.PluginConfig(profile="default", client_id="client-123", region="na", default_vin="5YJ3E1EA7JF000001"))
    config.save_auth_state(
        config.AuthState(
            profile="default",
            access_token="access-1",
            refresh_token="refresh-1",
            expires_at=9999999999,
            scopes=["openid", "vehicle_cmds"],
            region="na",
        )
    )

    def fake_request(method: str, url: str, **kwargs):
        if url.endswith("/api/1/vehicles/5YJ3E1EA7JF000001/vehicle_data"):
            return make_response(method, url, json_body={"response": {"vehicle_state": {"car_version": "2026.8.1", "software_update": {"status": "available"}}, "drive_state": {"latitude": 10.0, "longitude": 20.0}, "closures_state": {"df": 0}, "vehicle_config": {"car_type": "model3"}, "gui_settings": {"gui_distance_units": "mi/hr"}, "charge_schedule_data": {"schedules": []}, "preconditioning_schedule_data": {"schedules": []}}})
        if url.endswith("/api/1/test") and method == "GET":
            assert kwargs["params"] == {"foo": "bar"}
            return make_response(method, url, json_body={"response": {"ok": True}})
        if url.endswith("/api/1/test") and method == "POST":
            assert kwargs["json"] == {"hello": "world"}
            return make_response(method, url, json_body={"response": {"posted": True}})
        if url.endswith("/api/1/vehicles/5YJ3E1EA7JF000001/command/window_control"):
            assert kwargs["json"] == {"command": "close", "lat": 11.0, "lon": 22.0}
            return make_response(method, url, json_body={"response": {"result": True}})
        raise AssertionError(f"unexpected request: {method} {url}")

    monkeypatch.setattr(client.httpx, "request", fake_request)
    tools_by_name = {spec.name: runtime.make_handler(spec) for spec in runtime.list_tool_specs()}

    software = json.loads(tools_by_name["tescmd_software_status"]({}))
    security = json.loads(tools_by_name["tescmd_security_status"]({}))
    drive = json.loads(tools_by_name["tescmd_vehicle_drive_status"]({"no_cache": True}))
    closures = json.loads(tools_by_name["tescmd_vehicle_closures_status"]({"no_cache": True}))
    vehicle_config = json.loads(tools_by_name["tescmd_vehicle_config_status"]({"no_cache": True}))
    gui_settings = json.loads(tools_by_name["tescmd_vehicle_gui_settings"]({"no_cache": True}))
    charge_schedule = json.loads(tools_by_name["tescmd_vehicle_charge_schedule_status"]({"no_cache": True}))
    preconditioning_schedule = json.loads(tools_by_name["tescmd_vehicle_preconditioning_schedule_status"]({"no_cache": True}))
    raw_get = json.loads(tools_by_name["tescmd_raw_get"]({"path": "/api/1/test", "params": {"foo": "bar"}, "confirm": True}))
    raw_post = json.loads(tools_by_name["tescmd_raw_post"]({"path": "/api/1/test", "body": {"hello": "world"}, "confirm": True}))
    window = json.loads(tools_by_name["tescmd_vehicle_window_control"]({"command": "close", "lat": 11.0, "lon": 22.0, "confirm": True}))

    assert software["ok"] is True
    assert software["software"]["car_version"] == "2026.8.1"
    assert security["ok"] is True
    assert drive["drive_state"]["latitude"] == 10.0
    assert closures["closures"]["df"] == 0
    assert vehicle_config["vehicle_config"]["car_type"] == "model3"
    assert gui_settings["gui_settings"]["gui_distance_units"] == "mi/hr"
    assert charge_schedule["charge_schedule"]["schedules"] == []
    assert preconditioning_schedule["preconditioning_schedule"]["schedules"] == []
    assert raw_get["response"]["response"]["ok"] is True
    assert raw_post["response"]["response"]["posted"] is True
    assert window["ok"] is False
    assert "Vehicle Command Protocol" in window["error"]


def test_path_components_and_vehicle_ids_are_validated_before_network(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    config.save_config(config.PluginConfig(profile="default", client_id="client-123", region="na", default_vin="BAD/VIN"))
    config.save_auth_state(config.AuthState(profile="default", access_token="access-1", expires_at=9999999999, scopes=["vehicle_cmds"], region="na"))
    calls: list[tuple[str, str, dict]] = []

    def fake_request(method: str, url: str, **kwargs):
        calls.append((method, url, kwargs))
        return make_response(method, url, json_body={"response": {"ok": True}})

    monkeypatch.setattr(client.httpx, "request", fake_request)
    tools_by_name = {spec.name: runtime.make_handler(spec) for spec in runtime.list_tool_specs()}

    bad_vin = json.loads(tools_by_name["tescmd_vehicle_status"]({}))
    assert bad_vin["ok"] is False
    assert "Vehicle identifier must be" in bad_vin["error"]
    assert calls == []

    bad_invoice = json.loads(tools_by_name["tescmd_billing_invoice"]({"invoice_id": "../invoice"}))
    assert bad_invoice["ok"] is False
    assert "invoice_id contains invalid characters" in bad_invoice["error"]
    assert calls == []


def test_china_region_uses_tesla_cn_fleet_domain():
    assert client.fleet_base_url("cn") == "https://fleet-api.prd.cn.vn.cloud.tesla.cn"


def test_oauth_urls_match_tesla_fleet_api_docs():
    assert client.AUTH_BASE_URL == "https://auth.tesla.com/oauth2/v3"
    assert client.TOKEN_URL == "https://fleet-auth.prd.vn.cloud.tesla.com/oauth2/v3/token"
    assert auth.AUTHORIZE_URL == "https://auth.tesla.com/oauth2/v3/authorize"


def test_high_risk_vehicle_commands_require_confirm_before_network_call(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    config.save_config(config.PluginConfig(profile="default", client_id="client-123", region="na", default_vin="5YJ3E1EA7JF000001"))
    config.save_auth_state(config.AuthState(profile="default", access_token="access-1", expires_at=9999999999, scopes=["vehicle_cmds"], region="na"))

    calls = []

    def fake_request(method: str, url: str, **kwargs):
        calls.append((method, url, kwargs))
        return make_response(method, url, json_body={"response": {"result": True}})

    monkeypatch.setattr(client.httpx, "request", fake_request)
    tools_by_name = {spec.name: runtime.make_handler(spec) for spec in runtime.list_tool_specs()}

    denied = json.loads(tools_by_name["tescmd_security_unlock"]({}))
    assert denied["ok"] is False
    assert "confirm=true" in denied["error"]
    assert calls == []

    allowed = json.loads(tools_by_name["tescmd_security_unlock"]({"confirm": True}))
    assert allowed["ok"] is False
    assert "Vehicle Command Protocol" in allowed["error"]
    assert calls == []


def test_every_confirm_required_tool_denies_before_network_without_confirm(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    config.save_config(config.PluginConfig(profile="default", client_id="client-123", client_secret="secret-abc", region="na", default_vin="5YJ3E1EA7JF000001", domain="cars.example.com"))
    config.save_auth_state(config.AuthState(profile="default", access_token="access-1", refresh_token="refresh-1", expires_at=9999999999, scopes=["openid", "vehicle_cmds", "energy_cmds"], region="na"))
    network_calls = []

    def fake_request(method: str, url: str, **kwargs):
        network_calls.append((method, url, kwargs))
        return make_response(method, url, json_body={"response": {"ok": True}})

    monkeypatch.setattr(client.httpx, "request", fake_request)
    specs = runtime.list_tool_specs()
    handlers = {spec.name: runtime.make_handler(spec) for spec in specs}

    def dummy(param: runtime.ParamSpec):
        if param.name == "confirm":
            raise AssertionError("confirm should be omitted")
        if param.name == "profile":
            return "default"
        if param.name == "region":
            return "na"
        if param.name in {"vin", "vins"}:
            return ["5YJ3E1EA7JF000001"] if param.is_array else "5YJ3E1EA7JF000001"
        if param.name in {"site_id", "id", "share_user_id", "start_time", "end_time", "charging_time", "departure_time", "time_minutes", "days_of_week", "off_peak_hours_end_time", "preconditioning_times"}:
            return 1
        if param.name in {"lat", "lon", "driver_temp", "passenger_temp", "volume"}:
            return 1.0
        if param.name in {"percent", "amps", "level", "reserve"}:
            return 80
        if param.name in {"enabled", "home", "work", "other", "manual_override"}:
            return True
        if param.name in {"path", "output_path"}:
            return "/api/1/test" if param.name == "path" else "confirm-denied.json"
        if param.name in {"body", "params", "config", "settings"}:
            return {"example": True}
        if param.name in {"place_ids", "scopes", "endpoints"}:
            return ["example"]
        if param.name == "callback_url":
            return "https://cars.example.com/callback?code=code&state=state"
        if param.name == "method":
            return "local"
        if param.enum:
            return param.enum[0]
        return "example"

    checked = 0
    failures = []
    for spec in specs:
        if not any(param.name == "confirm" and param.required for param in spec.params):
            continue
        args = {param.name: dummy(param) for param in spec.params if param.required and param.name != "confirm"}
        result = json.loads(handlers[spec.name](args))
        checked += 1
        if result.get("ok") is not False or "confirm=true" not in result.get("error", ""):
            failures.append({"tool": spec.name, "result": result})
    assert checked >= 100
    assert failures == []
    assert network_calls == []


def test_raw_post_requires_confirm_and_rejects_non_api_paths(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    config.save_config(config.PluginConfig(profile="default", client_id="client-123", region="na"))
    config.save_auth_state(config.AuthState(profile="default", access_token="access-1", expires_at=9999999999, scopes=["vehicle_cmds"], region="na"))

    calls = []

    def fake_request(method: str, url: str, **kwargs):
        calls.append((method, url, kwargs))
        return make_response(method, url, json_body={"response": {"posted": True}})

    monkeypatch.setattr(client.httpx, "request", fake_request)
    tools_by_name = {spec.name: runtime.make_handler(spec) for spec in runtime.list_tool_specs()}

    denied = json.loads(tools_by_name["tescmd_raw_post"]({"path": "/api/1/test", "body": {"hello": "world"}}))
    assert denied["ok"] is False
    assert "confirm=true" in denied["error"]
    assert calls == []

    bad_path = json.loads(tools_by_name["tescmd_raw_post"]({"path": "https://evil.example/api/1/test", "confirm": True}))
    assert bad_path["ok"] is False
    assert "starting with /api/" in bad_path["error"]
    assert calls == []

    allowed = json.loads(tools_by_name["tescmd_raw_post"]({"path": "/api/1/test", "body": {"hello": "world"}, "confirm": True}))
    assert allowed["ok"] is True
    assert calls and calls[0][1].endswith("/api/1/test")


def test_handler_redacts_secrets_from_errors(monkeypatch) -> None:
    def explode(spec, args):
        raise client.TeslaAPIError(
            "request failed Authorization: Bearer secret-access access_token=secret-access client_secret=secret-secret",
            status_code=401,
            payload={
                "access_token": "secret-access",
                "nested": {"refresh_token": "secret-refresh"},
                "message": "client_secret=secret-secret",
            },
        )

    monkeypatch.setattr(runtime.tools, "execute", explode)
    spec = next(spec for spec in runtime.list_tool_specs() if spec.name == "tescmd_vehicle_list")
    payload_text = runtime.make_handler(spec)({})

    assert "secret-access" not in payload_text
    assert "secret-refresh" not in payload_text
    assert "secret-secret" not in payload_text
    payload = json.loads(payload_text)
    assert payload["ok"] is False
    assert payload["payload"]["access_token"] == "[REDACTED]"
    assert payload["payload"]["nested"]["refresh_token"] == "[REDACTED]"


def test_account_and_energy_mutations_require_confirm_before_network_call(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    config.save_config(config.PluginConfig(profile="default", client_id="client-123", region="na", default_vin="5YJ3E1EA7JF000001"))
    config.save_auth_state(config.AuthState(profile="default", access_token="access-1", expires_at=9999999999, scopes=["vehicle_cmds", "energy_cmds"], region="na"))

    calls = []

    def fake_request(method: str, url: str, **kwargs):
        calls.append((method, url, kwargs))
        return make_response(method, url, json_body={"response": {"ok": True}})

    monkeypatch.setattr(client.httpx, "request", fake_request)
    tools_by_name = {spec.name: runtime.make_handler(spec) for spec in runtime.list_tool_specs()}

    denied_driver = json.loads(tools_by_name["tescmd_sharing_add_driver"]({"email": "driver@example.com"}))
    assert denied_driver["ok"] is False
    assert "confirm=true" in denied_driver["error"]

    denied_energy = json.loads(tools_by_name["tescmd_energy_backup"]({"site_id": 42, "percent": 25}))
    assert denied_energy["ok"] is False
    assert "confirm=true" in denied_energy["error"]

    denied_telemetry = json.loads(tools_by_name["tescmd_vehicle_telemetry_create"]({"config": {"hostname": "telemetry.example.com"}}))
    assert denied_telemetry["ok"] is False
    assert "confirm=true" in denied_telemetry["error"]
    assert calls == []

    allowed_driver = json.loads(tools_by_name["tescmd_sharing_add_driver"]({"email": "driver@example.com", "confirm": True}))
    allowed_energy = json.loads(tools_by_name["tescmd_energy_backup"]({"site_id": 42, "percent": 25, "confirm": True}))
    allowed_telemetry = json.loads(tools_by_name["tescmd_vehicle_telemetry_create"]({"config": {"hostname": "telemetry.example.com"}, "confirm": True}))
    assert allowed_driver["ok"] is True
    assert allowed_energy["ok"] is True
    assert allowed_telemetry["ok"] is True
    assert len(calls) == 3



def test_schema_is_closed_and_marks_sensitive_inputs() -> None:
    specs = {spec.name: spec for spec in runtime.list_tool_specs()}
    auth_complete_schema = schemas.build_schema(specs["tescmd_auth_complete"])
    assert auth_complete_schema["parameters"]["additionalProperties"] is False
    assert auth_complete_schema["parameters"]["properties"]["code"]["x-sensitive"] is True
    assert auth_complete_schema["parameters"]["properties"]["code"]["writeOnly"] is True
    vehicle_schema = schemas.build_schema(specs["tescmd_vehicle_status"])
    assert vehicle_schema["parameters"]["properties"]["vin"]["x-sensitive"] is True
    place_schema = schemas.build_schema(specs["tescmd_navigation_place_search"])
    assert place_schema["parameters"]["additionalProperties"] is False


def test_domain_validation_and_key_overwrite_guards(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    tools_by_name = {spec.name: runtime.make_handler(spec) for spec in runtime.list_tool_specs()}

    try:
        config.save_config(config.PluginConfig(profile="default", client_id="client-123", domain="https://cars.example.com/path"))
    except Exception as exc:
        assert "hostname only" in str(exc)
    else:
        raise AssertionError("invalid domain should be rejected")

    config.save_config(config.PluginConfig(profile="default", client_id="client-123", domain="cars.example.com"))
    generated = json.loads(tools_by_name["tescmd_key_generate"]({"confirm": True}))
    assert generated["ok"] is True
    blocked = json.loads(tools_by_name["tescmd_key_generate"]({"confirm": True}))
    assert blocked["ok"] is True
    assert blocked["status"] == "exists"
    forced = json.loads(tools_by_name["tescmd_key_generate"]({"force": True, "confirm": True}))
    assert forced["ok"] is True
    assert forced["status"] == "generated"


def test_auth_export_requires_confirm_and_never_returns_token_blob(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    config.save_config(config.PluginConfig(profile="default", client_id="client-123", region="na"))
    config.save_auth_state(config.AuthState(profile="default", access_token="test-access", refresh_token="test-refresh", expires_at=9999999999, scopes=["vehicle_cmds"], region="na"))
    tools_by_name = {spec.name: runtime.make_handler(spec) for spec in runtime.list_tool_specs()}

    denied = json.loads(tools_by_name["tescmd_auth_export"]({}))
    assert denied["ok"] is False
    assert "confirm=true" in denied["error"]

    exported = json.loads(tools_by_name["tescmd_auth_export"]({"confirm": True}))
    assert exported["ok"] is True
    assert "auth" not in exported
    assert "test-access" not in json.dumps(exported)
    export_path = Path(exported["exported_to"])
    assert export_path.exists()
    assert export_path.stat().st_mode & 0o777 == 0o600


def test_signed_command_rejects_non_ok_operation_status(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    config.save_config(config.PluginConfig(profile="default", client_id="client-123", region="na", default_vin="5YJ3E1EA7JF000001"))
    config.save_auth_state(config.AuthState(profile="default", access_token="access-1", refresh_token="refresh-1", expires_at=9999999999, scopes=["vehicle_cmds"], region="na"))
    auth.generate_vehicle_command_keypair("default", domain="cars.example.com")
    client_private_key = client.load_private_key("default")
    vehicle_private_key = auth.ec.generate_private_key(auth.ec.SECP256R1())
    handshake_response = _build_signed_response_for_handshake(client_private_key, vehicle_private_key, epoch=b"epoch-op")
    failed_response = encode_routable_message(RoutableMessage(message_status=MessageStatus(operation_status=OperationStatus.OPERATIONSTATUS_ERROR)))
    calls: list[str] = []

    def fake_request(method: str, url: str, **kwargs):
        calls.append(url)
        return make_response(method, url, json_body={"response": handshake_response if len(calls) == 1 else failed_response})

    monkeypatch.setattr(client.httpx, "request", fake_request)
    tools_by_name = {spec.name: runtime.make_handler(spec) for spec in runtime.list_tool_specs()}
    payload = json.loads(tools_by_name["tescmd_security_lock"]({"confirm": True}))
    assert payload["ok"] is False
    assert "OPERATIONSTATUS_ERROR" in payload["error"]


def test_unknown_vehicle_command_fails_closed_before_network(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    config.save_config(config.PluginConfig(profile="default", client_id="client-123", region="na"))
    config.save_auth_state(config.AuthState(profile="default", access_token="access-1", region="na"))
    fleet = client.TeslaFleetClient(profile="default")

    def fail_request(*args, **kwargs):
        raise AssertionError("unknown vehicle command should not make a network request")

    monkeypatch.setattr(client.httpx, "request", fail_request)
    with pytest.raises(client.TeslaAPIError, match="No vehicle-command registry entry"):
        fleet.vehicle_command("5YJ3E1EA7JF000001", "unregistered_future_command", {})


def test_runtime_redacts_key_paths_and_cache_keys(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    config.save_config(config.PluginConfig(profile="default", client_id="client-123", region="na", domain="cars.example.com", default_vin="5YJ3E1EA7JF000001"))
    config.save_auth_state(config.AuthState(profile="default", access_token="access-1", region="na"))
    tools_by_name = {spec.name: runtime.make_handler(spec) for spec in runtime.list_tool_specs()}

    generated = json.loads(tools_by_name["tescmd_key_generate"]({"confirm": True}))
    shown = json.loads(tools_by_name["tescmd_key_show"]({}))
    assert generated["ok"] is True
    assert shown["ok"] is True
    rendered_keys = json.dumps({"generated": generated, "shown": shown})
    assert "private_key_path" not in rendered_keys
    assert "vehicle-command-key.pem" not in rendered_keys
    assert generated["private_key_present"] is True
    assert shown["private_key_present"] is True

    def fake_status(self, vin, endpoints=None):
        return {"charge_state": {"battery_level": 88}}

    monkeypatch.setattr(client.TeslaFleetClient, "vehicle_status", fake_status)
    status = json.loads(tools_by_name["tescmd_vehicle_status"]({"endpoints": ["charge_state"]}))
    assert status["ok"] is True
    assert "key" not in status["cache"]


def test_tesla_api_error_sanitizes_sensitive_payloads() -> None:
    exc = client.TeslaAPIError(
        "token endpoint failed",
        payload={
            "access_token": "access-secret",
            "refresh_token": "refresh-secret",
            "nested": {"client_secret": "client-secret", "error": "invalid_scope"},
        },
    )
    rendered = json.dumps(exc.payload)
    assert "access-secret" not in rendered
    assert "refresh-secret" not in rendered
    assert "client-secret" not in rendered
    assert "invalid_scope" in rendered
