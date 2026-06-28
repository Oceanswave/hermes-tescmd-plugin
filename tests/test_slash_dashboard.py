from __future__ import annotations

import json
from pathlib import Path

import pytest

from hermes_tescmd_plugin import config, slash, tools as tescmd_tools
from hermes_tescmd_plugin.dashboard import ensure_dashboard_installed
from hermes_tescmd_plugin.dashboard.plugin_api import (
    DefaultVehicleBody,
    QuickActionBody,
    _dashboard_display_payload,
    _command_safety_filters,
    _overview_read_context,
    _overview_section_health,
    _overview_target_context,
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


def test_slash_args_parse_double_dash_flags_without_positional_confusion() -> None:
    args = slash.parse_args(
        "--confirm --wake --no-cache --region=na --percent:80",
    )

    assert args == {
        "confirm": True,
        "wake": True,
        "no_cache": True,
        "region": "na",
        "percent": 80,
    }


def test_slash_args_parse_negated_double_dash_booleans() -> None:
    args = slash.parse_args(
        "--no-confirm --no-wake --no-cache --region=na",
    )

    assert args == {
        "confirm": False,
        "wake": False,
        "no_cache": True,
        "region": "na",
    }


def test_slash_args_parse_valued_negated_double_dash_booleans() -> None:
    args = slash.parse_args(
        "--no-confirm=true --no-wake:true --no-cache=true --region=na",
    )

    assert args == {
        "confirm": False,
        "wake": False,
        "no_cache": True,
        "region": "na",
    }


def test_slash_args_parse_false_valued_negated_double_dash_booleans_as_enabled() -> (
    None
):
    args = slash.parse_args("--no-confirm=false --no-wake:false")

    assert args == {"confirm": True, "wake": True}


def test_slash_args_parse_separated_double_dash_option_values() -> None:
    args = slash.parse_args(
        "5YJ3E1EA7JF000001 --percent 80 --driver-temp 70 --passenger-temp 71 "
        "--endpoints charge_state,drive_state --confirm false",
    )

    assert args == {
        "vin": "5YJ3E1EA7JF000001",
        "percent": 80,
        "driver_temp": 70,
        "passenger_temp": 71,
        "endpoints": ["charge_state", "drive_state"],
        "confirm": False,
    }


def test_slash_args_separated_booleans_do_not_consume_positional_vin() -> None:
    args = slash.parse_args("--confirm 5YJ3E1EA7JF000001 --wake")

    assert args == {
        "confirm": True,
        "vin": "5YJ3E1EA7JF000001",
        "wake": True,
    }


def test_slash_args_preserve_destination_when_double_dash_flags_are_present() -> None:
    args = slash.parse_args(
        "'123 Main St' --confirm --order=replace",
        positional_name="destination",
    )

    assert args == {
        "destination": "123 Main St",
        "confirm": True,
        "order": "replace",
    }


def test_malformed_slash_args_return_friendly_error_without_running_tool(
    monkeypatch,
) -> None:
    spec = slash.runtime.ToolSpec(
        name="tescmd_navigation_send",
        description="Send navigation destination.",
        operation="navigation_send",
    )

    def fail_handler(_args: dict) -> str:
        raise AssertionError("malformed slash arguments should not run tool handlers")

    monkeypatch.setattr(slash.runtime, "list_tool_specs", lambda: [spec])
    monkeypatch.setattr(slash.runtime, "make_handler", lambda _spec: fail_handler)

    result = slash._run_tool(  # noqa: SLF001
        "tescmd_navigation_send",
        "'123 Main St confirm=true",
        positional_name="destination",
    )
    output = slash._format_command("tescmd-nav", result)  # noqa: SLF001

    assert result["ok"] is False
    assert "Could not parse slash-command arguments" in output
    assert "balanced quotes" in output
    assert "Try: Re-run the slash command" in output
    assert "123 Main" not in output


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


def test_navigation_search_slash_summary_redacts_route_target_details() -> None:
    output = slash._format_command(  # noqa: SLF001
        "tescmd-nav-search",
        {
            "ok": True,
            "places": [
                {
                    "id": "ChIJN1t_tDeuEmsRUsoyG83frY4",
                    "display_name": {"text": "Central Coffee"},
                    "formatted_address": "123 Main St, Austin, TX 78701",
                    "location": {"latitude": 30.267153, "longitude": -97.743057},
                },
                {
                    "name": "places/ChIJRouteTargetPlaceId123456789",
                    "formatted_address": "456 Secret Ave, Austin, TX 78702",
                    "location": {"lat": 30.268, "lng": -97.744},
                },
            ],
        },
    )

    assert "Navigation search: 2 place candidate(s) returned." in output
    assert "#1 Central Coffee (address/location redacted)" in output
    assert "#2 Unnamed place (address/location redacted)" in output
    assert "place_ids=..." in output
    assert "123 Main St" not in output
    assert "456 Secret Ave" not in output
    assert "ChIJN1t_tDeuEmsRUsoyG83frY4" not in output
    assert "ChIJRouteTargetPlaceId123456789" not in output
    assert "30.267153" not in output
    assert "-97.743057" not in output


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


def test_run_tool_navigation_keeps_destination_when_separated_options_follow(
    monkeypatch,
) -> None:
    captured: dict = {}
    spec = slash.runtime.ToolSpec(
        name="tescmd_navigation_place_search",
        description="Search navigation places.",
        operation="navigation_place_search",
    )

    def fake_handler(args: dict) -> str:
        captured.update(args)
        return json.dumps({"ok": True, "places": []})

    monkeypatch.setattr(slash.runtime, "list_tool_specs", lambda: [spec])
    monkeypatch.setattr(slash.runtime, "make_handler", lambda _spec: fake_handler)

    result = slash._run_tool(
        "tescmd_navigation_place_search",
        "coffee shop --limit 3 --region na",
        positional_name="query",
    )

    assert result["ok"] is True
    assert captured == {
        "query": "coffee shop",
        "limit": 3,
        "region": "na",
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
        "tescmd-charge-schedule",
        "tescmd-preconditioning-schedule",
        "tescmd-security-status",
        "tescmd-software",
        "tescmd-nearby-chargers",
        "tescmd-alerts",
        "tescmd-drivers",
        "tescmd-release-notes",
        "tescmd-mobile-access",
        "tescmd-energy",
        "tescmd-service",
        "tescmd-warranty",
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
    assert (
        by_name["tescmd-nav"]["args_hint"]
        == "'address or place' [vin=...] confirm=true"
    )
    assert "vin=..." in by_name["tescmd-nav"]["description"]
    assert by_name["tescmd-nav-search"]["args_hint"] == "'address or place' [limit=5]"

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


def test_cache_status_reports_privacy_safe_freshness_counts(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    now = 1_800_000_000
    monkeypatch.setattr(config.time, "time", lambda: now - 30)
    current = config.save_cache_entry(
        "daily", "raw-cache-key-current", {"vin": "5YJ3E1EA7JF000001"}, ttl_seconds=120
    )
    monkeypatch.setattr(config.time, "time", lambda: now - 600)
    expired = config.save_cache_entry(
        "daily", "raw-cache-key-expired", {"vin": "5YJ3E1EA7JF000002"}, ttl_seconds=60
    )
    monkeypatch.setattr(config.time, "time", lambda: now)

    assert current.expires_at is not None
    status = config.cache_status("daily")

    assert status == {
        "enabled": True,
        "entries": 1,
        "expired_entries": 1,
        "total_entries": 2,
        "newest_age_seconds": now - current.created_at,
        "oldest_age_seconds": now - expired.created_at,
        "next_expiry_seconds": current.expires_at - now,
    }
    assert "raw-cache-key" not in json.dumps(status)
    assert "5YJ3E1EA" not in json.dumps(status)


def test_cache_status_slash_output_summarizes_counts_without_raw_payload() -> None:
    output = slash._format_command(  # noqa: SLF001
        "tescmd-cache-status",
        {
            "ok": True,
            "profile": "daily-5YJ3E1EA7JF000001",
            "enabled": True,
            "entries": 0,
            "expired_entries": 1,
            "message": "Plugin-native response cache for selected read-only Fleet API calls.",
            "path": "/tmp/hermes/plugins/hermes-tescmd-plugin/response-cache.json",
        },
    )

    assert output.startswith("/tescmd-cache-status: success")
    assert "Context: profile daily-…0001" in output
    assert "Cache: enabled, 0 current entries, 1 expired entry" in output
    assert "local cache may contain sensitive vehicle snapshots" in output
    assert "response-cache.json" not in output
    assert "5YJ3E1EA7JF000001" not in output


def test_key_show_slash_output_summarizes_readiness_without_paths_or_urls() -> None:
    output = slash._format_command(  # noqa: SLF001
        "tescmd-key-show",
        {
            "ok": True,
            "profile": "default",
            "status": "found",
            "private_key_present": True,
            "public_key_path": "/tmp/hermes/plugins/hermes-tescmd-plugin/keys/default/public.pem",
            "fingerprint": "SHA256:abc123",
            "expected_public_key_url": "https://cars.example.com/.well-known/appspecific/com.tesla.3p.public-key.pem",
            "enrollment_url": "https://tesla.com/_ak/cars.example.com",
        },
    )

    assert output.startswith("/tescmd-key-show: success")
    assert "Vehicle-command key: found" in output
    assert "private key present" in output
    assert "public key present" in output
    assert "fingerprint SHA256:abc123" in output
    assert "public-key URL configured" in output
    assert "enrollment URL available" in output
    assert "Result: command accepted by Tesla Fleet API" not in output
    assert "public.pem" not in output
    assert "cars.example.com" not in output
    assert "tesla.com/_ak" not in output
    assert "{" not in output


def test_key_validate_slash_output_summarizes_hosting_without_url_leak() -> None:
    output = slash._format_command(  # noqa: SLF001
        "tescmd-key-validate",
        {
            "ok": True,
            "profile": "setup-5YJ3E1EA7JF000001",
            "domain": "cars.example.com",
            "url": "https://cars.example.com/.well-known/appspecific/com.tesla.3p.public-key.pem",
            "accessible": False,
            "matches_local_key": False,
            "local_fingerprint": "SHA256:local",
            "remote_fingerprint": None,
        },
    )

    assert output.startswith("/tescmd-key-validate: success")
    assert "Context: profile setup-…0001" in output
    assert "Vehicle-command key hosting: hosted key not reachable" in output
    assert "does not match local key" in output
    assert "local fingerprint SHA256:local" in output
    assert "Result: command accepted by Tesla Fleet API" not in output
    assert "cars.example.com" not in output
    assert "public-key.pem" not in output
    assert "5YJ3E1EA7JF000001" not in output
    assert "{" not in output


def test_key_slash_output_suppresses_path_or_url_messages() -> None:
    output = slash._format_command(  # noqa: SLF001
        "tescmd-key-validate",
        {
            "ok": True,
            "profile": "default",
            "accessible": True,
            "matches_local_key": True,
            "local_fingerprint": "SHA256:local",
            "remote_fingerprint": "SHA256:remote",
            "message": (
                "Fetched /tmp/hermes/plugins/hermes-tescmd-plugin/keys/default/public.pem "
                "from https://cars.example.com/.well-known/appspecific/com.tesla.3p.public-key.pem"
            ),
        },
    )

    assert "Vehicle-command key hosting: hosted key reachable" in output
    assert "matches local key" in output
    assert "Result:" not in output
    assert "/tmp/hermes" not in output
    assert "cars.example.com" not in output
    assert "public-key.pem" not in output
    assert "{" not in output


def test_cache_clear_slash_output_reports_cleared_count() -> None:
    output = slash._format_command(  # noqa: SLF001
        "tescmd-cache-clear",
        {"ok": True, "profile": "default", "enabled": True, "cleared": 1},
    )

    assert output.startswith("/tescmd-cache-clear: success")
    assert "Cache: cleared 1 cached response." in output
    assert "Result: command accepted by Tesla Fleet API" not in output
    assert "{" not in output


def test_energy_slash_output_summarizes_product_types_and_hidden_count() -> None:
    output = slash._format_command(  # noqa: SLF001
        "tescmd-energy",
        {
            "ok": True,
            "profile": "energy-5YJ3E1EA7JF000001",
            "products": [
                {
                    "site_name": "Home Battery",
                    "resource_type": "battery",
                    "site_id": "12345678901234567",
                    "postal_code": "78701",
                    "latitude": 30.267153,
                },
                {"energy_site_name": "Solar Roof", "resource_type": "solar"},
                {"asset_site_name": "Backup Battery", "asset_type": "battery"},
                {"name": "Wall Connector", "device_type": "wall_connector"},
            ],
        },
    )

    assert output.startswith("/tescmd-energy: success")
    assert "Context: profile energy-…0001" in output
    assert "Energy products: 4 product(s) returned." in output
    assert "Energy product types: battery=2, solar=1, wall connector=1" in output
    assert "Top products: #1 Home Battery (type battery, site …4567)" in output
    assert "Energy products: 1 additional product(s) hidden." in output
    assert "use site_id=... with tescmd_energy_live/status" in output
    assert "12345678901234567" not in output
    assert "5YJ3E1EA7JF000001" not in output
    assert "78701" not in output
    assert "30.267153" not in output
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
                "Open https://cars.example.com/callback#code=oauth-code-123456&state=oauth-state-123456.",
                "Do not paste Bearer secret-token-123456 or client_secret=client-secret-123456 into chat.",
            ],
            "scope_readiness": {
                "configured_user_scopes": [
                    "openid",
                    "offline_access",
                    "vehicle_device_data",
                    "vehicle_cmds",
                ],
                "granted_user_scopes": ["openid", "offline_access"],
                "missing_granted_user_scopes": [
                    "vehicle_device_data",
                    "vehicle_cmds",
                ],
            },
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
    assert "#code=[REDACTED]&state=[REDACTED]" in output
    assert "client_secret=[REDACTED]" in output
    assert "Scopes: configured=4, granted=2, missing=2" in output
    assert "Missing scopes: vehicle_device_data, vehicle_cmds" in output
    assert "authenticated=no" in output
    assert "ready_for_vehicle_commands=no" in output
    assert "Safety: read-only" in output
    assert "5YJ3E1EA7JF000001" not in output
    assert "12345678901234567" not in output
    assert "secret-token-123456" not in output
    assert "oauth-code-123456" not in output
    assert "oauth-state-123456" not in output
    assert "client-secret-123456" not in output
    assert "{" not in output


def test_onboarding_slash_output_summarizes_hidden_items() -> None:
    output = slash._format_onboarding(  # noqa: SLF001
        {
            "ok": True,
            "phase": "auth_login",
            "missing_prerequisites": [f"missing {index}" for index in range(8)],
            "next_steps": [f"step {index}" for index in range(6)],
            "scope_readiness": {
                "configured_user_scopes": ["openid", "offline_access"],
                "granted_user_scopes": ["openid"],
                "missing_granted_user_scopes": [
                    "offline_access",
                    "vehicle_device_data",
                    "vehicle_cmds",
                    "vehicle_charging_cmds",
                    "vehicle_location",
                ],
            },
            "mutates_state": False,
        }
    )

    assert "- missing 5" in output
    assert "- missing 6" not in output
    assert "- …and 2 more missing prerequisite(s)" in output
    assert "- step 3" in output
    assert "- step 4" not in output
    assert "- …and 2 more setup step(s)" in output
    assert "Scopes: configured=2, granted=1, missing=5" in output
    assert (
        "Missing scopes: offline_access, vehicle_device_data, vehicle_cmds, "
        "vehicle_charging_cmds, …and 1 more"
    ) in output


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
                "12345678901234567 with Bearer secret-token-123456 "
                "near latitude=37.7749295 longitude: -122.4194155"
            ),
            "retry_command": "/tescmd-lock 5YJ3E1EA7JF000001 confirm=true",
            "next_action": (
                "Check vehicle 12345678901234567 enrollment at "
                "https://maps.example.test/?lat=37.7749295&lng=-122.4194155."
            ),
            "status_code": 403,
        },
    )

    assert "/tescmd-lock: failed" in output
    assert "…0001" in output
    assert "…4567" in output
    assert "Bearer [REDACTED]" in output
    assert "latitude=[coordinates redacted]" in output
    assert "longitude: [coordinates redacted]" in output
    assert "lat=[coordinates redacted]" in output
    assert "lng=[coordinates redacted]" in output
    assert "5YJ3E1EA7JF000001" not in output
    assert "12345678901234567" not in output
    assert "secret-token-123456" not in output
    assert "37.7749295" not in output
    assert "-122.4194155" not in output
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
    assert "access_token|refresh_token|id_token|client_id|client_secret" in asset
    assert "code_verifier|code_challenge|token|pin" in asset
    assert "([?#&](?:${secretKeys})=)" in asset
    assert "secretValuePattern" in asset
    assert "(^|[\\\\s,;({\\\\[])" in asset
    assert "(_match, prefix, key) => `${prefix}${key}[REDACTED]`" in asset
    assert "([\"']?(?:${secretKeys})[\"']?\\\\s*:\\\\s*)" in asset
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


