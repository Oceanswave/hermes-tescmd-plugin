from __future__ import annotations

import hashlib
import ipaddress
import json
import os
from pathlib import Path
from urllib.parse import urlparse
from typing import Any

import httpx
from cryptography.hazmat.primitives import serialization

from . import auth, client, config

WELL_KNOWN_PATH = ".well-known/appspecific/com.tesla.3p.public-key.pem"


def _normalize_domain(value: Any, *, allow_local: bool = False) -> str | None:
    if value is None or value == "":
        return None
    text = str(value).strip().lower().rstrip(".")
    if not text:
        return None
    if any(ch.isspace() for ch in text) or any(ch in text for ch in "/?#@"):
        raise client.TeslaAPIError("domain must be a hostname only; do not include scheme, path, query, userinfo, or whitespace.")
    if "://" in text:
        raise client.TeslaAPIError("domain must not include a URL scheme; provide only the hostname.")
    parsed = urlparse(f"//{text}")
    hostname = parsed.hostname
    if not hostname or parsed.username or parsed.password or parsed.path not in ("", None):
        raise client.TeslaAPIError("domain must be a hostname only.")
    if parsed.port is not None:
        raise client.TeslaAPIError("domain must not include a port; Tesla virtual-key hosting requires HTTPS on the standard port.")
    try:
        ascii_host = hostname.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise client.TeslaAPIError("domain is not a valid DNS hostname.") from exc
    if len(ascii_host) > 253 or any(not label or len(label) > 63 for label in ascii_host.split(".")):
        raise client.TeslaAPIError("domain is not a valid DNS hostname.")
    if ascii_host in {"localhost", "localhost.localdomain"}:
        raise client.TeslaAPIError("domain must be public HTTPS hostname, not localhost.")
    try:
        ip = ipaddress.ip_address(ascii_host)
    except ValueError:
        ip = None
    if ip and not allow_local and (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved):
        raise client.TeslaAPIError("domain must not be a private, loopback, link-local, or reserved IP address.")
    return ascii_host


def _validate_percent(name: str, value: Any) -> int:
    try:
        pct = int(value)
    except (TypeError, ValueError) as exc:
        raise client.TeslaAPIError(f"{name} must be an integer percentage.") from exc
    if not 0 <= pct <= 100:
        raise client.TeslaAPIError(f"{name} must be between 0 and 100.")
    return pct


def _safe_export_path(path_text: str, *, profile: str) -> Path:
    root = config.get_plugin_home() / "exports" / profile
    root.mkdir(parents=True, exist_ok=True)
    try:
        root.chmod(0o700)
    except OSError:
        pass
    candidate = Path(path_text).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = candidate.resolve()
    if root.resolve() not in candidate.parents and candidate != root.resolve():
        raise client.TeslaAPIError(f"output_path must stay under the plugin export directory: {root}")
    if candidate.exists():
        raise client.TeslaAPIError(f"Refusing to overwrite existing file: {candidate}")
    return candidate


def _profile(args: dict[str, Any]) -> str:
    try:
        return config.validate_profile(args.get("profile") or config.DEFAULT_PROFILE)
    except config.PluginStateError as exc:
        raise client.TeslaAPIError(str(exc)) from exc


def _resolve_vin(args: dict[str, Any], profile: str) -> str:
    vin = args.get("vin")
    if not vin:
        cfg = config.load_config(profile)
        vin = cfg.default_vin
    if not vin:
        raise client.TeslaAPIError("No vehicle identifier was provided and no default vehicle identifier is configured for this profile.")
    return client.validate_vin(str(vin))


def _require_full_vin(value: str, *, operation: str) -> str:
    if client.is_tesla_vin(value):
        return value
    raise client.TeslaAPIError(
        f"{operation} requires a full 17-character VIN. Tesla redacted VINs in this account's product response, "
        "so provide the real VIN explicitly with the vin argument. Opaque Fleet vehicle IDs/id_s work for vehicle path endpoints but not for this VIN-only Fleet endpoint."
    )


def _resolve_full_vin(args: dict[str, Any], fleet_client: client.TeslaFleetClient, *, operation: str) -> str:
    value = _resolve_vin(args, fleet_client.profile)
    if client.is_tesla_vin(value):
        return value
    vehicles = fleet_client.list_vehicles()
    for vehicle in vehicles:
        if not isinstance(vehicle, dict):
            continue
        identifiers = {str(vehicle.get(key)) for key in ("id_s", "vehicle_id", "id", "vin") if vehicle.get(key) is not None}
        candidate = vehicle.get("vin")
        if value in identifiers and isinstance(candidate, str) and client.is_tesla_vin(candidate):
            return candidate
    return _require_full_vin(value, operation=operation)


def _resolve_full_vins(args: dict[str, Any], fleet_client: client.TeslaFleetClient, *, operation: str) -> list[str]:
    requested = args.get("vins")
    values: list[Any]
    if requested is None:
        maybe_single = args.get("vin")
        if maybe_single:
            values = [maybe_single]
        else:
            vehicles = fleet_client.list_vehicles()
            values = [vehicle.get("vin") for vehicle in vehicles if isinstance(vehicle, dict) and vehicle.get("vin")]
    elif isinstance(requested, str):
        values = [part.strip() for part in requested.split(",") if part.strip()]
    elif isinstance(requested, list):
        values = requested
    else:
        raise client.TeslaAPIError("vins must be an array of full VIN strings or a comma-separated string.")
    vins = [_require_full_vin(str(value), operation=operation) for value in values if value]
    if not vins:
        raise client.TeslaAPIError(f"{operation} requires at least one full 17-character VIN.")
    return vins


def _public_vin(vin: str | None) -> str | None:
    return "[REDACTED]" if vin else None


def _fleet_client(args: dict[str, Any]) -> client.TeslaFleetClient:
    return client.TeslaFleetClient(profile=_profile(args), region_override=args.get("region"))


def _resolve_site_id(args: dict[str, Any]) -> int:
    site_id = args.get("site_id")
    if site_id is None:
        raise client.TeslaAPIError("site_id is required for this energy operation.")
    try:
        value = int(site_id)
    except (TypeError, ValueError) as exc:
        raise client.TeslaAPIError("site_id must be a positive integer.") from exc
    if value <= 0:
        raise client.TeslaAPIError("site_id must be a positive integer.")
    return value


def _result_from_command(command_name: str, vin: str, response: Any, *, region: str) -> dict[str, Any]:
    ok = True
    if isinstance(response, dict) and response.get("result") is False:
        ok = False
    return {
        "ok": ok,
        "command": command_name,
        "vin": _public_vin(vin),
        "region": region,
        "response": response,
    }


def _result_payload(*, fleet_client: client.TeslaFleetClient, result: Any, result_key: str, vin: str | None = None, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = {
        "ok": True,
        "profile": fleet_client.profile,
        "region": fleet_client.region,
        result_key: result,
    }
    if vin is not None:
        payload["vin"] = _public_vin(vin)
    if extra:
        payload.update(extra)
    return payload


def _redirect_uri_for(cfg: config.PluginConfig, *, redirect_port: int | None = None) -> tuple[int, str | None]:
    port = int(redirect_port or cfg.redirect_port or 8765)
    return port, config.resolve_oauth_redirect_uri(cfg)


def _key_presence(profile: str) -> tuple[Path | None, Path | None, bool]:
    private_path, public_path = _public_key_paths(profile)
    present = bool(private_path and public_path and private_path.exists() and public_path.exists())
    return private_path, public_path, present


def _bootstrap_status(*, profile: str, cfg: config.PluginConfig, auth_state: config.AuthState | None = None, pending: config.PendingAuthState | None = None) -> dict[str, Any]:
    auth_state = auth_state or config.load_auth_state(profile)
    pending = pending if pending is not None else config.load_pending_auth(profile)
    _, _, key_present = _key_presence(profile)
    has_domain = bool(cfg.domain)
    authenticated = auth_state.is_authenticated()
    key_validation = _hosted_key_validation(profile=profile, cfg=cfg) if has_domain and key_present else {
        "accessible": False,
        "local_fingerprint": None,
        "remote_fingerprint": None,
        "matches_local_key": False,
    }
    return {
        "app_configured": bool(cfg.client_id),
        "login_ready": bool(cfg.client_id),
        "pending_login": pending is not None,
        "authenticated": authenticated,
        "ready_for_vehicle_reads": bool(authenticated),
        "ready_for_vehicle_commands": bool(authenticated and cfg.default_vin),
        "ready_for_signed_commands": bool(authenticated and cfg.default_vin and key_present),
        "ready_for_partner_registration": bool(cfg.client_id and cfg.client_secret and cfg.domain),
        "ready_for_energy_reads": bool(authenticated),
        "ready_for_google_place_search": bool(cfg.google_maps_api_key),
        "missing_for_vehicle_commands": [name for name, missing in (("authenticated", not authenticated), ("default_vin", not bool(cfg.default_vin))) if missing],
        "missing_for_signed_commands": [name for name, missing in (("authenticated", not authenticated), ("default_vin", not bool(cfg.default_vin)), ("vehicle_command_key", not key_present)) if missing],
        "partner_ready": bool(cfg.client_id and cfg.client_secret and cfg.domain),
        "partner_registered_candidate": bool(cfg.client_id and cfg.client_secret and cfg.domain),
        "key_present": key_present,
        "public_key_accessible": key_validation["accessible"],
        "public_key_matches_local_key": key_validation["matches_local_key"],
        "key_hosting_ready": bool(key_validation["matches_local_key"]),
        "enrollment_ready": bool(key_validation["matches_local_key"] and cfg.client_secret),
    }


def _bootstrap_missing(cfg: config.PluginConfig) -> dict[str, bool]:
    return {
        "client_id": not bool(cfg.client_id),
        "client_secret": not bool(cfg.client_secret),
        "domain": not bool(cfg.domain),
        "default_vin": not bool(cfg.default_vin),
    }


def _bootstrap_next_steps(*, cfg: config.PluginConfig, bootstrap: dict[str, Any], redirect_uri: str | None) -> tuple[str, list[str]]:
    if not cfg.client_id:
        return (
            "configure_app",
            [
                f"Create or open your Tesla Developer application and add this public OAuth callback URL: {redirect_uri or 'https://<your-domain>/callback'}",
                f"Use these Tesla OAuth scopes during app setup/login: {', '.join(cfg.scopes)}",
                "Follow the README configuration checklist and edit the plugin config file with your Tesla app values.",
            ],
        )
    if not bootstrap["authenticated"]:
        return (
            "auth_login",
            [
                "Tesla app credentials are saved. Run tescmd_auth_login and open the returned auth_url.",
                "After Tesla redirects to the public callback URL, copy the full redirected URL and run tescmd_auth_complete with callback_url.",
            ],
        )
    if cfg.domain and not bootstrap["key_present"]:
        return (
            "key_generate",
            [
                "Authentication is working. Generate a vehicle-command key with tescmd_key_generate.",
                "Then host the public key at your domain and validate it with tescmd_key_validate.",
            ],
        )
    if bootstrap["key_present"] and cfg.domain and not bootstrap["public_key_accessible"]:
        return (
            "key_validate",
            [
                "The public key is not reachable at the expected .well-known URL yet.",
                "Serve the public key at your HTTPS domain root following the README manual-hosting instructions, then run tescmd_key_validate.",
            ],
        )
    if bootstrap["key_present"] and cfg.domain and not bootstrap["public_key_matches_local_key"]:
        return (
            "key_deploy",
            [
                "A public key is reachable, but it does not match the local vehicle-command key configured in the plugin.",
                "Redeploy the correct public key with tescmd_key_deploy, then rerun tescmd_key_validate.",
            ],
        )
    if bootstrap["key_present"] and cfg.domain and not cfg.client_secret:
        return (
            "setup",
            [
                "The hosted public key matches the local key, but client_secret is still missing for partner registration.",
                "Edit the plugin config file to add client_secret if you want partner registration and Tesla virtual-key enrollment.",
            ],
        )
    if bootstrap["enrollment_ready"]:
        return (
            "auth_register",
            [
                "Partner-registration prerequisites are in place and the hosted public key matches the local key.",
                "Run tescmd_auth_register and then tescmd_key_enroll.",
            ],
        )
    return (
        "vehicle_list",
        [
            "Bootstrap is complete enough for read-only Fleet API usage.",
            "Run tescmd_vehicle_list and then safe read-only vehicle status tools.",
        ],
    )


def _bootstrap_payload(*, profile: str, cfg: config.PluginConfig, auth_state: config.AuthState | None = None, pending: config.PendingAuthState | None = None, redirect_port: int | None = None) -> dict[str, Any]:
    auth_state = auth_state or config.load_auth_state(profile)
    pending = pending if pending is not None else config.load_pending_auth(profile)
    port, redirect_uri = _redirect_uri_for(cfg, redirect_port=redirect_port)
    bootstrap = _bootstrap_status(profile=profile, cfg=cfg, auth_state=auth_state, pending=pending)
    next_action, next_steps = _bootstrap_next_steps(cfg=cfg, bootstrap=bootstrap, redirect_uri=redirect_uri)
    _, public_path, key_present = _key_presence(profile)
    expected_public_key_url = f"https://{cfg.domain}/{WELL_KNOWN_PATH}" if cfg.domain and key_present else None
    enrollment_url = f"https://tesla.com/_ak/{cfg.domain}" if cfg.domain and key_present else None
    return {
        "redirect_port": port,
        "redirect_uri": redirect_uri,
        "missing": _bootstrap_missing(cfg),
        "bootstrap": bootstrap,
        "next_action": next_action,
        "next_steps": next_steps,
        "expected_public_key_url": expected_public_key_url,
        "enrollment_url": enrollment_url,
        "public_key_path": str(public_path) if public_path and public_path.exists() else None,
    }


def handle_status(args: dict[str, Any]) -> dict[str, Any]:
    profile = _profile(args)
    cfg = config.load_config(profile)
    auth_state = config.load_auth_state(profile)
    pending = config.load_pending_auth(profile)
    payload = {
        "ok": True,
        "profile": profile,
        "region": auth_state.region or cfg.region,
        "configured": bool(cfg.client_id),
        "authenticated": auth_state.is_authenticated(),
        "pending_login": pending is not None,
        "domain": cfg.domain,
        "default_vin": _public_vin(cfg.default_vin),
        "google_maps_places_ready": bool(cfg.google_maps_api_key),
        "scopes": auth_state.scopes or [scope for scope in cfg.scopes if scope not in config.PARTNER_ONLY_SCOPES],
        "partner_only_scopes": [scope for scope in cfg.scopes if scope in config.PARTNER_ONLY_SCOPES],
        "expires_at": auth_state.expires_at,
    }
    payload.update(_bootstrap_payload(profile=profile, cfg=cfg, auth_state=auth_state, pending=pending))
    _, public_path, key_present = _key_presence(profile)
    payload["key"] = {
        "present": key_present,
        "public_key_path": str(public_path) if public_path and public_path.exists() else None,
        "fingerprint": _public_key_fingerprint(public_path) if public_path and public_path.exists() else None,
    }
    return payload


def _mapped_payload(spec: Any, args: dict[str, Any]) -> dict[str, Any] | None:
    payload = dict(getattr(spec, "fixed_payload", {}) or {})
    payload_mode = getattr(spec, "payload_mode", "mapped")

    if payload_mode == "managed_location":
        lat = args.get("lat")
        lon = args.get("lon")
        if lat is None or lon is None:
            raise client.TeslaAPIError("Both lat and lon are required for managed charger location.")
        return {"location": {"lat": float(lat), "lon": float(lon)}}

    if payload_mode == "navigation_place_ids":
        raw_place_ids = args.get("place_ids")
        if not isinstance(raw_place_ids, list) or not raw_place_ids:
            raise client.TeslaAPIError("place_ids must be a non-empty array of Google Maps Place IDs.")
        encoded: list[str] = []
        for item in raw_place_ids:
            if not isinstance(item, str):
                raise client.TeslaAPIError("Every place_id must be a string.")
            place_id = item.strip()
            if place_id.startswith("refId:"):
                place_id = place_id.removeprefix("refId:")
            if not place_id or any(ch in place_id for ch in ",\x00"):
                raise client.TeslaAPIError("Google Maps Place IDs must be non-empty and must not contain commas or NUL bytes.")
            encoded.append(f"refId:{place_id}")
        return {"waypoints": ",".join(encoded)}

    for arg_name, payload_name in getattr(spec, "payload_fields", ()):
        if arg_name not in args:
            continue
        value = args[arg_name]
        if value is None:
            continue
        payload[payload_name] = value

    return payload or None


HIGH_RISK_VEHICLE_COMMANDS = {
    "door_unlock",
    "remote_start_drive",
    "set_valet_mode",
    "reset_valet_pin",
    "speed_limit_activate",
    "speed_limit_deactivate",
    "speed_limit_set_limit",
    "speed_limit_clear_pin",
    "set_pin_to_drive",
    "reset_pin_to_drive_pin",
    "clear_pin_to_drive_admin",
    "speed_limit_clear_pin_admin",
    "guest_mode",
    "erase_user_data",
}


def _require_confirm(args: dict[str, Any], action: str) -> None:
    if not args.get("confirm"):
        raise client.TeslaAPIError(f"confirm=true is required before running high-risk action: {action}.")


def _handle_vehicle_command(spec: Any, args: dict[str, Any]) -> dict[str, Any]:
    _require_confirm(args, spec.command_name)
    fleet_client = _fleet_client(args)
    # Signed Vehicle Command Protocol HMAC personalization uses the full VIN,
    # even when Fleet read endpoints accept id_s/vehicle_id aliases. Resolve
    # aliases from the product list before building signed commands.
    vin = _resolve_full_vin(args, fleet_client, operation=spec.command_name)
    response = fleet_client.vehicle_command(vin, spec.command_name, _mapped_payload(spec, args))
    return _result_from_command(spec.command_name, vin, response, region=fleet_client.region)


def execute(spec: Any, args: dict[str, Any]) -> dict[str, Any]:
    if getattr(spec, "operation", None) == "vehicle_command":
        return _handle_vehicle_command(spec, args)
    operation = OPERATIONS.get(spec.operation)
    if operation is None:
        raise client.TeslaAPIError(f"Unsupported operation: {spec.operation}")
    return operation(args)


def _public_key_paths(profile: str) -> tuple[Path | None, Path | None]:
    cfg = config.load_config(profile)
    private_path = Path(cfg.vehicle_command_key_private_path) if cfg.vehicle_command_key_private_path else None
    public_path = Path(cfg.vehicle_command_key_public_path) if cfg.vehicle_command_key_public_path else None
    return private_path, public_path


def _public_key_fingerprint(public_path: Path) -> str:
    public_key = serialization.load_pem_public_key(public_path.read_bytes())
    der = public_key.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    return hashlib.sha256(der).hexdigest()


def _pem_fingerprint(pem_text: str) -> str | None:
    try:
        public_key = serialization.load_pem_public_key(pem_text.encode())
    except Exception:
        return None
    der = public_key.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    return hashlib.sha256(der).hexdigest()


def _hosted_key_validation(*, profile: str, cfg: config.PluginConfig) -> dict[str, Any]:
    _, public_path = _public_key_paths(profile)
    local_fingerprint = _public_key_fingerprint(public_path) if public_path and public_path.exists() else None
    if not cfg.domain:
        return {
            "accessible": False,
            "local_fingerprint": local_fingerprint,
            "remote_fingerprint": None,
            "matches_local_key": False,
        }

    remote_fingerprint = None
    try:
        response = client.httpx.get(f"https://{cfg.domain}/{WELL_KNOWN_PATH}", follow_redirects=True, timeout=10)
        remote_fingerprint = _pem_fingerprint(response.text) if response.status_code == 200 else None
        accessible = response.status_code == 200 and remote_fingerprint is not None
    except client.httpx.HTTPError:
        accessible = False
    return {
        "accessible": accessible,
        "local_fingerprint": local_fingerprint,
        "remote_fingerprint": remote_fingerprint,
        "matches_local_key": bool(accessible and local_fingerprint and remote_fingerprint and local_fingerprint == remote_fingerprint),
    }


def handle_auth_login(args: dict[str, Any]) -> dict[str, Any]:
    profile = _profile(args)
    cfg = config.load_config(profile)
    if not cfg.client_id:
        _, redirect_uri = _redirect_uri_for(cfg, redirect_port=args.get("redirect_port"))
        raise client.TeslaAPIError(
            "Edit the plugin config file first so the plugin knows your Tesla client ID. "
            f"Expected public callback URL: {redirect_uri or 'https://<your-domain>/callback'}. "
            f"Required scopes: {', '.join(cfg.scopes)}. See the README configuration checklist."
        )
    scopes = args.get("scopes")
    if scopes is not None and not isinstance(scopes, list):
        raise client.TeslaAPIError("scopes must be an array of strings when provided.")
    return auth.start_login(profile, redirect_port=args.get("redirect_port"), scopes=scopes)


def handle_auth_complete(args: dict[str, Any]) -> dict[str, Any]:
    _require_confirm(args, "auth_complete")
    return auth.complete_login(
        _profile(args),
        callback_url=args.get("callback_url"),
        code=args.get("code"),
        state=args.get("state"),
    )


def handle_auth_status(args: dict[str, Any]) -> dict[str, Any]:
    profile = _profile(args)
    payload = auth.auth_status(profile)
    cfg = config.load_config(profile)
    auth_state = config.load_auth_state(profile)
    pending = config.load_pending_auth(profile)
    payload["bootstrap"] = _bootstrap_status(profile=profile, cfg=cfg, auth_state=auth_state, pending=pending)
    return payload


def handle_auth_refresh(args: dict[str, Any]) -> dict[str, Any]:
    _require_confirm(args, "auth_refresh")
    return auth.refresh_login(_profile(args))


def handle_auth_import(args: dict[str, Any]) -> dict[str, Any]:
    _require_confirm(args, "auth_import")
    auth_payload = args.get("auth")
    if not isinstance(auth_payload, (dict, str)):
        raise client.TeslaAPIError("auth must be an exported auth object or JSON string.")
    return auth.import_auth(_profile(args), auth_payload)


def handle_auth_export(args: dict[str, Any]) -> dict[str, Any]:
    _require_confirm(args, "auth_export")
    return auth.export_auth(_profile(args), output_path=args.get("output_path"))


def handle_auth_register(args: dict[str, Any]) -> dict[str, Any]:
    _require_confirm(args, "auth_register")
    return auth.register_partner(_profile(args))


def handle_auth_logout(args: dict[str, Any]) -> dict[str, Any]:
    _require_confirm(args, "auth_logout")
    profile = _profile(args)
    config.clear_auth_state(profile)
    config.clear_pending_auth(profile)
    return {"ok": True, "profile": profile, "authenticated": False, "pending_login": False}


def handle_key_generate(args: dict[str, Any]) -> dict[str, Any]:
    _require_confirm(args, "key_generate")
    profile = _profile(args)
    private_path, public_path = _public_key_paths(profile)
    force = bool(args.get("force", False))
    if private_path and public_path and private_path.exists() and public_path.exists() and not force:
        return {
            "ok": True,
            "profile": profile,
            "status": "exists",
            "private_key_present": True,
            "public_key_path": str(public_path),
            "fingerprint": _public_key_fingerprint(public_path),
        }
    payload = auth.generate_vehicle_command_keypair(profile, domain=config.load_config(profile).domain, force=force)
    public_key_path = Path(payload["public_key_path"])
    return {
        "ok": True,
        "profile": profile,
        "status": "generated",
        "private_key_present": True,
        "public_key_path": str(public_key_path),
        "public_key_url": payload.get("public_key_url"),
        "enrollment_url": payload.get("enrollment_url"),
        "fingerprint": _public_key_fingerprint(public_key_path),
    }


def handle_key_show(args: dict[str, Any]) -> dict[str, Any]:
    profile = _profile(args)
    cfg = config.load_config(profile)
    private_path, public_path = _public_key_paths(profile)
    present = bool(private_path and public_path and private_path.exists() and public_path.exists())
    if not present:
        return {"ok": True, "profile": profile, "status": "not_found", "key_dir": str(config.get_plugin_home() / 'keys' / profile)}
    assert public_path is not None
    return {
        "ok": True,
        "profile": profile,
        "status": "found",
        "private_key_present": True,
        "public_key_path": str(public_path),
        "fingerprint": _public_key_fingerprint(public_path),
        "expected_public_key_url": f"https://{cfg.domain}/{WELL_KNOWN_PATH}" if cfg.domain else None,
        "enrollment_url": f"https://tesla.com/_ak/{cfg.domain}" if cfg.domain else None,
    }


def handle_key_validate(args: dict[str, Any]) -> dict[str, Any]:
    profile = _profile(args)
    cfg = config.load_config(profile)
    if not cfg.domain:
        raise client.TeslaAPIError("No domain configured. Edit the plugin config file with a domain first.")
    url = f"https://{cfg.domain}/{WELL_KNOWN_PATH}"
    validation = _hosted_key_validation(profile=profile, cfg=cfg)
    return {
        "ok": True,
        "profile": profile,
        "domain": cfg.domain,
        "url": url,
        "accessible": validation["accessible"],
        "local_fingerprint": validation["local_fingerprint"],
        "remote_fingerprint": validation["remote_fingerprint"],
        "matches_local_key": validation["matches_local_key"],
    }


def handle_key_enroll(args: dict[str, Any]) -> dict[str, Any]:
    profile = _profile(args)
    cfg = config.load_config(profile)
    private_path, public_path = _public_key_paths(profile)
    if not (private_path and public_path and private_path.exists() and public_path.exists()):
        raise client.TeslaAPIError("No key pair found. Run tescmd_key_generate first.")
    if not cfg.domain:
        raise client.TeslaAPIError("No domain configured. Edit the plugin config file with a domain first.")
    key_status = handle_key_validate(args)
    if not (key_status["accessible"] and key_status["matches_local_key"]):
        raise client.TeslaAPIError("Hosted public key must be reachable and match the local key before enrollment. Run tescmd_key_deploy and tescmd_key_validate first.")
    return {
        "ok": True,
        "profile": profile,
        "domain": cfg.domain,
        "fingerprint": _public_key_fingerprint(public_path),
        "enroll_url": f"https://tesla.com/_ak/{cfg.domain}",
        "public_key_url": key_status["url"],
        "public_key_accessible": key_status["accessible"],
        "matches_local_key": key_status["matches_local_key"],
        "message": "Open the enroll_url on your phone and approve Add Virtual Key in the Tesla app.",
    }


def handle_key_unenroll(args: dict[str, Any]) -> dict[str, Any]:
    profile = _profile(args)
    cfg = config.load_config(profile)
    revoke_url = None
    if cfg.client_id:
        revoke_url = f"https://auth.tesla.com/user/revoke/consent?revoke_client_id={cfg.client_id}&back_url=https://tesla.com"
    return {
        "ok": True,
        "profile": profile,
        "status": "instructions",
        "revoke_url": revoke_url,
        "methods": [
            {"name": "vehicle_touchscreen", "steps": "Controls > Locks > remove the virtual key > scan key card", "speed": "immediate"},
            {"name": "tesla_app", "steps": "Profile > Security & Privacy > Third-Party Apps > Remove", "speed": "up to 2 hours"},
            {"name": "tesla_account_web", "steps": "accounts.tesla.com > Security > Third Party Apps > Manage > Remove", "speed": "up to 2 hours"},
        ],
    }


def handle_key_deploy(args: dict[str, Any]) -> dict[str, Any]:
    _require_confirm(args, "key_deploy")
    profile = _profile(args)
    cfg = config.load_config(profile)
    _, public_path = _public_key_paths(profile)
    if not public_path or not public_path.exists():
        raise client.TeslaAPIError("No public key found. Run tescmd_key_generate first.")

    requested_method = args.get("method") or "local"
    if requested_method != "local":
        raise client.TeslaAPIError("Manual HTTPS hosting only: use method='local', then serve the generated .well-known public-key file from your own domain. Tailscale, GitHub Pages, and MCP/server hosting integrations are intentionally not included in this plugin.")

    deploy_root = config.get_plugin_home() / "hosting" / profile
    deploy_file = deploy_root / WELL_KNOWN_PATH
    deploy_file.parent.mkdir(parents=True, exist_ok=True)
    deploy_file.write_bytes(public_path.read_bytes())
    try:
        deploy_file.chmod(0o644)
    except OSError:
        pass
    (deploy_root / "index.html").write_text("<html><body><p>Tesla Fleet API public key host.</p></body></html>\n")
    return {
        "ok": True,
        "profile": profile,
        "status": "prepared",
        "method": "local",
        "deploy_root": str(deploy_root),
        "public_key_file": str(deploy_file),
        "expected_public_key_url": f"https://{cfg.domain}/{WELL_KNOWN_PATH}" if cfg.domain else None,
        "message": "Upload or serve deploy_root at your HTTPS domain root so the .well-known key path is publicly reachable. This plugin does not run a hosting service.",
    }

def handle_vehicle_list(args: dict[str, Any]) -> dict[str, Any]:
    fleet_client = _fleet_client(args)
    return {"ok": True, "profile": fleet_client.profile, "region": fleet_client.region, "vehicles": fleet_client.list_vehicles()}


def handle_vehicle_get(args: dict[str, Any]) -> dict[str, Any]:
    fleet_client = _fleet_client(args)
    vin = _resolve_vin(args, fleet_client.profile)
    return _result_payload(fleet_client=fleet_client, vin=vin, result=fleet_client.vehicle(vin), result_key="vehicle")


def _cached_vehicle_status(fleet_client: client.TeslaFleetClient, vin: str, *, endpoints: Any, no_cache: bool = False) -> tuple[Any, dict[str, Any]]:
    vehicle_cache_id = hashlib.sha256(f"{fleet_client.profile}:{fleet_client.region}:{vin}".encode("utf-8")).hexdigest()
    cache_key = config.make_cache_key({
        "kind": "vehicle_status",
        "region": fleet_client.region,
        "vehicle_hash": vehicle_cache_id,
        "endpoints": endpoints or [],
    })
    if not no_cache:
        entry = config.load_cache_entry(fleet_client.profile, cache_key)
        if entry is not None:
            return entry.value, {"enabled": True, "hit": True, "bypassed": False, "expires_at": entry.expires_at}
    data = fleet_client.vehicle_status(vin, endpoints=endpoints)
    if no_cache:
        return data, {"enabled": True, "hit": False, "bypassed": True, "expires_at": None}
    entry = config.save_cache_entry(fleet_client.profile, cache_key, data)
    return data, {"enabled": True, "hit": False, "bypassed": False, "expires_at": entry.expires_at}


def handle_vehicle_status(args: dict[str, Any]) -> dict[str, Any]:
    fleet_client = _fleet_client(args)
    vin = _resolve_vin(args, fleet_client.profile)
    if args.get("wake"):
        _require_confirm(args, "wake vehicle before read")
        fleet_client.wake_vehicle(vin)
    data, cache_meta = _cached_vehicle_status(fleet_client, vin, endpoints=args.get("endpoints"), no_cache=bool(args.get("no_cache", False) or args.get("wake")))
    return {"ok": True, "profile": fleet_client.profile, "region": fleet_client.region, "vin": vin, "data": data, "units": args.get("units"), "cache_bypassed": cache_meta["bypassed"], "cache": cache_meta}


def handle_vehicle_info(args: dict[str, Any]) -> dict[str, Any]:
    args = dict(args)
    args.pop("endpoints", None)
    return handle_vehicle_status(args)


def _handle_vehicle_data_section(args: dict[str, Any], endpoint: str, *, result_key: str | None = None, aliases: tuple[str, ...] = ()) -> dict[str, Any]:
    args = dict(args)
    args["endpoints"] = [endpoint]
    payload = handle_vehicle_status(args)
    if result_key:
        data = payload.get("data")
        section = None
        if isinstance(data, dict):
            for key in (endpoint, *aliases):
                if key in data:
                    section = data.get(key)
                    break
        payload[result_key] = section
    return payload


def handle_vehicle_location(args: dict[str, Any]) -> dict[str, Any]:
    return _handle_vehicle_data_section(args, "location_data", result_key="location", aliases=("drive_state",))


def handle_vehicle_drive_status(args: dict[str, Any]) -> dict[str, Any]:
    return _handle_vehicle_data_section(args, "drive_state", result_key="drive_state", aliases=("location_data",))


def handle_vehicle_closures_status(args: dict[str, Any]) -> dict[str, Any]:
    return _handle_vehicle_data_section(args, "closures_state", result_key="closures")


def handle_vehicle_config_status(args: dict[str, Any]) -> dict[str, Any]:
    return _handle_vehicle_data_section(args, "vehicle_config", result_key="vehicle_config")


def handle_vehicle_gui_settings(args: dict[str, Any]) -> dict[str, Any]:
    return _handle_vehicle_data_section(args, "gui_settings", result_key="gui_settings")


def handle_vehicle_charge_schedule_status(args: dict[str, Any]) -> dict[str, Any]:
    return _handle_vehicle_data_section(args, "charge_schedule_data", result_key="charge_schedule")


def handle_vehicle_preconditioning_schedule_status(args: dict[str, Any]) -> dict[str, Any]:
    return _handle_vehicle_data_section(args, "preconditioning_schedule_data", result_key="preconditioning_schedule")


def handle_vehicle_wake(args: dict[str, Any]) -> dict[str, Any]:
    _require_confirm(args, "vehicle_wake")
    fleet_client = _fleet_client(args)
    vin = _resolve_vin(args, fleet_client.profile)
    return _result_payload(fleet_client=fleet_client, vin=vin, result=fleet_client.wake_vehicle(vin), result_key="response")


def handle_vehicle_mobile_access(args: dict[str, Any]) -> dict[str, Any]:
    fleet_client = _fleet_client(args)
    vin = _resolve_vin(args, fleet_client.profile)
    return _result_payload(fleet_client=fleet_client, vin=vin, result=fleet_client.mobile_enabled(vin), result_key="mobile_access_enabled")


def handle_vehicle_nearby_chargers(args: dict[str, Any]) -> dict[str, Any]:
    fleet_client = _fleet_client(args)
    vin = _resolve_vin(args, fleet_client.profile)
    return _result_payload(fleet_client=fleet_client, vin=vin, result=fleet_client.nearby_charging_sites(vin), result_key="sites")


def handle_vehicle_alerts(args: dict[str, Any]) -> dict[str, Any]:
    fleet_client = _fleet_client(args)
    vin = _resolve_vin(args, fleet_client.profile)
    return _result_payload(fleet_client=fleet_client, vin=vin, result=fleet_client.recent_alerts(vin), result_key="alerts")


def handle_vehicle_drivers(args: dict[str, Any]) -> dict[str, Any]:
    fleet_client = _fleet_client(args)
    vin = _resolve_vin(args, fleet_client.profile)
    return _result_payload(fleet_client=fleet_client, vin=vin, result=fleet_client.drivers(vin), result_key="drivers")


def handle_vehicle_release_notes(args: dict[str, Any]) -> dict[str, Any]:
    fleet_client = _fleet_client(args)
    vin = _resolve_vin(args, fleet_client.profile)
    return _result_payload(fleet_client=fleet_client, vin=vin, result=fleet_client.release_notes(vin), result_key="release_notes")


def handle_vehicle_service(args: dict[str, Any]) -> dict[str, Any]:
    fleet_client = _fleet_client(args)
    vin = _resolve_vin(args, fleet_client.profile)
    return _result_payload(fleet_client=fleet_client, vin=vin, result=fleet_client.service_data(vin), result_key="service")


def handle_vehicle_specs(args: dict[str, Any]) -> dict[str, Any]:
    fleet_client = _fleet_client(args)
    vin = _resolve_vin(args, fleet_client.profile)
    return _result_payload(fleet_client=fleet_client, vin=vin, result=fleet_client.specs(vin), result_key="specs")


def handle_vehicle_subscriptions(args: dict[str, Any]) -> dict[str, Any]:
    fleet_client = _fleet_client(args)
    vin = _resolve_full_vin(args, fleet_client, operation="vehicle_subscriptions")
    return _result_payload(fleet_client=fleet_client, vin=vin, result=fleet_client.subscriptions(vin), result_key="subscriptions")


def handle_vehicle_upgrades(args: dict[str, Any]) -> dict[str, Any]:
    fleet_client = _fleet_client(args)
    vin = _resolve_full_vin(args, fleet_client, operation="vehicle_upgrades")
    return _result_payload(fleet_client=fleet_client, vin=vin, result=fleet_client.upgrades(vin), result_key="upgrades")


def handle_vehicle_options(args: dict[str, Any]) -> dict[str, Any]:
    fleet_client = _fleet_client(args)
    vin = _resolve_full_vin(args, fleet_client, operation="vehicle_options")
    return _result_payload(fleet_client=fleet_client, vin=vin, result=fleet_client.options(vin), result_key="options")


def handle_vehicle_warranty(args: dict[str, Any]) -> dict[str, Any]:
    fleet_client = _fleet_client(args)
    vin = _resolve_full_vin(args, fleet_client, operation="vehicle_warranty")
    return _result_payload(fleet_client=fleet_client, vin=vin, result=fleet_client.warranty_details(vin=vin), result_key="warranty")


def handle_vehicle_pricing(args: dict[str, Any]) -> dict[str, Any]:
    fleet_client = _fleet_client(args)
    request_payload = args.get("request")
    if isinstance(request_payload, str):
        request_payload = json.loads(request_payload)
    if not isinstance(request_payload, dict):
        raise client.TeslaAPIError("request must be a JSON object.")
    return _result_payload(fleet_client=fleet_client, result=fleet_client.vehicle_pricing(request_payload), result_key="pricing")


def handle_vehicle_enterprise_roles(args: dict[str, Any]) -> dict[str, Any]:
    fleet_client = _fleet_client(args)
    vin = _resolve_vin(args, fleet_client.profile)
    return _result_payload(fleet_client=fleet_client, vin=vin, result=fleet_client.enterprise_roles(vin), result_key="roles")


def handle_vehicle_enterprise_payer(args: dict[str, Any]) -> dict[str, Any]:
    _require_confirm(args, "vehicle_enterprise_payer")
    fleet_client = _fleet_client(args)
    vin = _resolve_vin(args, fleet_client.profile)
    payer = args.get("payer")
    if isinstance(payer, str):
        payer = json.loads(payer)
    if not isinstance(payer, dict):
        raise client.TeslaAPIError("payer must be a JSON object.")
    return _result_payload(fleet_client=fleet_client, vin=vin, result=fleet_client.enterprise_payer(vin, payer), result_key="response")


def handle_vehicle_fleet_status(args: dict[str, Any]) -> dict[str, Any]:
    fleet_client = _fleet_client(args)
    vins = _resolve_full_vins(args, fleet_client, operation="vehicle_fleet_status")
    return _result_payload(fleet_client=fleet_client, result=fleet_client.fleet_status(vins=vins), result_key="fleet_status")


def handle_vehicle_telemetry_config(args: dict[str, Any]) -> dict[str, Any]:
    fleet_client = _fleet_client(args)
    vin = _resolve_vin(args, fleet_client.profile)
    return _result_payload(fleet_client=fleet_client, vin=vin, result=fleet_client.fleet_telemetry_config(vin), result_key="telemetry_config")


def handle_vehicle_telemetry_create(args: dict[str, Any]) -> dict[str, Any]:
    _require_confirm(args, "vehicle_telemetry_create")
    fleet_client = _fleet_client(args)
    config_payload = args.get("config")
    if isinstance(config_payload, str):
        config_payload = json.loads(config_payload)
    if not isinstance(config_payload, dict):
        raise client.TeslaAPIError("config must be a JSON object.")
    return _result_payload(fleet_client=fleet_client, result=fleet_client.fleet_telemetry_config_create(config_payload=config_payload), result_key="response")


def handle_vehicle_telemetry_create_jws(args: dict[str, Any]) -> dict[str, Any]:
    _require_confirm(args, "vehicle_telemetry_create_jws")
    fleet_client = _fleet_client(args)
    token = args.get("token")
    if not isinstance(token, str) or not token:
        raise client.TeslaAPIError("token is required.")
    return _result_payload(fleet_client=fleet_client, result=fleet_client.fleet_telemetry_config_jws(token), result_key="response")


def handle_vehicle_telemetry_delete(args: dict[str, Any]) -> dict[str, Any]:
    if not args.get("confirm"):
        raise client.TeslaAPIError("confirm=true is required to delete fleet telemetry configuration.")
    fleet_client = _fleet_client(args)
    vin = _resolve_vin(args, fleet_client.profile)
    return _result_payload(fleet_client=fleet_client, vin=vin, result=fleet_client.fleet_telemetry_config_delete(vin), result_key="response")


def handle_vehicle_telemetry_errors(args: dict[str, Any]) -> dict[str, Any]:
    fleet_client = _fleet_client(args)
    vin = _resolve_vin(args, fleet_client.profile)
    return _result_payload(fleet_client=fleet_client, vin=vin, result=fleet_client.fleet_telemetry_errors(vin), result_key="errors")


def handle_charge_status(args: dict[str, Any]) -> dict[str, Any]:
    return _handle_vehicle_data_section(args, "charge_state", result_key="charge_state")


def handle_climate_status(args: dict[str, Any]) -> dict[str, Any]:
    return _handle_vehicle_data_section(args, "climate_state", result_key="climate_state")


def handle_security_status(args: dict[str, Any]) -> dict[str, Any]:
    payload = _handle_vehicle_data_section(args, "vehicle_state", result_key="security")
    return payload


def handle_software_status(args: dict[str, Any]) -> dict[str, Any]:
    args = dict(args)
    args["endpoints"] = ["vehicle_state"]
    payload = handle_vehicle_status(args)
    vehicle_state = payload["data"].get("vehicle_state") if isinstance(payload.get("data"), dict) else None
    payload["software"] = {
        "car_version": vehicle_state.get("car_version") if isinstance(vehicle_state, dict) else None,
        "software_update": vehicle_state.get("software_update") if isinstance(vehicle_state, dict) else None,
    }
    return payload


def handle_user_me(args: dict[str, Any]) -> dict[str, Any]:
    fleet_client = _fleet_client(args)
    return _result_payload(fleet_client=fleet_client, result=fleet_client.user_me(), result_key="user")


def handle_user_region(args: dict[str, Any]) -> dict[str, Any]:
    fleet_client = _fleet_client(args)
    return _result_payload(fleet_client=fleet_client, result=fleet_client.user_region(), result_key="region_info")


def handle_user_orders(args: dict[str, Any]) -> dict[str, Any]:
    fleet_client = _fleet_client(args)
    return _result_payload(fleet_client=fleet_client, result=fleet_client.user_orders(), result_key="orders")


def handle_user_features(args: dict[str, Any]) -> dict[str, Any]:
    fleet_client = _fleet_client(args)
    return _result_payload(fleet_client=fleet_client, result=fleet_client.user_feature_config(), result_key="features")


def handle_billing_history(args: dict[str, Any]) -> dict[str, Any]:
    fleet_client = _fleet_client(args)
    result = fleet_client.charging_history(vin=args.get("vin_filter") or args.get("vin"), start_time=args.get("start_time"), end_time=args.get("end_time"), page_no=args.get("page"), page_size=args.get("page_size"))
    return _result_payload(fleet_client=fleet_client, result=result, result_key="history")


def handle_billing_sessions(args: dict[str, Any]) -> dict[str, Any]:
    fleet_client = _fleet_client(args)
    result = fleet_client.charging_sessions(vin=args.get("vin_filter") or args.get("vin"), date_from=args.get("date_from"), date_to=args.get("date_to"), limit=args.get("limit"), offset=args.get("offset"))
    return _result_payload(fleet_client=fleet_client, result=result, result_key="sessions")


def handle_billing_invoice(args: dict[str, Any]) -> dict[str, Any]:
    fleet_client = _fleet_client(args)
    invoice_id = args.get("invoice_id")
    if not invoice_id:
        raise client.TeslaAPIError("invoice_id is required.")
    result = fleet_client.charging_invoice(str(invoice_id))
    payload = _result_payload(fleet_client=fleet_client, result=result, result_key="invoice")
    if args.get("output_path") and isinstance(result, str):
        _require_confirm(args, "billing_invoice_output")
        target = _safe_export_path(str(args["output_path"]), profile=fleet_client.profile)
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as handle:
            handle.write(result)
        payload["saved_to"] = str(target)
    return payload


def handle_energy_list(args: dict[str, Any]) -> dict[str, Any]:
    fleet_client = _fleet_client(args)
    return _result_payload(fleet_client=fleet_client, result=fleet_client.energy_products(), result_key="products")


def handle_energy_live(args: dict[str, Any]) -> dict[str, Any]:
    fleet_client = _fleet_client(args)
    site_id = _resolve_site_id(args)
    return _result_payload(fleet_client=fleet_client, result=fleet_client.energy_live_status(site_id), result_key="live_status", extra={"site_id": site_id})


def handle_energy_status(args: dict[str, Any]) -> dict[str, Any]:
    fleet_client = _fleet_client(args)
    site_id = _resolve_site_id(args)
    return _result_payload(fleet_client=fleet_client, result=fleet_client.energy_site_info(site_id), result_key="site", extra={"site_id": site_id})


def handle_energy_backup(args: dict[str, Any]) -> dict[str, Any]:
    _require_confirm(args, "energy_backup")
    fleet_client = _fleet_client(args)
    site_id = _resolve_site_id(args)
    return _result_payload(fleet_client=fleet_client, result=fleet_client.energy_backup(site_id, _validate_percent("percent", args["percent"])), result_key="response", extra={"site_id": site_id})


def handle_energy_mode(args: dict[str, Any]) -> dict[str, Any]:
    _require_confirm(args, "energy_mode")
    fleet_client = _fleet_client(args)
    site_id = _resolve_site_id(args)
    return _result_payload(fleet_client=fleet_client, result=fleet_client.energy_operation_mode(site_id, str(args["mode"])), result_key="response", extra={"site_id": site_id})


def handle_energy_storm(args: dict[str, Any]) -> dict[str, Any]:
    _require_confirm(args, "energy_storm")
    fleet_client = _fleet_client(args)
    site_id = _resolve_site_id(args)
    return _result_payload(fleet_client=fleet_client, result=fleet_client.energy_storm_mode(site_id, bool(args["enabled"])), result_key="response", extra={"site_id": site_id})


def handle_energy_tou(args: dict[str, Any]) -> dict[str, Any]:
    _require_confirm(args, "energy_tou")
    fleet_client = _fleet_client(args)
    site_id = _resolve_site_id(args)
    settings = args.get("settings")
    if isinstance(settings, str):
        settings = json.loads(settings)
    if not isinstance(settings, dict):
        raise client.TeslaAPIError("settings must be a JSON object.")
    return _result_payload(fleet_client=fleet_client, result=fleet_client.energy_time_of_use(site_id, settings), result_key="response", extra={"site_id": site_id})


def handle_energy_calendar(args: dict[str, Any]) -> dict[str, Any]:
    fleet_client = _fleet_client(args)
    site_id = _resolve_site_id(args)
    result = fleet_client.energy_calendar_history(site_id, kind=args.get("kind") or "energy", period=args.get("period") or "day", start_date=args.get("start_date"), end_date=args.get("end_date"), time_zone=args.get("time_zone"))
    return _result_payload(fleet_client=fleet_client, result=result, result_key="history", extra={"site_id": site_id})


def handle_energy_history(args: dict[str, Any]) -> dict[str, Any]:
    args = dict(args)
    args.setdefault("kind", "charge")
    return handle_energy_telemetry(args)


def handle_energy_off_grid(args: dict[str, Any]) -> dict[str, Any]:
    _require_confirm(args, "energy_off_grid")
    fleet_client = _fleet_client(args)
    site_id = _resolve_site_id(args)
    return _result_payload(fleet_client=fleet_client, result=fleet_client.energy_off_grid_vehicle_charging_reserve(site_id, _validate_percent("reserve", args["reserve"])), result_key="response", extra={"site_id": site_id})


def handle_energy_grid_config(args: dict[str, Any]) -> dict[str, Any]:
    _require_confirm(args, "energy_grid_config")
    fleet_client = _fleet_client(args)
    site_id = _resolve_site_id(args)
    config_payload = args.get("config")
    if isinstance(config_payload, str):
        config_payload = json.loads(config_payload)
    if not isinstance(config_payload, dict):
        raise client.TeslaAPIError("config must be a JSON object.")
    return _result_payload(fleet_client=fleet_client, result=fleet_client.energy_grid_import_export(site_id, config_payload), result_key="response", extra={"site_id": site_id})


def handle_energy_telemetry(args: dict[str, Any]) -> dict[str, Any]:
    fleet_client = _fleet_client(args)
    site_id = _resolve_site_id(args)
    result = fleet_client.energy_telemetry_history(site_id, kind=args.get("kind") or "charge", start_date=args.get("start_date"), end_date=args.get("end_date"), time_zone=args.get("time_zone"))
    return _result_payload(fleet_client=fleet_client, result=result, result_key="telemetry", extra={"site_id": site_id})


def handle_partner_public_key(args: dict[str, Any]) -> dict[str, Any]:
    fleet_client = _fleet_client(args)
    domain = args.get("domain") or fleet_client.cfg.domain
    if not domain:
        raise client.TeslaAPIError("domain is required for partner public-key lookup.")
    return _result_payload(fleet_client=fleet_client, result=fleet_client.partner_public_key(str(domain)), result_key="public_key")


def handle_partner_telemetry_error_vins(args: dict[str, Any]) -> dict[str, Any]:
    fleet_client = _fleet_client(args)
    return _result_payload(fleet_client=fleet_client, result=fleet_client.partner_fleet_telemetry_error_vins(), result_key="vins")


def handle_partner_telemetry_errors(args: dict[str, Any]) -> dict[str, Any]:
    fleet_client = _fleet_client(args)
    return _result_payload(fleet_client=fleet_client, result=fleet_client.partner_fleet_telemetry_errors(), result_key="errors")


def handle_sharing_add_driver(args: dict[str, Any]) -> dict[str, Any]:
    _require_confirm(args, "sharing_add_driver")
    fleet_client = _fleet_client(args)
    vin = _resolve_vin(args, fleet_client.profile)
    email = args.get("email")
    if not email:
        raise client.TeslaAPIError("email is required.")
    return _result_payload(fleet_client=fleet_client, vin=vin, result=fleet_client.add_driver(vin, str(email)), result_key="driver")


def handle_sharing_remove_driver(args: dict[str, Any]) -> dict[str, Any]:
    _require_confirm(args, "sharing_remove_driver")
    fleet_client = _fleet_client(args)
    vin = _resolve_vin(args, fleet_client.profile)
    share_user_id = args.get("share_user_id")
    if share_user_id is None:
        raise client.TeslaAPIError("share_user_id is required.")
    return _result_payload(fleet_client=fleet_client, vin=vin, result=fleet_client.remove_driver(vin, int(share_user_id)), result_key="response")


def handle_sharing_create_invite(args: dict[str, Any]) -> dict[str, Any]:
    _require_confirm(args, "sharing_create_invite")
    fleet_client = _fleet_client(args)
    vin = _resolve_vin(args, fleet_client.profile)
    return _result_payload(fleet_client=fleet_client, vin=vin, result=fleet_client.create_invite(vin), result_key="invite")


def handle_sharing_list_invites(args: dict[str, Any]) -> dict[str, Any]:
    fleet_client = _fleet_client(args)
    vin = _resolve_vin(args, fleet_client.profile)
    return _result_payload(fleet_client=fleet_client, vin=vin, result=fleet_client.list_invites(vin), result_key="invites")


def handle_sharing_redeem_invite(args: dict[str, Any]) -> dict[str, Any]:
    _require_confirm(args, "sharing_redeem_invite")
    fleet_client = _fleet_client(args)
    code = args.get("code")
    if not code:
        raise client.TeslaAPIError("code is required.")
    return _result_payload(fleet_client=fleet_client, result=fleet_client.redeem_invite(str(code)), result_key="invite")


def handle_sharing_revoke_invite(args: dict[str, Any]) -> dict[str, Any]:
    _require_confirm(args, "sharing_revoke_invite")
    fleet_client = _fleet_client(args)
    vin = _resolve_vin(args, fleet_client.profile)
    invite_id = args.get("invite_id")
    if not invite_id:
        raise client.TeslaAPIError("invite_id is required.")
    return _result_payload(fleet_client=fleet_client, vin=vin, result=fleet_client.revoke_invite(vin, str(invite_id)), result_key="response")


def _validate_raw_path(path: Any) -> str:
    if not path:
        raise client.TeslaAPIError("path is required.")
    path_text = str(path)
    if not path_text.startswith("/api/"):
        raise client.TeslaAPIError("Raw Fleet API paths must be relative paths starting with /api/.")
    if "://" in path_text or ".." in path_text or "\x00" in path_text:
        raise client.TeslaAPIError("Raw Fleet API paths must not be absolute URLs, contain NUL bytes, or contain parent-directory traversal.")
    return path_text


def handle_raw_get(args: dict[str, Any]) -> dict[str, Any]:
    _require_confirm(args, "raw_get")
    fleet_client = _fleet_client(args)
    path = _validate_raw_path(args.get("path"))
    params = args.get("params")
    if isinstance(params, str):
        params = json.loads(params)
    if params is not None and not isinstance(params, dict):
        raise client.TeslaAPIError("params must be a JSON object.")
    return _result_payload(fleet_client=fleet_client, result=fleet_client.raw_get(path, params=params), result_key="response", extra={"path": path, "method": "GET"})


def handle_raw_post(args: dict[str, Any]) -> dict[str, Any]:
    _require_confirm(args, "raw_post")
    fleet_client = _fleet_client(args)
    path = _validate_raw_path(args.get("path"))
    body = args.get("body")
    if isinstance(body, str):
        body = json.loads(body)
    if body is not None and not isinstance(body, dict):
        raise client.TeslaAPIError("body must be a JSON object.")
    return _result_payload(fleet_client=fleet_client, result=fleet_client.raw_post(path, body=body), result_key="response", extra={"path": path, "method": "POST"})


def handle_raw_delete(args: dict[str, Any]) -> dict[str, Any]:
    _require_confirm(args, "raw_delete")
    fleet_client = _fleet_client(args)
    path = _validate_raw_path(args.get("path"))
    body = args.get("body")
    if isinstance(body, str):
        body = json.loads(body)
    if body is not None and not isinstance(body, dict):
        raise client.TeslaAPIError("body must be a JSON object.")
    return _result_payload(fleet_client=fleet_client, result=fleet_client.raw_delete(path, body=body), result_key="response", extra={"path": path, "method": "DELETE"})


def handle_navigation_place_search(args: dict[str, Any]) -> dict[str, Any]:
    profile = _profile(args)
    cfg = config.load_config(profile)
    if not cfg.google_maps_api_key:
        raise client.TeslaAPIError("google_maps_api_key is not configured. Add google_maps_api_key to the plugin config file, or provide Google Maps Place IDs directly to tescmd_navigation_waypoints.")
    query = str(args.get("query") or "").strip()
    if not query:
        raise client.TeslaAPIError("query is required for Google Places search.")
    try:
        limit = int(args.get("limit") or 5)
    except (TypeError, ValueError) as exc:
        raise client.TeslaAPIError("limit must be an integer from 1 through 10.") from exc
    if not 1 <= limit <= 10:
        raise client.TeslaAPIError("limit must be from 1 through 10.")
    try:
        response = httpx.post(
            "https://places.googleapis.com/v1/places:searchText",
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": cfg.google_maps_api_key,
                "X-Goog-FieldMask": "places.id,places.displayName,places.formattedAddress,places.location",
            },
            json={"textQuery": query, "maxResultCount": limit},
            timeout=20,
        )
    except httpx.HTTPError as exc:
        raise client.NetworkError(f"Google Places request failed: {exc}") from exc
    try:
        payload = response.json()
    except ValueError as exc:
        raise client.TeslaAPIError(f"Google Places returned non-JSON response with HTTP {response.status_code}.") from exc
    if response.status_code >= 400:
        message = payload.get("error", {}).get("message") if isinstance(payload, dict) else None
        raise client.TeslaAPIError(f"Google Places search failed with HTTP {response.status_code}: {message or payload}")
    places = payload.get("places", []) if isinstance(payload, dict) else []
    candidates = []
    for place in places[:limit]:
        if not isinstance(place, dict):
            continue
        candidates.append(
            {
                "place_id": place.get("id"),
                "name": (place.get("displayName") or {}).get("text") if isinstance(place.get("displayName"), dict) else None,
                "formatted_address": place.get("formattedAddress"),
                "location": place.get("location"),
            }
        )
    return {
        "ok": True,
        "profile": profile,
        "query": query,
        "candidates": candidates,
        "next_tool": "tescmd_navigation_waypoints",
        "next_args_hint": {"place_ids": [item["place_id"] for item in candidates if item.get("place_id")]},
        "note": "This only resolves Google Place IDs. Sending the route to the vehicle still requires an explicit tescmd_navigation_waypoints call with confirm=true.",
    }