def test_dashboard_vehicle_override_field_hides_identifier_by_default() -> None:
    asset = Path("src/hermes_tescmd_plugin/dashboard/assets/index.js").read_text()
    style = Path("src/hermes_tescmd_plugin/dashboard/assets/style.css").read_text()
    body = asset.split("function VehiclePicker", 1)[1].split(
        "function TargetContextPanel", 1
    )[0]

    assert "const [showIdentifier, setShowIdentifier] = hooks.useState(false);" in body
    assert 'className: "tescmd-identifier-entry"' in body
    assert 'type: showIdentifier ? "text" : "password"' in body
    assert 'autoComplete: "off"' in body
    assert "spellCheck: false" in body
    assert '"aria-label": "Vehicle identifier override, hidden by default"' in body
    assert 'showIdentifier ? "Hide identifier" : "Reveal identifier"' in body
    assert '"aria-pressed": showIdentifier' in body
    assert "raw override field is hidden by default" in body
    assert ".tescmd-identifier-entry" in style
    assert 'input[type="password"]' in style


def test_dashboard_security_snapshot_names_open_closures_without_raw_codes() -> None:
    asset = Path("src/hermes_tescmd_plugin/dashboard/assets/index.js").read_text()
    style = Path("src/hermes_tescmd_plugin/dashboard/assets/style.css").read_text()
    summary_body = asset.split("function securitySummary", 1)[1].split(
        "function locationSummary", 1
    )[0]
    snapshot_body = asset.split("function VehicleSnapshot", 1)[1].split(
        "function loadLeaflet", 1
    )[0]

    assert "const closureLabels = {" in asset
    assert 'df: "driver front door"' in asset
    assert 'rt: "rear trunk"' in asset
    assert 'fd_window: "driver front window"' in asset
    assert "function closureIsOpen(value)" in asset
    assert '"ajar"' in asset
    assert '"vented"' in asset
    assert "Object.entries(closureLabels)" in summary_body
    assert "openLabels" in summary_body
    assert "Open: ${security.openLabels.slice(0, 3).join" in snapshot_body
    assert "No open closures reported" in snapshot_body
    assert 'className: "tescmd-mini-widget tescmd-security-widget"' in snapshot_body
    assert 'h("em", null, closureText)' in snapshot_body
    assert ".tescmd-security-widget em" in style


def test_dashboard_onboarding_card_sanitizes_setup_guidance() -> None:
    asset = Path("src/hermes_tescmd_plugin/dashboard/assets/index.js").read_text()
    body = asset.split("function OnboardingCard", 1)[1].split("function BusyBanner", 1)[
        0
    ]

    assert "missing_prerequisites.map((item) => sanitizeDashboardText" in body
    assert "next_steps.map((step) => sanitizeDashboardText" in body
    assert "function boundedPreview(items, limit)" in asset
    assert "function hiddenCountText(count, singular, plural)" in asset
    assert "const missingPreview = boundedPreview(missing, 4)" in body
    assert "const stepsPreview = boundedPreview(steps, 2)" in body
    assert (
        'hiddenCountText(missingPreview.hiddenCount, "setup item", "setup items")'
        in body
    )
    assert (
        'hiddenCountText(stepsPreview.hiddenCount, "next step", "next steps")' in body
    )
    assert "hiddenMissing ? h(Badge" in body
    assert (
        'hiddenSteps ? h("small", { className: "tescmd-muted" }, hiddenSteps)' in body
    )
    assert "const next = sanitizeDashboardText" in body
    assert "const docsAnchor = sanitizeDashboardText" in body
    assert (
        "OAuth values, vehicle identifiers, and precise route/location details stay hidden"
        in body
    )
    assert (
        "Hidden counts describe omitted sanitized guidance without revealing raw values"
        in body
    )
    assert 'h("small", null, docsAnchor)' in body
    assert 'h("li", { key: index }, step)' in body
    assert 'h("li", { key: index }, onboarding' not in body


def test_dashboard_navigation_actions_require_targets_and_clear_route_fields() -> None:
    asset = Path("src/hermes_tescmd_plugin/dashboard/assets/index.js").read_text()
    style = Path("src/hermes_tescmd_plugin/dashboard/assets/style.css").read_text()

    assert "function NavigationGuardPanel" in asset
    assert (
        "Navigation buttons stay unavailable until their required destination fields are present"
        in asset
    )
    assert (
        "Route text, coordinates, and place IDs are treated as temporary sensitive state"
        in asset
    )
    assert "Clear route fields" in asset
    assert ".tescmd-nav-guard-actions" in style
    assert (
        "Clearing only edits dashboard form state; it does not call Tesla or the plugin."
        in asset
    )
    assert "function clearAllNavigationFields()" in asset
    assert "clearRouteFields: clearAllNavigationFields" in asset
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
    assert "function routeReadiness(destination, lat, lon, placeIds)" in asset
    assert (
        "function controlReadiness(percent, amps, driverTemp, passengerTemp, volume)"
        in asset
    )
    assert "function ActionRequirementsPanel" in asset
    assert "Action readiness" in asset
    assert "Quick action readiness checklist" in asset
    assert "Why some buttons are disabled" in asset
    assert "tescmd-action-blockers" in asset
    assert "aria-describedby" in asset
    assert (
        "Disabled-button reasons are shown here without echoing destinations, coordinates, place IDs, VINs, or Fleet IDs."
        in asset
    )
    assert "check the confirmation box before any physical action" in asset
    assert "enter a charge limit from 1 to 100" in asset
    assert "enter charging amps from 1 to 80" in asset
    assert "enter driver and passenger temperatures from 50° to 90°" in asset
    assert "enter a volume level from 0 to 11" in asset
    assert "Enter a charge limit from 1 to 100 before changing charging." in asset
    assert "Enter charging amps from 1 to 80 before changing charging." in asset
    assert (
        "Enter driver and passenger temperatures from 50° to 90° before changing climate."
        in asset
    )
    assert "const driverReady = boundedNumberReady(driverTemp, 50, 90);" in asset
    assert "const passengerReady = boundedNumberReady(passengerTemp, 50, 90);" in asset
    assert "Enter a volume level from 0 to 11 before changing media volume." in asset
    assert "enter both latitude and longitude" in asset
    assert (
        "h(ActionRequirementsPanel, { confirm, destination, lat, lon, placeIds, percent, amps, driverTemp, passengerTemp, volume })"
        in asset
    )
    assert ".tescmd-action-requirements" in style
    assert ".tescmd-action-requirements-warn" in style
    assert ".tescmd-action-requirement-list" in style
    assert ".tescmd-action-blockers" in style
    assert "border-left: 3px solid" in style
    assert "Route fields were cleared; physical actions are locked again." in asset
    assert (
        "route fields were cleared and confirmation is locked off after the request"
        in asset
    )


def test_dashboard_action_readiness_panel_explains_disabled_buttons_privately() -> None:
    asset = Path("src/hermes_tescmd_plugin/dashboard/assets/index.js").read_text()
    style = Path("src/hermes_tescmd_plugin/dashboard/assets/style.css").read_text()
    body = asset.split("function ActionRequirementsPanel", 1)[1].split(
        "function objectAt", 1
    )[0]

    assert "function routeReadiness(destination, lat, lon, placeIds)" in asset
    assert (
        "function controlReadiness(percent, amps, driverTemp, passengerTemp, volume)"
        in asset
    )
    assert "Quick action readiness checklist" in body
    assert "Action readiness" in body
    assert "still blocking some buttons" in body
    assert "All quick-action guardrails are satisfied" in body
    assert "Disabled-button reasons are shown here" in body
    assert (
        "without echoing destinations, coordinates, place IDs, VINs, or Fleet IDs"
        in body
    )
    assert "Physical confirmation" in body
    assert "Charge limit" in body
    assert "Charge amps" in body
    assert "Cabin temperatures" in body
    assert "Media volume" in body
    assert "enter a charge limit from 1 to 100" in body
    assert "enter charging amps from 1 to 80" in body
    assert "enter driver and passenger temperatures from 50° to 90°" in body
    assert "enter a volume level from 0 to 11" in body
    assert "boundedNumberReady(driverTemp, 50, 90)" in asset
    assert "boundedNumberReady(passengerTemp, 50, 90)" in asset
    assert (
        "Enter driver and passenger temperatures from 50° to 90° before changing climate."
        in asset
    )
    assert "Navigate" in body
    assert "GPS navigation" in body
    assert "Waypoints" in body
    assert "enter both latitude and longitude" in body
    assert "enter at least one place ID" in body
    assert (
        "h(ActionRequirementsPanel, { confirm, destination, lat, lon, placeIds, percent, amps, driverTemp, passengerTemp, volume })"
        in asset
    )
    assert ".tescmd-action-requirements" in style
    assert ".tescmd-action-requirements-warn" in style
    assert ".tescmd-action-requirement-list" in style