def handle_help(args: dict[str, Any]) -> dict[str, Any]:
    profile = _profile(args)
    cfg = config.load_config(profile)
    auth_state = config.load_auth_state(profile)
    bootstrap = _bootstrap_status(profile=profile, cfg=cfg, auth_state=auth_state)
    return {
        "ok": True,
        "profile": profile,
        "bootstrap": bootstrap,
        "routing": {
            "overall_status_or_recovery": "tescmd_status",
            "first_time_setup": "Edit plugin config.json per README -> tescmd_auth_login -> tescmd_auth_complete -> tescmd_vehicle_list -> update config.json default_vin",
            "vehicle_list": "tescmd_vehicle_list",
            "where_is_my_car": "tescmd_vehicle_location",
            "battery_or_charge_status": "tescmd_charge_status",
            "start_or_stop_charging": "tescmd_charge_start / tescmd_charge_stop with confirm=true",
            "wake_vehicle": "tescmd_vehicle_wake with confirm=true",
            "single_destination_navigation": "tescmd_navigation_send(destination, confirm=true)",
            "single_gps_navigation": "tescmd_navigation_gps(lat, lon, order?, confirm=true)",
            "multi_stop_place_id_navigation": "tescmd_navigation_waypoints(place_ids=[...], confirm=true)",
            "resolve_addresses_to_place_ids": "tescmd_navigation_place_search(query) requires google_maps_api_key",
            "nearby_superchargers": "tescmd_vehicle_nearby_chargers then tescmd_navigation_supercharger(order, confirm=true)",
            "signed_command_readiness": "tescmd_status bootstrap.ready_for_signed_commands and bootstrap.missing_for_signed_commands",
        },
        "safety": [
            "Do not set confirm=true unless the user explicitly requested the side effect.",
            "Do not set wake=true on read tools unless the user explicitly asked to wake/check a sleeping vehicle; wake requires confirm=true.",
            "Do not invent Google Place IDs. Use tescmd_navigation_place_search with a configured Google Maps API key, ask the user, or use single-destination navigation.",
        ],
    }