def test_dashboard_action_groups_show_privacy_safe_safety_notes() -> None:
    asset = Path("src/hermes_tescmd_plugin/dashboard/assets/index.js").read_text()
    style = Path("src/hermes_tescmd_plugin/dashboard/assets/style.css").read_text()
    body = asset.split("function actionGroupSafetyNote", 1)[1].split(
        "function ReadGroup", 1
    )[0]

    assert "function actionGroupSafetyNote(title)" in asset
    assert "tescmd-action-group-heading" in body
    assert "can affect access or alert people near the vehicle" in body
    assert "success banners avoid VINs, Fleet IDs, and raw request JSON" in body
    assert "route targets are temporary sensitive fields" in body
    assert 'h("small", null, actionGroupSafetyNote(title))' in body
    assert ".tescmd-action-group-heading" in style
    assert "5YJ3E1EA7JF000001" not in body
    assert "12345678901234567" not in body
    assert "latitude" not in body
    assert "longitude" not in body


def test_dashboard_read_safety_panel_explains_wake_confirm_boundary() -> None:
    asset = Path("src/hermes_tescmd_plugin/dashboard/assets/index.js").read_text()
    style = Path("src/hermes_tescmd_plugin/dashboard/assets/style.css").read_text()
    body = asset.split("function ReadSafetyPanel", 1)[1].split(
        "function NavigationGuardPanel", 1
    )[0]

    assert "Read safety guardrails" in body
    assert "Wake-enabled reads are armed" in body
    assert "Reads are non-waking" in body
    assert "wake and confirmation are both enabled" in body
    assert "will not send wake-enabled reads until physical-action confirmation" in body
    assert "fail-closed read" in body
    assert "h(ReadSafetyPanel, { wakeReads, confirm })" in asset
    assert ".tescmd-read-safety" in style
    assert ".tescmd-read-safety-wake" in style


def test_dashboard_scope_readiness_panel_summarizes_missing_scopes_safely() -> None:
    asset = Path("src/hermes_tescmd_plugin/dashboard/assets/index.js").read_text()
    style = Path("src/hermes_tescmd_plugin/dashboard/assets/style.css").read_text()
    body = asset.split("function ScopeReadinessPanel", 1)[1].split(
        "function BusyBanner", 1
    )[0]

    assert "function scopeReadinessFromStatus(status)" in asset
    assert "scopeCapabilityRows(scopeReadiness)" in asset
    assert "function scopeNeedsText(missing)" in asset
    assert "OAuth scope readiness" in body
    assert "Some Tesla capabilities need scopes" in body
    assert "Tesla OAuth scopes look ready" in body
    assert "missing_granted_user_scopes" in body
    assert "payload && payload.missing_scopes" in asset
    assert (
        "Missing scope names are shown without tokens, vehicle identifiers, or callback values"
        in body
    )
    assert "sanitizeDashboardText(scopeReadiness.grant_scope_source" in body
    assert 'sanitizeDashboardText(item, "scope")' in body
    assert "const missingGrantedPreview = boundedPreview(missingGranted, 4)" in body
    assert "const capabilitiesPreview = boundedPreview(capabilities, 4)" in body
    assert (
        'hiddenCountText(missingGrantedPreview.hiddenCount, "missing granted scope", "missing granted scopes")'
        in body
    )
    assert (
        'hiddenCountText(capabilitiesPreview.hiddenCount, "capability", "capabilities")'
        in body
    )
    assert "scopeNeedsText(item.missing)" in body
    assert (
        "Hidden scope-readiness counts describe omitted sanitized scopes/capabilities"
        in body
    )
    assert "without exposing raw tokens, callbacks, or vehicle identifiers" in body
    assert "h(ScopeReadinessPanel, { status })" in asset
    assert ".tescmd-scope-readiness" in style
    assert ".tescmd-scope-readiness-warn" in style


def test_dashboard_user_visible_errors_are_sanitized_before_rendering() -> None:
    asset = Path("src/hermes_tescmd_plugin/dashboard/assets/index.js").read_text()

    assert "setError(dashboardErrorMessage(err));" in asset
    assert "setError(String((err && err.message) || err));" not in asset
    assert "setLastActionStatus(sanitizeDashboardText(payload.message" in asset
    assert "Tesla dashboard request failed." in asset
    assert (
        "code|state|access_token|refresh_token|id_token|client_id|client_secret"
        in asset
    )
    assert "code_verifier|code_challenge|token|pin" in asset
    assert "lat(?:itude)?|lon(?:gitude)?|lng" in asset
    assert "destination|address|query|place_id|place_ids" in asset
    error_card_body = asset.split('className: "tescmd-error-card"', 1)[0]
    assert "dashboardErrorMessage(err)" in error_card_body


def test_dashboard_quick_action_status_uses_redacted_payload_summary() -> None:
    asset = Path("src/hermes_tescmd_plugin/dashboard/assets/index.js").read_text()
    body = asset.split("function dashboardActionStatus", 1)[1].split(
        "async function setDefaultVehicle", 1
    )[0]

    assert "payload && payload.message" in body
    assert "response.message" in body
    assert "sanitizeDashboardText(rawMessage, fallback)" in body
    assert "Tesla accepted the ${actionLabel} command." in body
    assert "Route fields were cleared; physical actions are locked again." in body
    assert (
        "setLastActionStatus(dashboardActionStatus(payload, action, navigationAction));"
        in asset
    )
    assert "Ran ${action}; route fields" not in asset
    assert "Ran ${action}; physical actions" not in asset


def test_dashboard_payload_panel_has_local_clear_privacy_control() -> None:
    asset = Path("src/hermes_tescmd_plugin/dashboard/assets/index.js").read_text()
    style = Path("src/hermes_tescmd_plugin/dashboard/assets/style.css").read_text()
    body = asset.split("function PayloadPrivacyToolbar", 1)[1].split(
        "function Field", 1
    )[0]

    assert "Payload privacy controls" in body
    assert "Local debug payload" in body
    assert "Redacted payload is visible" in body
    assert "No payload retained" in body
    assert "Clear payload panel" in body
    assert "does not call Tesla or the plugin" in body
    assert "disabled: !hasPayload" in body
    assert (
        'h(PayloadPrivacyToolbar, { hasPayload: Boolean(detail), clearPayload: () => { setDetail(null); setLastReadKind(""); } })'
        in asset
    )
    assert ".tescmd-payload-privacy" in style


def test_dashboard_admin_read_summaries_are_useful_and_private() -> None:
    asset = Path("src/hermes_tescmd_plugin/dashboard/assets/index.js").read_text()
    body = asset.split("function DashboardReadSummary", 1)[1].split(
        "function vehicleAvailability", 1
    )[0]

    assert "function yesNoUnknown(value)" in asset
    assert "function setupReadinessValue(payload, key)" in asset
    assert "function cacheModeLabel(payload)" in asset
    assert "function cacheValue(payload, ...keys)" in asset
    assert "function cacheCountLabel(label, value, pluralLabel)" in asset
    assert "function cacheFreshnessLabel(payload)" in asset
    assert (
        'cacheValue(payload, "entries", "entry_count", "count", "current_entries")'
        in body
    )
    assert 'cacheValue(payload, "backend", "mode", "storage", "source")' in body
    assert "current/stale counts, backend mode, and freshness hints" in body
    assert (
        "raw cache keys, cached vehicle snapshots, vehicle identifiers, or account details"
        in body
    )
    assert 'cacheCountLabel("current entry", entryCount, "current entries")' in body
    assert (
        'cacheCountLabel("stale/expired entry", expiredCount, "stale/expired entries")'
        in body
    )
    assert "cacheFreshnessLabel(payload)" in body
    assert (
        'cacheValue(payload, "next_expiry_seconds", "next_expires_in_seconds"' in asset
    )
    assert "payload && payload.cache_status" in asset
    assert "payload && payload.response" in asset
    assert "payload && payload.data" in asset
    assert "cache_key" not in body
    assert "cache_path" not in body
    assert 'lastReadKind === "auth-status"' in body
    assert 'lastReadKind === "onboarding"' in body
    assert 'lastReadKind === "key-show" || lastReadKind === "key-validate"' in body
    assert 'lastReadKind === "cache-status"' in body
    assert 'lastReadKind === "config"' in body
    assert 'lastReadKind === "gui"' in body
    assert "Auth readiness summary" in body
    assert "Onboarding summary" in body
    assert "Vehicle-command key summary" in body
    assert "Key hosting validation summary" in body
    assert "Cache summary" in body
    assert "Vehicle config summary" in body
    assert "GUI settings summary" in body
    assert "function configGuiBadge(label, ...values)" in asset
    assert "function configGuiBooleanBadge(label, ...values)" in asset
    assert "coarse model, capability, and unit hints" in body
    assert (
        'configGuiBadge("model", config.car_type, config.model, config.trim_badging)'
        in body
    )
    assert (
        'configGuiBooleanBadge("navigation", config.can_accept_navigation_requests'
        in body
    )
    assert "coarse unit and display preferences" in body
    assert (
        'configGuiBadge("distance", gui.gui_distance_units, gui.distance_units)' in body
    )
    assert 'configGuiBadge("temperature", gui.gui_temperature_units' in body
    assert (
        "tokens, callback URLs, client IDs, vehicle identifiers, and key paths stay"
        in body
    )
    assert (
        "without exposing OAuth values, domains, client IDs, or vehicle identifiers"
        in body
    )
    assert (
        "local key paths, public-key URLs, fingerprints, domains, and enrollment links"
        in body
    )
    assert "local cache paths, raw cache keys, cached vehicle snapshots" in body
    assert (
        "without echoing raw option values, identifiers, precise location hints, or account details"
        in body
    )
    assert "access_token" not in body
    assert "refresh_token" not in body
    assert "client_secret" not in body
    assert "public-key.pem" not in body
    assert "5YJ3E1EA7JF000001" not in body
    assert "12345678901234567" not in body


def test_dashboard_core_status_read_summaries_are_useful_and_private() -> None:
    asset = Path("src/hermes_tescmd_plugin/dashboard/assets/index.js").read_text()
    body = asset.split("function DashboardReadSummary", 1)[1].split(
        "function vehicleAvailability", 1
    )[0]

    assert "function readObjectWithFields(payload, fieldKeys, ...nestedKeys)" in asset
    assert "function closureSummaryData(payload)" in asset
    assert 'lastReadKind === "vehicle-status"' in body
    assert 'lastReadKind === "closures"' in body
    assert 'lastReadKind === "security"' in body
    assert "Vehicle status summary" in body
    assert "Closures summary" in body
    assert "Security summary" in body
    assert (
        "coarse firmware/state, occupancy, lock/Sentry, charge, climate, and drive hints"
        in body
    )
    assert (
        "Vehicle names, VINs, Fleet IDs, exact coordinates, addresses, route text"
        in body
    )
    assert 'percentBadge("battery", firstDefined(charge.battery_level' in body
    assert 'temperatureBadge("cabin", firstDefined(climate.inside_temp' in body
    assert 'speedBadge("speed", firstDefined(drive.speed' in body
    assert "Object.entries(closureLabels)" in asset
    assert "summary.openLabels.slice(0, 4).join" in body
    assert "Raw closure codes, vehicle identifiers, and location fields" in body
    assert (
        'readObjectWithFields(payload, ["locked", "sentry_mode", "valet_mode"' in body
    )
    assert "Security returned lock/Sentry/valet state" in body
    assert "Raw alarm details, private identifiers, and exact location fields" in body
    core_block = body.split('lastReadKind === "vehicle-status"', 1)[1].split(
        'lastReadKind === "charge"', 1
    )[0]
    assert "vehicle_name" in core_block
    assert "address" in core_block
    assert "route text" in core_block
    assert "latitude" not in core_block
    assert "longitude" not in core_block
    assert "destination=" not in core_block
    assert "5YJ3E1EA7JF000001" not in body
    assert "12345678901234567" not in body


def test_dashboard_charge_and_climate_read_summaries_are_useful_and_private() -> None:
    asset = Path("src/hermes_tescmd_plugin/dashboard/assets/index.js").read_text()
    body = asset.split("function DashboardReadSummary", 1)[1].split(
        "function vehicleAvailability", 1
    )[0]

    assert "function readStatusObject(payload, ...keys)" in asset
    assert "function percentBadge(label, value)" in asset
    assert "function temperatureBadge(label, value)" in asset
    assert 'lastReadKind === "charge"' in body
    assert 'lastReadKind === "climate"' in body
    assert "Charge read summary" in body
    assert "Climate read summary" in body
    assert 'readStatusObject(payload, "charge_state", "charge", "battery")' in body
    assert 'readStatusObject(payload, "climate_state", "climate", "hvac_state")' in body
    assert 'percentBadge("battery", level)' in body
    assert 'percentBadge("limit", limit)' in body
    assert 'temperatureBadge("cabin"' in body
    assert 'temperatureBadge("outside"' in body
    assert 'temperatureBadge("target"' in body
    assert (
        "Charge-port locations, vehicle identifiers, raw charger metadata, and account details stay in the redacted payload"
        in body
    )
    assert (
        "Precise location context, vehicle identifiers, driver-specific personal data, and raw climate payload details stay in the redacted payload"
        in body
    )
    assert "battery_range" in body
    assert "est_battery_range" in body
    assert "ideal_battery_range" in body
    assert "inside_temp" in body
    assert "outside_temp" in body
    assert "driver_temp_setting" in body
    assert "passenger_temp_setting" in body
    read_block = body.split('lastReadKind === "charge"', 1)[1].split(
        'lastReadKind === "config"', 1
    )[0]
    assert "latitude" not in read_block
    assert "longitude" not in read_block
    assert "5YJ3E1EA7JF000001" not in body
    assert "12345678901234567" not in body


def test_dashboard_drive_and_location_read_summaries_are_useful_and_private() -> None:
    asset = Path("src/hermes_tescmd_plugin/dashboard/assets/index.js").read_text()
    body = asset.split("function DashboardReadSummary", 1)[1].split(
        "function vehicleAvailability", 1
    )[0]

    assert "function milesBadge(label, value)" in asset
    assert "function speedBadge(label, value)" in asset
    assert 'lastReadKind === "drive" || lastReadKind === "location"' in body
    assert "Drive read summary" in body
    assert "Location read summary" in body
    assert 'readStatusObject(payload, "drive_state", "drive", "location_data")' in body
    assert 'speedBadge("speed", firstDefined(drive.speed, drive.vehicle_speed))' in body
    assert (
        "compassHeadingLabel(firstDefined(drive.heading, drive.vehicle_heading))"
        in body
    )
    assert 'milesBadge("odometer"' in body
    assert "coordinateHint" in body
    assert "fix available" in body
    assert (
        "Drive/location state is condensed into speed, heading, gear/power, odometer"
        in body
    )
    assert (
        "Precise coordinates, route or destination text, addresses, vehicle identifiers, and raw map payload details stay in the redacted payload"
        in body
    )
    read_block = body.split(
        'lastReadKind === "drive" || lastReadKind === "location"', 1
    )[1].split('lastReadKind === "config"', 1)[0]
    assert "address" in read_block
    assert "destination text" in read_block
    assert "route or destination" in read_block
    assert "latitude" not in read_block
    assert "longitude" not in read_block
    assert "drive.address" not in read_block
    assert "drive.destination" not in read_block
    assert "drive.native_location_name" not in read_block
    assert "5YJ3E1EA7JF000001" not in body
    assert "12345678901234567" not in body


def test_dashboard_software_and_alert_summaries_are_useful_and_private() -> None:
    asset = Path("src/hermes_tescmd_plugin/dashboard/assets/index.js").read_text()
    body = asset.split("function DashboardReadSummary", 1)[1].split(
        "function vehicleAvailability", 1
    )[0]

    assert "function softwareMeta(payload, ...keys)" in asset
    assert "function alertItems(payload)" in asset
    assert "function alertStatusLabel(alert, fallback)" in asset
    assert 'lastReadKind === "software"' in body
    assert 'lastReadKind === "alerts"' in body
    assert "Software summary" in body
    assert "version ${version}" in body
    assert "status ${status}" in body
    assert "timing ${estimate}" in body
    assert "progress ${progress}" in body
    assert "scheduled ${scheduled}" in body
    assert 'softwareMeta(payload, "install_perc", "download_perc"' in body
    assert 'softwareMeta(payload, "scheduled_time", "install_window_start"' in body
    assert (
        "without exposing vehicle identifiers, release-note URLs, account fields, location context, or raw diagnostic payloads"
        in body
    )
    assert "Alerts summary" in body
    assert "Top statuses: ${topStatuses.join" in body
    assert (
        "Alert messages, driver/location hints, callback URLs, and vehicle identifiers stay in the redacted payload"
        in body
    )
    assert "vehicle_alerts" in asset
    assert "active_alerts" in asset
    assert "software_update" in asset
    assert "vehicle_state" in asset
    assert "payload && payload.software" in asset
    assert "vehicleState && vehicleState.software_update" in asset
    assert "alert.message" not in asset
    assert "alert.description" not in asset
    assert "release_note_url" not in body
    assert "latitude" not in body
    assert "longitude" not in body
    assert "5YJ3E1EA7JF000001" not in body
    assert "12345678901234567" not in body


def test_dashboard_nearby_chargers_read_summary_is_useful_and_private() -> None:
    asset = Path("src/hermes_tescmd_plugin/dashboard/assets/index.js").read_text()
    body = asset.split("function DashboardReadSummary", 1)[1].split(
        "function vehicleAvailability", 1
    )[0]

    assert "function chargerSites(payload, key, ...aliases)" in asset
    assert "function chargerDistanceLabel(site)" in asset
    assert "function chargerStallLabel(site)" in asset
    assert "function chargerOrderLabel(site, fallback, order)" in asset
    assert 'lastReadKind === "nearby-chargers"' in body
    assert "Nearby chargers summary" in body
    assert 'Top ${chargerOrderLabel(topSupercharger, "Supercharger", 1)}' in body
    assert "tescmd_navigation_supercharger order=N confirm=true" in body
    assert "charger names and coordinates stay hidden" in body
    assert "destination charger" in body
    assert "nearby_superchargers" in body
    assert "destination_chargers" in body
    assert "numericValue(site.distance_miles" in asset
    assert '.replace(/\\.0$/, "")' in asset
    assert "chargerOrderLabel(topSupercharger" in body
    assert "chargerStallLabel(topSupercharger)" in body
    assert "chargerDistanceLabel(topSupercharger)" in body
    assert ".name" not in body
    assert "site_name" not in body
    assert "location_name" not in body
    assert "latitude" not in body
    assert "longitude" not in body
    assert "site.lat" not in body
    assert "site.lng" not in body
    assert "5YJ3E1EA7JF000001" not in body


def test_dashboard_schedule_read_summaries_are_useful_and_private() -> None:
    asset = Path("src/hermes_tescmd_plugin/dashboard/assets/index.js").read_text()
    body = asset.split("function DashboardReadSummary", 1)[1].split(
        "function vehicleAvailability", 1
    )[0]

    assert "function scheduleSection(payload, ...keys)" in asset
    assert "function scheduleEntries(sectionPayload, ...keys)" in asset
    assert "function scheduleEntryLabel(entry, fallback)" in asset
    assert "function scheduleSummaryData(payload, sectionKeys, entryKeys)" in asset
    assert (
        "return {};"
        in asset.split("function scheduleSection", 1)[1].split(
            "function scheduleEntries", 1
        )[0]
    )
    assert 'if (!entry || typeof entry !== "object") return fallback;' in asset
    assert 'lastReadKind === "charge-schedule"' in body
    assert 'lastReadKind === "preconditioning-schedule"' in body
    assert "Charge schedule summary" in body
    assert "Preconditioning schedule summary" in body
    assert "Top schedules: ${summary.topEntries.join" in body
    assert "enabled ${summary.enabled}" in body
    assert "next/start ${summary.nextStart}" in body
    assert '"charge_schedule", "charge_schedule_data"' in body
    assert '"preconditioning_schedule", "preconditioning_schedule_data"' in body
    assert "entry.minute_of_day" in asset
    assert "entry.departure_time" in asset
    assert "entry.days_of_week" in asset
    assert "value !== undefined && value !== null" in asset
    assert "Schedule IDs, vehicle identifiers" in body
    assert "precise coordinates stay out of the visible summary" in body
    assert "schedule_id" not in body
    assert "entry.id" not in body
    assert "latitude" not in body
    assert "longitude" not in body
    assert "5YJ3E1EA7JF000001" not in body


def test_dashboard_release_notes_read_summary_is_useful_and_private() -> None:
    asset = Path("src/hermes_tescmd_plugin/dashboard/assets/index.js").read_text()
    body = asset.split("function DashboardReadSummary", 1)[1].split(
        "function vehicleAvailability", 1
    )[0]

    assert "function releaseNoteContainers(payload)" in asset
    assert "function releaseNoteItems(payload)" in asset
    assert "function releaseNoteVersion(payload)" in asset
    assert "function releaseNoteStatus(payload)" in asset
    assert "function releaseNoteTitle(item, fallback)" in asset
    assert 'lastReadKind === "release-notes"' in body
    assert "Release notes summary" in body
    assert "Firmware ${version} · ${status}" in body
    assert "Top sections: ${topTitles.join" in body
    assert (
        "Note bodies, URLs, route text, vehicle identifiers, and coordinates stay in the redacted payload"
        in body
    )
    assert "Release-note metadata returned without section titles" in body
    assert "payload && payload.release_notes" in asset
    assert "releaseNotes && releaseNotes.release_notes" in asset
    assert "releaseNotes && releaseNotes.sections" in asset
    assert "releaseNotes && releaseNotes.notes" in asset
    assert "releaseNotes && releaseNotes.release_notes_list" in asset
    assert "payload && payload.release_notes_list" in asset
    assert "payload && payload.release_note_sections" in asset
    assert "releaseNotes.car_version" in asset
    assert "item.subtitle" in asset
    assert "note section" in body
    assert "item.body" not in asset
    assert "item.content" not in asset
    assert "item.description" not in asset
    assert "item.url" not in asset
    assert "latitude" not in body
    assert "longitude" not in body
    assert "destination=" not in body
    assert "place_id" not in body
    assert "5YJ3E1EA7JF000001" not in body


def test_dashboard_drivers_read_summary_is_useful_and_private() -> None:
    asset = Path("src/hermes_tescmd_plugin/dashboard/assets/index.js").read_text()
    body = asset.split("function DashboardReadSummary", 1)[1].split(
        "function vehicleAvailability", 1
    )[0]

    assert "function accessContainers(payload)" in asset
    assert "function accessRows(payload, keys)" in asset
    assert "function accessCount(payload, keys)" in asset
    assert "function accessFacetCounts(rows, keys, fallback)" in asset
    assert 'lastReadKind === "drivers"' in body
    assert "Access summary" in body
    assert "Top role/status hints: ${accessHints.join" in body
    assert (
        'accessRows(payload, ["drivers", "users", "people", "members", "vehicle_drivers"])'
        in body
    )
    assert 'accessRows(payload, ["invites", "invitations", "pending_invites"])' in body
    assert '["role", "permission", "access_level", "access_type", "type"]' in body
    assert '["status", "state", "account_status", "access_status"]' in body
    assert '["status", "state", "invite_status"]' in body
    assert "raw permission payloads stay" in body
    assert "...accessHints.slice(0, 3)" in body
    assert "payload && payload.access" in asset
    assert "invite links, private IDs" in body
    assert "row.email" not in asset
    assert "row.name" not in asset
    assert "phone" not in body.split('lastReadKind === "drivers"', 1)[1].split(
        'lastReadKind === "service"', 1
    )[0].lower().replace("phone numbers", "")
    assert "invite_url" not in body
    assert "5YJ3E1EA7JF000001" not in body
    assert "12345678901234567" not in body