def handle_cache_status(args: dict[str, Any]) -> dict[str, Any]:
    profile = _profile(args)
    status = config.cache_status(profile)
    return {"ok": True, "profile": profile, **status, "message": "Plugin-native response cache for selected read-only Fleet API calls."}


def handle_cache_clear(args: dict[str, Any]) -> dict[str, Any]:
    _require_confirm(args, "cache_clear")
    profile = _profile(args)
    cleared = config.clear_cache(profile)
    return {"ok": True, "profile": profile, "enabled": True, "cleared": cleared}


def handle_plugin_mode_info(args: dict[str, Any], *, mode: str) -> dict[str, Any]:
    profile = _profile(args)
    return {
        "ok": True,
        "profile": profile,
        "mode": mode,
        "plugin_native": True,
        "message": {
            "serve": "The Hermes plugin already exposes Tesla capabilities directly as tools, so there is no separate plugin-side HTTP/MCP daemon to start.",
            "openclaw_bridge": "OpenClaw bridge mode is a standalone CLI/server workflow and is not run inside the native Hermes plugin. Use Hermes tools directly or wire telemetry externally.",
            "vehicle_telemetry_stream": "CLI telemetry streaming is a long-running TUI/server workflow. In plugin mode, use telemetry config/error tools and an external telemetry receiver instead of launching a dashboard process from a tool call.",
        }[mode],
    }