def test_dashboard_service_read_summary_handles_nested_status_privately() -> None:
    asset = Path("src/hermes_tescmd_plugin/dashboard/assets/index.js").read_text()
    body = asset.split("function DashboardReadSummary", 1)[1].split(
        "function vehicleAvailability", 1
    )[0]

    assert "function serviceContainers(payload)" in asset
    assert "function serviceValue(payload, ...keys)" in asset
    assert "response && response.service" in asset
    assert "data && data.service" in asset
    assert "service && service.response" in asset
    assert 'lastReadKind === "service"' in body
    assert "Service summary" in body
    assert (
        'serviceValue(payload, "status", "service_status", "state", '
        '"maintenance_status", "appointment_status")' in body
    )
    assert "Top visits: ${topVisits.join" in body
    assert "Appointment IDs, service-center addresses, raw booking URLs" in body
    assert "vehicle identifiers, and customer contact details" in body
    assert "appointment.appointment_id" not in asset
    assert "appointment.service_center_url" not in asset
    assert "appointment.url" not in asset
    assert "appointment.address" not in asset
    assert "service_center_name" not in asset
    assert "customer" not in body.split('lastReadKind === "service"', 1)[1].split(
        'lastReadKind === "mobile-access"', 1
    )[0].lower().replace("customer contact details", "")
    assert "5YJ3E1EA7JF000001" not in body
    assert "12345678901234567" not in body


def test_dashboard_warranty_read_summary_is_available_useful_and_private() -> None:
    asset = Path("src/hermes_tescmd_plugin/dashboard/assets/index.js").read_text()
    body = asset.split("function DashboardReadSummary", 1)[1].split(
        "function vehicleAvailability", 1
    )[0]

    assert '["warranty", "Warranty"]' in asset
    assert "function warrantyContainers(payload)" in asset
    assert "function warrantyTerms(payload)" in asset
    assert "function warrantyMeta(payload, ...keys)" in asset
    assert "function warrantyTermLabel(term, fallback)" in asset
    assert 'lastReadKind === "warranty"' in body
    assert "Warranty summary" in body
    assert "Warranty ${status} · as of ${asOf}" in body
    assert "Top terms: ${topTerms.join" in body
    assert (
        "Agreement IDs, URLs, vehicle identifiers, and raw coverage payload details stay in the redacted payload"
        in body
    )
    assert "Warranty data returned without term labels" in body
    assert '["warranties", "warranty_terms", "terms", "coverages", "items"]' in asset
    assert "term.end_date" in asset
    assert "term.odometer_limit_miles" in asset
    assert "term.odometer_limit_km" in asset
    assert "term.mileage_limit" in asset
    assert "payload && payload.warranty" in asset
    assert (
        "tescmd_vehicle_warranty"
        in Path("src/hermes_tescmd_plugin/dashboard/plugin_api.py").read_text()
    )
    assert "agreement_id" not in body
    assert "contract_id" not in body
    assert "term.url" not in asset
    assert "latitude" not in body
    assert "longitude" not in body
    assert "5YJ3E1EA7JF000001" not in body


def test_dashboard_energy_read_summary_is_useful_and_private() -> None:
    asset = Path("src/hermes_tescmd_plugin/dashboard/assets/index.js").read_text()
    body = asset.split("function DashboardReadSummary", 1)[1].split(
        "function vehicleAvailability", 1
    )[0]
    plugin_api = Path("src/hermes_tescmd_plugin/dashboard/plugin_api.py").read_text()

    assert "/tescmd-energy" in Path("README.md").read_text()
    assert '["energy", "Energy"]' in asset
    assert '"energy": "tescmd_energy_list"' in plugin_api
    assert "function energyContainers(payload)" in asset
    assert "function energyProducts(payload)" in asset
    assert "function energyMeta(payload, ...keys)" in asset
    assert "function energyPowerBadge(label, value)" in asset
    assert 'lastReadKind === "energy"' in body
    assert "Energy summary" in body
    assert "Energy returned ${products.length} product/site record" in body
    assert "Live power and backup hints are summarized" in body
    assert (
        '["products", "energy_products", "sites", "energy_sites", "resources"]' in asset
    )
    assert (
        'energyMeta(payload, "status", "state", "operation_mode", "site_status", "grid_status")'
        in body
    )
    assert (
        'energyMeta(payload, "backup_reserve_percent", "backup_reserve", "reserve_percent", "battery_backup_reserve")'
        in body
    )
    assert 'energyPowerBadge("solar", solarPower)' in body
    assert 'energyPowerBadge("grid", gridPower)' in body
    assert "Site IDs, addresses, coordinates, vehicle identifiers" in body
    assert "account/customer details" in body
    assert "raw telemetry rows" in body
    assert "payload && payload.energy" in asset
    assert "payload && payload.energy_site" in asset
    assert "site_id" not in body
    assert "address" in body
    assert "latitude" not in body
    assert "longitude" not in body
    assert "customer_name" not in body
    assert "account_id" not in body
    assert "5YJ3E1EA7JF000001" not in body


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
            "limit": 20,
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

    assert output.startswith(
        "Tesla command audit log: 1 event(s) (showing up to the last 20)"
    )
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


def test_audit_log_tool_reports_validated_limit(monkeypatch) -> None:
    captured_limit = None

    def fake_recent_command_events(limit: int) -> list[dict[str, object]]:
        nonlocal captured_limit
        captured_limit = limit
        return [{"tool": "tescmd_wake", "stage": "attempt"}]

    monkeypatch.setattr(
        tescmd_tools.audit,
        "audit_log_path",
        lambda: "/private/audit/commands.jsonl",
    )
    monkeypatch.setattr(
        tescmd_tools.audit,
        "recent_command_events",
        fake_recent_command_events,
    )

    payload = tescmd_tools.handle_audit_log({"limit": "7"})

    assert payload["limit"] == 7
    assert captured_limit == 7
    assert payload["events"] == [{"tool": "tescmd_wake", "stage": "attempt"}]


def test_audit_log_slash_output_uses_limit_context_without_exposing_path() -> None:
    output = slash._format_audit_log(  # noqa: SLF001
        {
            "ok": True,
            "path": "/home/user/.hermes/plugins/hermes-tescmd-plugin/audit/commands.jsonl",
            "limit": 3,
            "events": [
                {"tool": "tescmd_wake", "stage": "attempt", "ok": None},
                {"tool": "tescmd_security_lock", "stage": "result", "ok": True},
            ],
        }
    )

    assert output.startswith(
        "Tesla command audit log: 2 event(s) (showing up to the last 3)"
    )
    assert "tescmd_wake attempt attempted" in output
    assert "tescmd_security_lock result succeeded" in output
    assert "commands.jsonl" not in output


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


def test_mobile_access_slash_summary_is_human_readable() -> None:
    output = slash._format_command(
        "tescmd-mobile-access",
        {
            "ok": True,
            "vin": "5YJ3E1EA7JF000001",
            "mobile_access_enabled": False,
        },
    )

    assert output.startswith("/tescmd-mobile-access: success")
    assert "Mobile access: disabled." in output
    assert "Result: command accepted" not in output
    assert "5YJ3E1EA7JF000001" not in output
    assert "{" not in output


def test_mobile_access_slash_summary_handles_nested_response_shapes() -> None:
    cases = (
        ({"response": {"mobile_access_enabled": False}}, "disabled"),
        ({"data": {"mobile_access_enabled": True}}, "enabled"),
        ({"response": {"vehicle_state": {"mobile_access_enabled": True}}}, "enabled"),
    )
    for wrapper, expected_state in cases:
        payload = {"ok": True, "vin": "5YJ3E1EA7JF000001", **wrapper}

        output = slash._format_command("tescmd-mobile-access", payload)

        assert output.startswith("/tescmd-mobile-access: success")
        assert f"Mobile access: {expected_state}." in output
        assert "status not returned" not in output
        assert "5YJ3E1EA7JF000001" not in output
        assert "{" not in output


def test_alerts_slash_summary_counts_statuses_and_numbers_redacted_top_alerts() -> None:
    output = slash._format_command(
        "tescmd-alerts",
        {
            "ok": True,
            "vin": "5YJ3E1EA7JF000001",
            "alerts": [
                {
                    "severity": "warning",
                    "message": "Low tire pressure on vehicle 5YJ3E1EA7JF000001",
                    "latitude": 30.267153,
                    "longitude": -97.743057,
                },
                {
                    "level": "warning",
                    "description": "Navigation alert lat=30.267153 lng=-97.743057",
                },
                {
                    "status": "active",
                    "title": "Service required for Fleet ID 12345678901234567",
                    "callback": "https://cars.example/callback?code=secret-code&state=secret-state",
                },
            ],
        },
    )

    assert output.startswith("/tescmd-alerts: success")
    assert "Alerts: 3 recent alert(s)" in output
    assert "Alert types/statuses: active 1, warning 2" in output
    assert "#1 warning: Low tire pressure on vehicle …0001" in output
    assert (
        "#2 warning: Navigation alert lat=[coordinates redacted] lng=[coordinates redacted]"
        in output
    )
    assert "#3 active: Service required for Fleet ID …4567" in output
    assert "Result: command accepted" not in output
    assert "5YJ3E1EA7JF000001" not in output
    assert "12345678901234567" not in output
    assert "30.267153" not in output
    assert "-97.743057" not in output
    assert "secret-code" not in output
    assert "secret-state" not in output
    assert "{" not in output


def test_drivers_slash_summary_counts_without_personal_details_or_raw_payload() -> None:
    output = slash._format_command(  # noqa: SLF001
        "tescmd-drivers",
        {
            "ok": True,
            "vin": "5YJ3E1EA7JF000001",
            "drivers": [
                {
                    "name": "Alice Driver",
                    "email": "alice@example.com",
                    "phone_number": "+155****4567",
                    "driver_id": "driver-1234567890",
                    "role": "owner",
                    "status": "active",
                    "invite_url": "https://tesla.example/invite/secret-token",
                },
                {
                    "display_name": "Bob Pending",
                    "email_address": "bob@example.com",
                    "user_id": "user-0987654321",
                    "access_level": "driver",
                    "invite_status": "pending",
                },
            ],
        },
    )

    assert output.startswith("/tescmd-drivers: success")
    assert "Drivers: 2 associated driver(s) returned." in output
    assert "Driver statuses: active 1, pending 1" in output
    assert "#1 role owner, status active" in output
    assert "#2 role driver, status pending" in output
    assert "names, emails, phone numbers, invites, and ids are redacted" in output
    assert "Result: command accepted" not in output
    assert "{" not in output
    assert "5YJ3E1EA7JF000001" not in output
    assert "Alice" not in output
    assert "Bob" not in output
    assert "alice@example.com" not in output
    assert "+155****4567" not in output
    assert "driver-1234567890" not in output
    assert "secret-token" not in output


def test_energy_slash_summary_lists_products_without_raw_payload() -> None:
    output = slash._format_command(
        "tescmd-energy",
        {
            "ok": True,
            "profile": "default",
            "region": "na",
            "products": [
                {
                    "site_name": "Home Powerwall",
                    "resource_type": "battery",
                    "site_id": 12345678901234567,
                    "backup_reserve_percent": 20,
                    "latitude": 37.7749295,
                    "longitude": -122.4194155,
                },
                {
                    "asset_site_name": "Solar Roof",
                    "product_type": "solar",
                    "energy_site_id": 98765432109876543,
                },
            ],
        },
    )

    assert output.startswith("/tescmd-energy: success")
    assert "Energy products: 2 product(s) returned." in output
    assert "#1 Home Powerwall (type battery, site …4567)" in output
    assert "#2 Solar Roof (type solar, site …6543)" in output
    assert "use site_id=... with tescmd_energy_live/status" in output
    assert "Result: command accepted" not in output
    assert "12345678901234567" not in output
    assert "98765432109876543" not in output
    assert "37.7749295" not in output
    assert "-122.4194155" not in output
    assert "backup_reserve_percent" not in output
    assert "{" not in output


def test_service_slash_summary_redacts_vehicle_ids_and_avoids_raw_payload() -> None:
    output = slash._format_command(
        "tescmd-service",
        {
            "ok": True,
            "vin": "5YJ3E1EA7JF000001",
            "service": {
                "service_status": "scheduled for vehicle 5YJ3E1EA7JF000002",
                "appointment": {
                    "status": "booked",
                    "start_time": "2026-06-10T09:00:00Z",
                    "service_center": "Tesla Service 123 Main St 12345678901234567",
                },
            },
        },
    )

    assert output.startswith("/tescmd-service: success")
    assert "Service: service status scheduled for vehicle …0002" in output
    assert "1 service visit returned" in output
    assert (
        "appointment status booked, start 2026-06-10T09:00:00Z, "
        "center Tesla Service 123 Main St …4567" in output
    )
    assert "5YJ3E1EA7JF000001" not in output
    assert "5YJ3E1EA7JF000002" not in output
    assert "Tesla Service 123 Main St …4567" in output
    assert "12345678901234567" not in output
    assert "{" not in output


def test_service_slash_summary_handles_response_visit_lists_privately() -> None:
    output = slash._format_command(
        "tescmd-service",
        {
            "ok": True,
            "vin": "5YJ3E1EA7JF000001",
            "response": {
                "maintenance_status": "appointment pending for Fleet 12345678901234567",
                "service_visits": [
                    {
                        "appointment_id": "APT-SECRET-123",
                        "state": "confirmed",
                        "scheduled_time": "2026-07-01T13:30:00Z",
                        "service_center_name": "Tesla Service 5YJ3E1EA7JF000002",
                        "service_center_url": "https://cars.example.com/callback?code=secret-token-123456&state=secret-state",
                        "address": "123 Main St, Springfield",
                        "latitude": 37.7749295,
                        "longitude": -122.4194155,
                    },
                    {
                        "appointment_id": "APT-SECRET-456",
                        "state": "waiting",
                        "scheduled_time": "2026-07-02T14:00:00Z",
                        "service_center_name": "Tesla Service 98765432109876543",
                    },
                ],
            },
        },
    )

    assert output.startswith("/tescmd-service: success")
    assert "Service: maintenance status appointment pending for Fleet …4567" in output
    assert "2 service visits returned" in output
    assert "appointment state confirmed" in output
    assert "time 2026-07-01T13:30:00Z" in output
    assert "center Tesla Service …0002, 123 Main St, Springfield" in output
    assert "APT-SECRET-123" not in output
    assert "APT-SECRET-456" not in output
    assert "98765432109876543" not in output
    assert "2026-07-02T14:00:00Z" not in output
    assert "secret-token-123456" not in output
    assert "secret-state" not in output
    assert "37.7749295" not in output
    assert "-122.4194155" not in output
    assert "5YJ3E1EA7JF000001" not in output
    assert "5YJ3E1EA7JF000002" not in output
    assert "12345678901234567" not in output
    assert "{" not in output


def test_service_slash_summary_handles_nested_public_center_details_without_urls() -> (
    None
):
    output = slash._format_command(
        "tescmd-service",
        {
            "ok": True,
            "service": {
                "appointment": {
                    "status": "scheduled",
                    "service_center": {
                        "name": "Tesla Service Center",
                        "address": "3500 Deer Creek Rd, Palo Alto, CA",
                        "url": "https://cars.example.com/callback?code=secret-token-123456&state=secret-state",
                    },
                    "service_center_url": "https://cars.example.com/callback?code=another-secret&state=another-state",
                    "appointment_id": "APT-SECRET-789",
                }
            },
        },
    )

    assert output.startswith("/tescmd-service: success")
    assert (
        "appointment status scheduled, center Tesla Service Center, "
        "3500 Deer Creek Rd, Palo Alto, CA" in output
    )
    assert "cars.example.com" not in output
    assert "secret-token-123456" not in output
    assert "another-secret" not in output
    assert "APT-SECRET-789" not in output


def test_warranty_slash_summary_registers_useful_private_read_surface() -> None:
    commands = slash.command_definitions()

    assert "tescmd-warranty" in commands
    assert commands["tescmd-warranty"]["args_hint"] == "[vin]"


def test_warranty_slash_summary_redacts_ids_urls_and_raw_payload() -> None:
    output = slash._format_command(
        "tescmd-warranty",
        {
            "ok": True,
            "vin": "5YJ3E1EA7JF000001",
            "response": {
                "status": "active for vehicle 5YJ3E1EA7JF000002",
                "generated_at": "2026-06-16T12:00:00Z",
                "warranty": {
                    "warranty_terms": [
                        {
                            "name": "Basic Vehicle Limited Warranty",
                            "coverage_status": "active",
                            "end_date": "2028-06-01",
                            "odometer_limit_miles": 50000,
                            "agreement_id": "WRN-SECRET-123",
                            "details_url": "https://cars.example.com/callback?code=secret-token-123456&state=secret-state",
                        },
                        {
                            "warranty_type": "Battery and Drive Unit",
                            "status": "active",
                            "expiration_date": "2032-06-01",
                            "odometer_limit_km": 192000,
                        },
                    ]
                },
            },
        },
    )

    assert output.startswith("/tescmd-warranty: success")
    assert "Warranty: 2 terms returned" in output
    assert "status active for vehicle …0002" in output
    assert "as of 2026-06-16T12:00:00Z" in output
    assert (
        "#1 Basic Vehicle Limited Warranty (status active, ends 2028-06-01, "
        "mi limit 50000)" in output
    )
    assert (
        "#2 Battery and Drive Unit (status active, ends 2032-06-01, km limit 192000)"
        in output
    )
    assert "identifiers, URLs, and raw payload details stay out" in output
    assert "Result: command accepted" not in output
    assert "5YJ3E1EA7JF000001" not in output
    assert "5YJ3E1EA7JF000002" not in output
    assert "WRN-SECRET-123" not in output
    assert "cars.example.com" not in output
    assert "secret-token-123456" not in output
    assert "secret-state" not in output
    assert "details_url" not in output
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
    assert (
        "Top places: #1 Coffee & Charge (address/location redacted); "
        "#2 Unnamed place (address/location redacted)" in output
    )
    assert "place_ids=..." in output
    assert "456 Example Ave" not in output
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
                    {
                        "title": "Trip Planner",
                        "body": "Navigate to 456 Example Ave",
                    },
                    {
                        "title": "Cabin Comfort",
                        "body": "Private release body",
                    },
                    {
                        "title": "Dashcam Viewer",
                        "url": "https://cars.example.com/release?state=secret-state-123456",
                    },
                ],
            },
        },
    )

    assert output.startswith("/tescmd-release-notes: success")
    assert "Release notes: 5 note(s) — version 2026.14.3, status available" in output
    assert (
        "Top notes: #1 Improved Autopark for vehicle …0002; #2 Charge on Solar; #3 Trip Planner"
        in output
    )
    assert "Release notes: 2 additional note(s) hidden for brevity." in output
    assert (
        "note bodies, URLs, route text, vehicle identifiers, and coordinates stay out of slash summaries"
        in output
    )
    assert "Cabin Comfort" not in output
    assert "Dashcam Viewer" not in output
    assert "Result: command accepted" not in output
    assert "5YJ3E1EA7JF000001" not in output
    assert "5YJ3E1EA7JF000002" not in output
    assert "123 Main St" not in output
    assert "456 Example Ave" not in output
    assert "37.7749295" not in output
    assert "secret-token-123456" not in output
    assert "secret-state-123456" not in output
    assert "{" not in output


def test_release_notes_slash_summary_handles_nested_wrappers_privately() -> None:
    output = slash._format_command(
        "tescmd-release-notes",
        {
            "ok": True,
            "response": {
                "release_notes": {
                    "car_version": "2026.20.1",
                    "state": "installed",
                    "sections": [
                        {
                            "subtitle": "Road trip improvements for VIN 5YJ3E1EA7JF000003",
                            "description": "Navigate to 456 Example Ave at 37.7749295,-122.4194155",
                            "url": "https://cars.example.com/release?code=secret-code&state=secret-state",
                        },
                        {
                            "name": "Charging refinements",
                            "content": "Private route target ChIJsecretPlaceId123",
                        },
                    ],
                }
            },
        },
    )

    assert "Release notes: 2 note(s) — version 2026.20.1, status installed" in output
    assert (
        "Top notes: #1 Road trip improvements for VIN …0003; #2 Charging refinements"
        in output
    )
    assert "Result: command accepted" not in output
    assert "5YJ3E1EA7JF000003" not in output
    assert "456 Example Ave" not in output
    assert "37.7749295" not in output
    assert "-122.4194155" not in output
    assert "secret-code" not in output
    assert "secret-state" not in output
    assert "ChIJsecretPlaceId123" not in output
    assert "{" not in output


def test_schedule_slash_summaries_are_human_readable_and_privacy_safe() -> None:
    charge_output = slash._format_command(
        "tescmd-charge-schedule",
        {
            "ok": True,
            "vin": "5YJ3E1EA7JF000001",
            "charge_schedule": {
                "enabled": True,
                "next_start_time": 0,
                "schedules": [
                    {
                        "id": "98765432109876543",
                        "enabled": True,
                        "start_time": 0,
                        "end_time": 360,
                        "days_of_week": ["monday", "tuesday"],
                        "latitude": 37.7749295,
                        "longitude": -122.4194155,
                    }
                ],
            },
        },
    )
    preconditioning_output = slash._format_command(
        "tescmd-preconditioning-schedule",
        {
            "ok": True,
            "response": {
                "preconditioning_schedule_data": {
                    "scheduled_departure_enabled": False,
                    "preconditioning_schedules": [
                        {
                            "schedule_id": "5YJ3E1EA7JF000002",
                            "preconditioning_enabled": False,
                            "departure_time": "07:30",
                            "location": "123 Main St",
                        }
                    ],
                }
            },
        },
    )

    assert charge_output.startswith("/tescmd-charge-schedule: success")
    assert "Charge schedule: 1 entry returned — enabled, next/start 0" in charge_output
    assert "Top schedules: #1 id …6543, enabled yes, start 0, end 360" in charge_output
    assert "Result: command accepted" not in charge_output
    assert "5YJ3E1EA7JF000001" not in charge_output
    assert "98765432109876543" not in charge_output
    assert "37.7749295" not in charge_output
    assert "-122.4194155" not in charge_output
    assert "{" not in charge_output

    assert preconditioning_output.startswith(
        "/tescmd-preconditioning-schedule: success"
    )
    assert (
        "Preconditioning schedule: 1 entry returned — disabled"
        in preconditioning_output
    )
    assert "preconditioning enabled no" in preconditioning_output
    assert "depart 07:30" in preconditioning_output
    assert "5YJ3E1EA7JF000002" not in preconditioning_output
    assert "123 Main St" not in preconditioning_output
    assert "{" not in preconditioning_output


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


def test_heading_cardinal_labels_are_coarse_and_scan_friendly() -> None:
    assert slash._heading_cardinal(0) == "N"  # noqa: SLF001
    assert slash._heading_cardinal(44.9) == "NE"  # noqa: SLF001
    assert slash._heading_cardinal(90) == "E"  # noqa: SLF001
    assert slash._heading_cardinal(180) == "S"  # noqa: SLF001
    assert slash._heading_cardinal(271) == "W"  # noqa: SLF001
    assert slash._heading_cardinal("315") == "NW"  # noqa: SLF001
    assert slash._heading_cardinal("unknown") is None  # noqa: SLF001


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
        "Drive: shift drive, speed 0 mph, heading 271° W, power -2 kW, "
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

    assert "Drive: shift parked, speed 0 mph, heading 0° N" in output
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

    assert "Drive: shift parked, speed 0 mph, heading 0° N" in output
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


def test_config_slash_summary_reports_model_hints_and_capabilities_privately() -> None:
    output = slash._format_command(
        "tescmd-config",
        {
            "ok": True,
            "vin": "5YJ3E1EA7JF000001",
            "vehicle_config": {
                "car_type": "cybertruck",
                "car_version": "Cybertruck 5YJ3E1EA7JF000001",
                "trim_badging": "Cyberbeast",
                "exterior_color": "Stainless",
                "plg": True,
                "rear_seat_heaters": True,
                "can_accept_navigation_requests": True,
                "id_s": "12345678901234567",
            },
        },
    )

    assert output.startswith("/tescmd-config: success")
    assert (
        "Config: car type cybertruck, car version Cybertruck …0001, "
        "trim badging Cyberbeast, exterior color Stainless; "
        "capabilities powered liftgate, rear seat heaters, nav sharing"
    ) in output
    assert "Result: command accepted" not in output
    assert "5YJ3E1EA7JF000001" not in output
    assert "12345678901234567" not in output
    assert "{" not in output