OPERATIONS = {
    "status": handle_status,
    "auth_login": handle_auth_login,
    "auth_complete": handle_auth_complete,
    "auth_status": handle_auth_status,
    "auth_refresh": handle_auth_refresh,
    "auth_import": handle_auth_import,
    "auth_export": handle_auth_export,
    "auth_register": handle_auth_register,
    "auth_logout": handle_auth_logout,
    "key_generate": handle_key_generate,
    "key_show": handle_key_show,
    "key_validate": handle_key_validate,
    "key_enroll": handle_key_enroll,
    "key_unenroll": handle_key_unenroll,
    "key_deploy": handle_key_deploy,
    "vehicle_list": handle_vehicle_list,
    "vehicle_get": handle_vehicle_get,
    "vehicle_status": handle_vehicle_status,
    "vehicle_info": handle_vehicle_info,
    "vehicle_location": handle_vehicle_location,
    "vehicle_drive_status": handle_vehicle_drive_status,
    "vehicle_closures_status": handle_vehicle_closures_status,
    "vehicle_config_status": handle_vehicle_config_status,
    "vehicle_gui_settings": handle_vehicle_gui_settings,
    "vehicle_charge_schedule_status": handle_vehicle_charge_schedule_status,
    "vehicle_preconditioning_schedule_status": handle_vehicle_preconditioning_schedule_status,
    "vehicle_wake": handle_vehicle_wake,
    "vehicle_mobile_access": handle_vehicle_mobile_access,
    "vehicle_nearby_chargers": handle_vehicle_nearby_chargers,
    "vehicle_alerts": handle_vehicle_alerts,
    "vehicle_drivers": handle_vehicle_drivers,
    "vehicle_release_notes": handle_vehicle_release_notes,
    "vehicle_service": handle_vehicle_service,
    "vehicle_specs": handle_vehicle_specs,
    "vehicle_subscriptions": handle_vehicle_subscriptions,
    "vehicle_upgrades": handle_vehicle_upgrades,
    "vehicle_options": handle_vehicle_options,
    "vehicle_warranty": handle_vehicle_warranty,
    "vehicle_pricing": handle_vehicle_pricing,
    "vehicle_enterprise_roles": handle_vehicle_enterprise_roles,
    "vehicle_enterprise_payer": handle_vehicle_enterprise_payer,
    "vehicle_fleet_status": handle_vehicle_fleet_status,
    "vehicle_telemetry_config": handle_vehicle_telemetry_config,
    "vehicle_telemetry_create": handle_vehicle_telemetry_create,
    "vehicle_telemetry_create_jws": handle_vehicle_telemetry_create_jws,
    "vehicle_telemetry_delete": handle_vehicle_telemetry_delete,
    "vehicle_telemetry_errors": handle_vehicle_telemetry_errors,
    "charge_status": handle_charge_status,
    "climate_status": handle_climate_status,
    "security_status": handle_security_status,
    "software_status": handle_software_status,
    "user_me": handle_user_me,
    "user_region": handle_user_region,
    "user_orders": handle_user_orders,
    "user_features": handle_user_features,
    "billing_history": handle_billing_history,
    "billing_sessions": handle_billing_sessions,
    "billing_invoice": handle_billing_invoice,
    "energy_list": handle_energy_list,
    "energy_live": handle_energy_live,
    "energy_status": handle_energy_status,
    "energy_backup": handle_energy_backup,
    "energy_mode": handle_energy_mode,
    "energy_storm": handle_energy_storm,
    "energy_tou": handle_energy_tou,
    "energy_calendar": handle_energy_calendar,
    "energy_history": handle_energy_history,
    "energy_off_grid": handle_energy_off_grid,
    "energy_grid_config": handle_energy_grid_config,
    "energy_telemetry": handle_energy_telemetry,
    "partner_public_key": handle_partner_public_key,
    "partner_telemetry_error_vins": handle_partner_telemetry_error_vins,
    "partner_telemetry_errors": handle_partner_telemetry_errors,
    "sharing_add_driver": handle_sharing_add_driver,
    "sharing_remove_driver": handle_sharing_remove_driver,
    "sharing_create_invite": handle_sharing_create_invite,
    "sharing_list_invites": handle_sharing_list_invites,
    "sharing_redeem_invite": handle_sharing_redeem_invite,
    "sharing_revoke_invite": handle_sharing_revoke_invite,
    "raw_get": handle_raw_get,
    "raw_post": handle_raw_post,
    "raw_delete": handle_raw_delete,
    "navigation_place_search": handle_navigation_place_search,
    "help": handle_help,
    "cache_status": handle_cache_status,
    "cache_clear": handle_cache_clear,
    "serve": lambda args: handle_plugin_mode_info(args, mode="serve"),
    "openclaw_bridge": lambda args: handle_plugin_mode_info(args, mode="openclaw_bridge"),
    "vehicle_telemetry_stream": lambda args: handle_plugin_mode_info(args, mode="vehicle_telemetry_stream"),
}