def test_gui_slash_summary_reports_unit_preferences_privately() -> None:
    output = slash._format_command(
        "tescmd-gui",
        {
            "ok": True,
            "vin": "5YJ3E1EA7JF000001",
            "gui_settings": {
                "gui_distance_units": "mi/hr for 5YJ3E1EA7JF000001",
                "gui_temperature_units": "F",
                "gui_charge_rate_units": "mi/hr",
                "gui_24_hour_time": False,
                "gui_range_display": "Rated",
            },
        },
    )

    assert output.startswith("/tescmd-gui: success")
    assert (
        "GUI: distance mi/hr for …0001, temperature F, charge rate mi/hr, "
        "24h time False, range display Rated"
    ) in output
    assert "Result: command accepted" not in output
    assert "5YJ3E1EA7JF000001" not in output
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
        "Top alerts: #1 critical: Tire pressure low on …0001; #2 info: Software update ready"
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


def test_success_result_preserves_falsey_values_without_generic_fallback() -> None:
    false_output = slash._format_command(
        "tescmd-security-status",
        {"ok": True, "response": {"result": False}},
    )
    zero_output = slash._format_command(
        "tescmd-charge-limit",
        {"ok": True, "response": {"reason": 0}},
    )

    assert "Result: no" in false_output
    assert "Result: 0" in zero_output
    assert "Result: command accepted by Tesla Fleet API" not in false_output
    assert "Result: command accepted by Tesla Fleet API" not in zero_output


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
            "state": "online",
        },
        "drivers": [
            {
                "name": "Alice Driver",
                "email": "alice@example.com",
                "phone_number": "+15555551234",
                "driver_id": "driver-1234567890",
                "share_user_id": "share-0987654321",
                "invite_url": "https://tesla.example/invite/secret-token",
            }
        ],
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
            "refresh_token": "refresh-token-123456",
            "id_token": "id-token-123456",
            "oauth_token": "oauth-token-123456",
            "client_id": "client-id-123456",
            "client_secret": "client-secret-123456",
            "code": "oauth-code-123456",
            "oauth_code": "oauth-code-654321",
            "authorization_code": "authorization-code-123456",
            "auth_code": "auth-code-123456",
            "state": "oauth-state-123456",
            "oauth_state": "oauth-state-654321",
            "code_verifier": "verifier-123456",
            "code_challenge": "challenge-123456",
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
    assert redacted["vehicle"]["state"] == "online"
    assert redacted["drivers"][0]["name"] == "[REDACTED_PERSONAL]"
    assert redacted["drivers"][0]["email"] == "[REDACTED_PERSONAL]"
    assert redacted["drivers"][0]["phone_number"] == "[REDACTED_PERSONAL]"
    assert redacted["drivers"][0]["driver_id"] == "[REDACTED_PERSONAL]"
    assert redacted["drivers"][0]["share_user_id"] == "[REDACTED_PERSONAL]"
    assert redacted["drivers"][0]["invite_url"] == "[REDACTED_PERSONAL]"
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
    assert redacted["auth"]["refresh_token"] == "[REDACTED]"
    assert redacted["auth"]["id_token"] == "[REDACTED]"
    assert redacted["auth"]["oauth_token"] == "[REDACTED]"
    assert redacted["auth"]["client_id"] == "[REDACTED]"
    assert redacted["auth"]["client_secret"] == "[REDACTED]"
    assert redacted["auth"]["code"] == "[REDACTED]"
    assert redacted["auth"]["oauth_code"] == "[REDACTED]"
    assert redacted["auth"]["authorization_code"] == "[REDACTED]"
    assert redacted["auth"]["auth_code"] == "[REDACTED]"
    assert redacted["auth"]["state"] == "[REDACTED]"
    assert redacted["auth"]["oauth_state"] == "[REDACTED]"
    assert redacted["auth"]["code_verifier"] == "[REDACTED]"
    assert redacted["auth"]["code_challenge"] == "[REDACTED]"
    assert "5YJ3E1EA7JF000001" not in rendered
    assert "5YJ3E1EA7JF000002" not in rendered
    assert "5YJ3E1EA7JF000003" not in rendered
    assert "12345678901234567" not in rendered
    assert "12345678901234568" not in rendered
    assert "98765432109876543" not in rendered
    assert "Alice Driver" not in rendered
    assert "alice@example.com" not in rendered
    assert "+15555551234" not in rendered
    assert "driver-1234567890" not in rendered
    assert "share-0987654321" not in rendered
    assert "tesla.example/invite" not in rendered
    assert "secret...3456" not in rendered
    assert "refresh-token-123456" not in rendered
    assert "id-token-123456" not in rendered
    assert "oauth-token-123456" not in rendered
    assert "client-id-123456" not in rendered
    assert "client-secret-123456" not in rendered
    assert "oauth-code-123456" not in rendered
    assert "oauth-code-654321" not in rendered
    assert "authorization-code-123456" not in rendered
    assert "auth-code-123456" not in rendered
    assert "oauth-state-123456" not in rendered
    assert "oauth-state-654321" not in rendered
    assert "verifier-123456" not in rendered
    assert "challenge-123456" not in rendered
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
    assert catalog["reads"]["energy"] == "tescmd_energy_list"
    assert catalog["reads"]["warranty"] == "tescmd_vehicle_warranty"
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
    filters = {item["value"]: item for item in catalog["safety_filters"]}
    assert filters["confirm_required"]["label"] == "Confirm-gated actions"
    assert (
        filters["confirm_required"]["count"]
        == catalog["privacy_summary"]["confirm_required"]
    )
    assert (
        filters["wake_capable"]["count"] == catalog["privacy_summary"]["wake_capable"]
    )
    assert (
        filters["vehicle_identifier"]["count"]
        == catalog["privacy_summary"]["vehicle_identifier"]
    )
    assert (
        filters["location_or_destination"]["count"]
        == catalog["privacy_summary"]["location_or_destination"]
    )
    assert filters["secret_like"]["count"] == (
        catalog["privacy_summary"]["secret_or_oauth_value"]
        + catalog["privacy_summary"]["schema_sensitive"]
    )


def test_dashboard_command_safety_filters_are_stable_and_privacy_safe() -> None:
    filters = _command_safety_filters(
        [
            {
                "confirm_required": True,
                "wake_capable": False,
                "sensitive_parameters": {"vin": ["vehicle_identifier"]},
            },
            {
                "confirm_required": False,
                "wake_capable": True,
                "sensitive_parameters": {
                    "destination": ["location_or_destination"],
                    "code": ["secret_or_oauth_value", "schema_sensitive"],
                },
            },
        ]
    )

    by_value = {item["value"]: item for item in filters}
    assert by_value == {
        "confirm_required": {
            "value": "confirm_required",
            "label": "Confirm-gated actions",
            "count": 1,
        },
        "wake_capable": {
            "value": "wake_capable",
            "label": "Wake-capable reads",
            "count": 1,
        },
        "vehicle_identifier": {
            "value": "vehicle_identifier",
            "label": "Vehicle identifier parameters",
            "count": 1,
        },
        "location_or_destination": {
            "value": "location_or_destination",
            "label": "Location/destination parameters",
            "count": 1,
        },
        "secret_like": {
            "value": "secret_like",
            "label": "Secret/OAuth-like parameters",
            "count": 2,
        },
    }


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


def test_dashboard_commands_tab_shows_privacy_safety_summary() -> None:
    asset = Path("src/hermes_tescmd_plugin/dashboard/assets/index.js").read_text()
    style = Path("src/hermes_tescmd_plugin/dashboard/assets/style.css").read_text()

    assert "function commandPrivacySummary(catalog)" in asset
    assert "function commandCatalogText(value, fallback)" in asset
    assert "commandCatalogText(command.description || command.operation" in asset
    assert "Catalog privacy summary" in asset
    assert "confirm-gated" in asset
    assert "wake-capable" in asset
    assert "vehicle ID params" in asset
    assert "location/destination params" in asset
    assert "secret-like params" in asset
    assert "Schema-sensitive parameters are grouped with secret-like counts" in asset
    assert "commandPrivacySummary(catalog)" in asset
    assert ".tescmd-command-privacy" in style
    assert ".tescmd-command-privacy-grid" in style


def test_dashboard_command_search_includes_safety_and_parameter_terms() -> None:
    asset = Path("src/hermes_tescmd_plugin/dashboard/assets/index.js").read_text()

    assert "function commandSearchCorpus(command)" in asset
    assert "Object.keys(command.parameters)" in asset
    assert "command.sensitive_parameters" in asset
    assert "command.safety_notes" in asset
    assert "commandSearchCorpus(command).includes(queryText)" in asset
    assert "value).toLowerCase().includes(queryText)" not in asset


def test_dashboard_command_catalog_can_filter_by_safety_marker() -> None:
    asset = Path("src/hermes_tescmd_plugin/dashboard/assets/index.js").read_text()
    body = asset.split("function CommandCatalog", 1)[1].split(
        "function TeslaDashboard", 1
    )[0]

    assert "function commandMatchesSafetyFilter(command, safetyFilter)" in asset
    assert "Safety marker" in body
    assert "All safety markers" in body
    assert "catalog.safety_filters" in body
    assert "commandMatchesSafetyFilter(command, safetyFilter)" in body
    assert 'safetyFilter === "confirm_required"' in asset
    assert 'safetyFilter === "wake_capable"' in asset
    assert 'safetyFilter === "secret_like"' in asset
    assert 'flatFlags.has("secret_or_oauth_value")' in asset
    assert 'flatFlags.has("schema_sensitive")' in asset
    assert "commandSafetyFilter" in asset
    assert "setCommandSafetyFilter" in asset


def test_dashboard_command_catalog_has_loading_error_and_filtered_empty_states() -> (
    None
):
    asset = Path("src/hermes_tescmd_plugin/dashboard/assets/index.js").read_text()
    body = asset.split("function CommandCatalog", 1)[1].split(
        "function TeslaDashboard", 1
    )[0]

    assert "catalogLoaded" in body
    assert "Command catalog loading" in body
    assert "No Tesla vehicle command is sent while loading the catalog." in body
    assert "Command catalog unavailable" in body
    assert "catalogError" in body
    assert "The error text is sanitized before rendering" in body
    assert "catalogLoaded && !filtered.length" in body
    assert (
        "Try a different search term, category, or safety marker, or reset all command filters."
        in body
    )
    assert "retryCatalog" in body
    assert "commandCatalogLoading" in asset
    assert "setCommandCatalogLoading(true)" in asset
    assert "setCommandCatalogLoading(false)" in asset
    assert "loading: commandCatalogLoading" in asset
    assert "setCommandCatalogError(dashboardErrorMessage(err))" in asset
    assert (
        "setError(dashboardErrorMessage(err))"
        not in asset.split('api("/commands")', 1)[1].split("return () =>", 1)[0]
    )


def test_dashboard_command_catalog_can_reset_active_filters() -> None:
    asset = Path("src/hermes_tescmd_plugin/dashboard/assets/index.js").read_text()
    style = Path("src/hermes_tescmd_plugin/dashboard/assets/style.css").read_text()
    body = asset.split("function CommandCatalog", 1)[1].split(
        "function TeslaDashboard", 1
    )[0]

    assert "function activeCommandFilters" in asset
    assert "const activeFilters = activeCommandFilters" in body
    assert 'setSearch("")' in body
    assert 'setCategory("all")' in body
    assert 'setSafetyFilter("all")' in body
    assert "Reset filters" in body
    assert "Active filters" in body
    assert "Reset command filters" in body
    assert "without sending a Tesla command" in body
    assert "does not call Tesla or run a plugin command" in body
    assert "tescmd-command-active-filters" in body
    assert ".tescmd-command-active-filters" in style
    assert ".tescmd-command-reset" in style


def test_dashboard_command_catalog_sanitizes_visible_runtime_metadata() -> None:
    asset = Path("src/hermes_tescmd_plugin/dashboard/assets/index.js").read_text()
    body = asset.split("function CommandCatalog", 1)[1].split(
        "function TeslaDashboard", 1
    )[0]

    assert "function commandCatalogText(value, fallback)" in asset
    assert "return sanitizeDashboardText(value" in asset
    assert 'h("code", null, commandCatalogText(command.name' in body
    assert "commandCatalogText(command.category" in body
    assert "commandCatalogText(command.description || command.operation" in body
    assert "commandCatalogText(note" in body
    assert "commandCatalogText(command.operation" in body
    assert "commandCatalogText(command.command_name" in body
    assert 'commandCatalogText(name, "parameter")' in asset
    assert "schema.enum.map((item) => commandCatalogText" in asset
    assert "flags[name].map((item) => commandCatalogText" in asset
    assert "command.name)," not in body
    assert "command.description || command.operation)," not in body
    assert 'h("li", { key: note }, note)' not in body


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
    assert payload["target_context"]["using_override"] is True
    assert payload["target_context"]["target_override"] == "…0001"
    assert payload["display_payload"]["target_context"]["target_override"] == "…0001"
    assert payload["read_context"] == {
        "overview_reads_wake": False,
        "overview_reads_confirm": False,
        "cache_mode": "fresh Fleet API reads",
        "units": "metric",
        "section_count": 6,
        "privacy_note": "Overview refreshes are non-waking and non-confirmed; use explicit read controls for wake-enabled checks.",
    }
    assert payload["display_payload"]["read_context"] == payload["read_context"]
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


def test_dashboard_overview_read_context_is_non_waking_and_privacy_safe() -> None:
    assert _overview_read_context(False, None) == {
        "overview_reads_wake": False,
        "overview_reads_confirm": False,
        "cache_mode": "cache allowed",
        "units": "configured",
        "section_count": 6,
        "privacy_note": "Overview refreshes are non-waking and non-confirmed; use explicit read controls for wake-enabled checks.",
    }
    assert _overview_read_context(True, "us") == {
        "overview_reads_wake": False,
        "overview_reads_confirm": False,
        "cache_mode": "fresh Fleet API reads",
        "units": "us",
        "section_count": 6,
        "privacy_note": "Overview refreshes are non-waking and non-confirmed; use explicit read controls for wake-enabled checks.",
    }


def test_dashboard_options_show_safe_overview_read_mode_panel() -> None:
    asset = Path("src/hermes_tescmd_plugin/dashboard/assets/index.js").read_text()
    style = Path("src/hermes_tescmd_plugin/dashboard/assets/style.css").read_text()

    assert "function ReadContextPanel" in asset
    assert "Overview read context" in asset
    assert "Overview refreshes stay read-only" in asset
    assert "Overview refresh has elevated read flags" in asset
    assert "Wake/confirm" in asset
    assert "readContext.cache_mode" in asset
    assert "readContext.units" in asset
    assert "readContext.section_count" in asset
    assert "readContext.overview_reads_wake" in asset
    assert (
        "h(ReadContextPanel, { readContext: overview && overview.read_context })"
        in asset
    )
    assert ".tescmd-read-context" in style
    assert ".tescmd-read-context-grid" in style
    assert "readContext.vin" not in asset
    assert "readContext.id_s" not in asset


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


def test_dashboard_security_widget_lists_safe_open_closure_labels() -> None:
    asset = Path("src/hermes_tescmd_plugin/dashboard/assets/index.js").read_text()
    style = Path("src/hermes_tescmd_plugin/dashboard/assets/style.css").read_text()
    body = asset.split("function closureIsOpen", 1)[1].split(
        "function locationSummary", 1
    )[0]

    assert "const closureLabels =" in asset
    assert "function closureIsOpen(value)" in asset
    assert '"driver front door"' in asset
    assert '"front trunk"' in asset
    assert '"driver front window"' in asset
    assert "closed" in body
    assert "opened" in body
    assert "vented" in body
    assert "openLabels" in body
    assert "Open: ${security.openLabels.slice(0, 3).join" in asset
    assert "No open closures reported" in asset
    assert "tescmd-security-widget" in asset
    assert ".tescmd-security-widget em" in style
    assert 'bool("closed")' not in asset
    assert "closures[key] && closures[key] !== 0" not in asset


def test_dashboard_location_summary_shows_safe_compass_heading() -> None:
    asset = Path("src/hermes_tescmd_plugin/dashboard/assets/index.js").read_text()
    body = asset.split("function locationSummary", 1)[1].split(
        "function selectedVehicle", 1
    )[0]

    assert "function compassHeadingLabel(heading)" in body
    assert "vehicle_heading" in body
    assert "heading ${Math.round(normalized)}° ${directions[index]}" in body
    assert "speed unavailable" in body
    assert "heading unavailable" in body
    assert "Speed and heading unavailable" in body
    assert "location.native_latitude" not in body
    assert "drive.native_latitude" not in body
    assert "location.native_longitude" not in body
    assert "drive.native_longitude" not in body
    assert 'precision === "precise"' in body
    assert "precise coordinates hidden" in body
    assert "precise coordinates visible" in body


def test_dashboard_map_load_failure_has_privacy_safe_error_state() -> None:
    asset = Path("src/hermes_tescmd_plugin/dashboard/assets/index.js").read_text()
    style = Path("src/hermes_tescmd_plugin/dashboard/assets/style.css").read_text()
    body = asset.split("function LeafletMap", 1)[1].split(
        "function commandCatalogText", 1
    )[0]

    assert 'useState("idle")' in body
    assert 'setMapStatus("loading")' in body
    assert 'setMapStatus("ready")' in body
    assert 'setMapStatus("error")' in body
    assert "Map could not load" in body
    assert "The coordinates remain hidden here" in body
    assert "is not retried as a Tesla command" in body
    assert "Loading map…" in body
    assert "tescmd-map-error" in style
    assert "tescmd-map-loading" in style
    assert ").catch(() => {});" not in body
    assert "37.331" not in body
    assert "destination" not in body.lower()


def test_dashboard_vehicle_picker_uses_safe_model_hints_not_visible_ids() -> None:
    asset = Path("src/hermes_tescmd_plugin/dashboard/assets/index.js").read_text()

    assert "function vehicleModelHint" in asset
    assert "vehicle_config" in asset
    assert "config.car_type" in asset
    assert "config.trim_badging" in asset
    assert "vehiclePickerLabel(vehicle, index)" in asset
    assert "Vehicle menu labels show safe model hints only" in asset
    assert "raw override field is hidden by default" in asset
    assert "`${name} — ${hint} — ${state}`" in asset
    assert "`${name} — ${state}`" in asset
    assert "`${name} — ${id} — ${state}`" not in asset
    assert "`${name} — ${vehicle.vin}" not in asset
    assert "`${name} — ${vehicle.id_s}" not in asset


def test_dashboard_target_context_panel_shows_safe_default_vs_override() -> None:
    asset = Path("src/hermes_tescmd_plugin/dashboard/assets/index.js").read_text()
    style = Path("src/hermes_tescmd_plugin/dashboard/assets/style.css").read_text()

    assert "function TargetContextPanel" in asset
    assert "Dashboard target context" in asset
    assert "Temporary vehicle override active" in asset
    assert "Using configured default target" in asset
    assert "Target identifiers are redacted here" in asset
    assert "overview && overview.target_context" in asset
    assert "tescmd-target-context-override" in asset
    assert "tescmd-target-context-grid" in asset
    assert ".tescmd-target-context" in style
    assert ".tescmd-target-context-grid" in style
    assert "targetContext.target_override" in asset
    assert "targetContext.configured_default" in asset
    assert "targetContext.vin" not in asset
    assert "targetContext.id_s" not in asset


def test_dashboard_overview_target_context_redacts_identifiers(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    config.save_config(
        config.PluginConfig(profile="dashboard", default_vin="5YJ3E1EA7JF000001")
    )

    default_context = _overview_target_context("dashboard", None, None)
    override_context = _overview_target_context("dashboard", "12345678901234567", "na")

    assert default_context == {
        "profile": "dashboard",
        "region": "configured",
        "using_override": False,
        "using_configured_default": True,
        "target_override": None,
        "configured_default": "…0001",
        "privacy_note": "Dashboard target context redacts VIN/Fleet IDs and only indicates whether reads use a temporary override or the configured default.",
    }
    assert override_context["using_override"] is True
    assert override_context["using_configured_default"] is False
    assert override_context["target_override"] == "…4567"
    assert override_context["configured_default"] == "…0001"
    assert "5YJ3E1EA7JF000001" not in json.dumps(default_context)
    assert "12345678901234567" not in json.dumps(override_context)


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


def test_dashboard_last_read_summary_surfaces_access_service_mobile_reads_privately() -> (
    None
):
    asset = Path("src/hermes_tescmd_plugin/dashboard/assets/index.js").read_text()
    style = Path("src/hermes_tescmd_plugin/dashboard/assets/style.css").read_text()
    body = asset.split("function DashboardReadSummary", 1)[1].split(
        "function vehicleAvailability", 1
    )[0]

    assert "function serviceAppointments(payload)" in asset
    assert "function serviceAppointmentLabel(appointment, fallback)" in asset
    assert "function mobileAccessContainers(payload)" in asset
    assert "function mobileAccessValue(payload, ...keys)" in asset
    assert "function mobileAccessBadge(label, payload, ...keys)" in asset
    assert 'lastReadKind === "mobile-access"' in body
    assert 'lastReadKind === "drivers"' in body
    assert 'lastReadKind === "service"' in body
    assert "Access summary" in body
    assert "Service summary" in body
    assert "Top visits: ${topVisits.join" in body
    assert "service_appointments" in body
    assert "upcoming_appointments" in body
    assert "Appointment IDs, service-center addresses, raw booking URLs" in body
    assert "customer contact details stay" in body
    assert "Mobile access summary" in body
    assert "remote access, read, command, status, and source hints" in body
    assert "account contact fields, tokens, callback values" in body
    assert "ready_for_vehicle_reads" in body
    assert "ready_for_vehicle_commands" in body
    assert "mobileAccessValue(payload" in body
    assert "names, emails, phone numbers, invite links" in body
    assert "mobile access ${access}" in body
    assert "reads ${yesNoUnknown" in body
    assert "commands ${yesNoUnknown" in body
    assert "source = mobileAccessBadge" in body
    assert "arrayCount(payload" in body
    assert "sanitizeDashboardText(badge" in body
    assert (
        "Visible read summaries omit VINs, Fleet IDs, tokens, destinations, and precise coordinates"
        in body
    )
    assert "private appointment IDs" not in body
    assert "appointment.id" not in asset
    assert "appointment.url" not in asset
    assert "appointment.address" not in asset
    assert "appointment.email" not in asset
    assert "appointment.phone" not in asset
    assert "5YJ3E1EA7JF000001" not in body
    assert "lat" not in body
    assert "longitude" not in body
    assert "setLastReadKind(kind)" in asset
    assert 'setLastReadKind("")' in asset
    assert "h(DashboardReadSummary, { detail, lastReadKind })" in asset
    assert ".tescmd-read-summary" in style
    assert ".tescmd-read-summary-badges" in style
    assert "payload.email" not in body
    assert "payload.phone" not in body
    assert "payload.name" not in body
    assert "appointment_id" not in body
    assert "invite_url" not in body


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


def test_dashboard_read_supports_warranty_without_wake_confirm_flags(
    monkeypatch,
) -> None:
    calls: list[tuple[str, dict]] = []

    def fake_run(tool_name, args=None):
        calls.append((tool_name, args or {}))
        return {"ok": True, "warranty": {"status": "active"}}

    monkeypatch.setattr("hermes_tescmd_plugin.dashboard.plugin_api._run", fake_run)

    payload = read(
        "warranty",
        vin="5YJ3E1EA7JF000001",
        profile="daily",
        region="eu",
        wake=True,
        confirm=True,
        no_cache=True,
    )

    assert payload == {
        "ok": True,
        "warranty": {"status": "active"},
        "display_payload": {"ok": True, "warranty": {"status": "active"}},
    }
    assert calls == [
        (
            "tescmd_vehicle_warranty",
            {
                "profile": "daily",
                "vin": "5YJ3E1EA7JF000001",
                "region": "eu",
            },
        )
    ]


def test_dashboard_read_supports_energy_list_without_vehicle_side_effect_flags(
    monkeypatch,
) -> None:
    calls: list[tuple[str, dict]] = []

    def fake_run(tool_name, args=None):
        calls.append((tool_name, args or {}))
        return {"ok": True, "products": [{"status": "online"}]}

    monkeypatch.setattr("hermes_tescmd_plugin.dashboard.plugin_api._run", fake_run)

    payload = read(
        "energy",
        profile="daily",
        region="eu",
        wake=True,
        confirm=True,
        no_cache=True,
    )

    assert payload == {
        "ok": True,
        "products": [{"status": "online"}],
        "display_payload": {"ok": True, "products": [{"status": "online"}]},
    }
    assert calls == [("tescmd_energy_list", {"profile": "daily", "region": "eu"})]


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
