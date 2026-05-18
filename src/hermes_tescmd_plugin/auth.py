from __future__ import annotations

import base64
import hashlib
import json
import contextlib
import os
import secrets
from dataclasses import asdict
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from . import client, config

AUTHORIZE_URL = "https://auth.tesla.com/oauth2/v3/authorize"
PENDING_AUTH_TTL_SECONDS = 10 * 60


def _urlsafe_b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def generate_code_verifier() -> str:
    return _urlsafe_b64(secrets.token_bytes(48))


def generate_code_challenge(code_verifier: str) -> str:
    return _urlsafe_b64(hashlib.sha256(code_verifier.encode()).digest())


def start_login(profile: str, *, redirect_port: int | None = None, scopes: list[str] | None = None) -> dict[str, Any]:
    cfg = config.load_config(profile)
    if not cfg.client_id:
        raise client.TeslaAPIError("Edit the plugin config file first so the plugin knows your Tesla client ID. See the README configuration checklist.")

    redirect_port = redirect_port or cfg.redirect_port
    requested_scopes = scopes or cfg.scopes or list(config.DEFAULT_SCOPES)
    active_scopes = [scope for scope in requested_scopes if scope not in config.PARTNER_ONLY_SCOPES]
    partner_only_scopes = [scope for scope in requested_scopes if scope in config.PARTNER_ONLY_SCOPES]
    state = secrets.token_urlsafe(24)
    code_verifier = generate_code_verifier()
    redirect_uri = config.resolve_oauth_redirect_uri(cfg)
    if not redirect_uri:
        raise client.TeslaAPIError("Configure a public HTTPS OAuth callback first: set oauth_redirect_uri, or set domain so the plugin can use https://<domain>/callback. Tesla app registration requires a public callback URL.")

    pending = config.PendingAuthState(
        profile=profile,
        state=state,
        code_verifier=code_verifier,
        redirect_port=redirect_port,
        redirect_uri=redirect_uri,
        scopes=list(active_scopes),
    )
    config.save_pending_auth(pending)

    query = {
        "response_type": "code",
        "client_id": cfg.client_id,
        "redirect_uri": redirect_uri,
        "scope": " ".join(active_scopes),
        "state": state,
        "code_challenge": generate_code_challenge(code_verifier),
        "code_challenge_method": "S256",
    }
    return {
        "ok": True,
        "profile": profile,
        "region": cfg.region,
        "redirect_uri": redirect_uri,
        "state": state,
        "auth_url": f"{AUTHORIZE_URL}?{urlencode(query)}",
        "scopes": active_scopes,
        "partner_only_scopes": partner_only_scopes,
    }


def _extract_code_and_state(
    *,
    callback_url: str | None,
    code: str | None,
    state: str | None,
    expected_redirect_uri: str | None = None,
) -> tuple[str, str]:
    if callback_url:
        parsed = urlparse(callback_url)
        if expected_redirect_uri:
            expected = urlparse(expected_redirect_uri)
            if (parsed.scheme, parsed.hostname, parsed.port, parsed.path) != (
                expected.scheme,
                expected.hostname,
                expected.port,
                expected.path,
            ):
                raise client.TeslaAPIError("OAuth callback URL does not match the pending login redirect URI.")
        query = parse_qs(parsed.query)
        code = query.get("code", [None])[0]
        state = query.get("state", [None])[0]
    if not code or not state:
        raise client.TeslaAPIError("Provide either callback_url or both code and state.")
    return code, state


def complete_login(
    profile: str,
    *,
    callback_url: str | None = None,
    code: str | None = None,
    state: str | None = None,
) -> dict[str, Any]:
    pending = config.load_pending_auth(profile)
    if pending is None:
        raise client.TeslaAPIError("No pending Tesla login was found. Run tescmd_auth_login first.")
    if int(__import__("time").time()) - pending.created_at > PENDING_AUTH_TTL_SECONDS:
        config.clear_pending_auth(profile)
        raise client.TeslaAPIError("Pending Tesla login has expired. Run tescmd_auth_login again.")
    code, state = _extract_code_and_state(
        callback_url=callback_url,
        code=code,
        state=state,
        expected_redirect_uri=pending.redirect_uri,
    )
    if state != pending.state:
        raise client.TeslaAPIError("Returned OAuth state does not match the pending login session.")

    cfg = config.load_config(profile)
    auth_state = client.exchange_authorization_code(
        cfg=cfg,
        code=code,
        code_verifier=pending.code_verifier,
        redirect_uri=pending.redirect_uri,
    )
    config.save_auth_state(auth_state)
    config.clear_pending_auth(profile)
    return {
        "ok": True,
        "profile": profile,
        "region": auth_state.region,
        "scopes": auth_state.scopes,
        "expires_at": auth_state.expires_at,
        "authenticated": True,
    }


def refresh_login(profile: str) -> dict[str, Any]:
    cfg = config.load_config(profile)
    state = config.load_auth_state(profile)
    refreshed = client.refresh_access_token(cfg, state)
    config.save_auth_state(refreshed)
    return {
        "ok": True,
        "profile": profile,
        "region": refreshed.region,
        "scopes": refreshed.scopes,
        "expires_at": refreshed.expires_at,
        "authenticated": True,
    }


def auth_status(profile: str) -> dict[str, Any]:
    cfg = config.load_config(profile)
    auth_state = config.load_auth_state(profile)
    pending = config.load_pending_auth(profile)
    granted_scopes = set(auth_state.scopes)
    configured_user_scopes = [scope for scope in cfg.scopes if scope not in config.PARTNER_ONLY_SCOPES]
    configured_partner_scopes = [scope for scope in cfg.scopes if scope in config.PARTNER_ONLY_SCOPES]
    return {
        "ok": True,
        "profile": profile,
        "configured": bool(cfg.client_id),
        "authenticated": auth_state.is_authenticated(),
        "pending_login": pending is not None,
        "region": auth_state.region or cfg.region,
        "domain": cfg.domain,
        "default_vin": cfg.default_vin,
        "scopes": auth_state.scopes or configured_user_scopes,
        "configured_scopes": cfg.scopes,
        "configured_user_scopes": configured_user_scopes,
        "partner_only_scopes": configured_partner_scopes,
        "missing_granted_user_scopes": [scope for scope in configured_user_scopes if granted_scopes and scope not in granted_scopes],
        "expires_at": auth_state.expires_at,
        "vehicle_command_key": {
            "private_key_path": cfg.vehicle_command_key_private_path,
            "public_key_path": cfg.vehicle_command_key_public_path,
        },
    }


def export_auth(profile: str, *, output_path: str | None = None) -> dict[str, Any]:
    auth_state = config.load_auth_state(profile)
    export_dir = config.get_plugin_home() / "exports" / profile
    export_dir.mkdir(parents=True, exist_ok=True)
    try:
        export_dir.chmod(0o700)
    except OSError:
        pass
    path = Path(output_path).expanduser() if output_path else export_dir / "auth.json"
    if not path.is_absolute():
        path = export_dir / path
    path = path.resolve()
    export_root = export_dir.resolve()
    if path != export_root and export_root not in path.parents:
        raise client.TeslaAPIError(f"output_path must stay under the plugin auth export directory: {export_root}")
    if path.exists():
        raise client.TeslaAPIError(f"Refusing to overwrite existing auth export file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(path, flags, 0o600)
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(asdict(auth_state), handle, indent=2, sort_keys=True)
            handle.write("\n")
    except Exception:
        with contextlib.suppress(OSError):
            path.unlink()
        raise
    return {
        "ok": True,
        "profile": profile,
        "exported_to": str(path),
        "message": "Auth state was written to a 0600 file; token values are not returned in tool output.",
    }


def import_auth(profile: str, auth_blob: dict[str, Any] | str) -> dict[str, Any]:
    try:
        payload = json.loads(auth_blob) if isinstance(auth_blob, str) else auth_blob
    except json.JSONDecodeError as exc:
        raise client.TeslaAPIError("Auth import payload is not valid JSON.") from exc
    if not isinstance(payload, dict):
        raise client.TeslaAPIError("Auth import payload must be a JSON object.")

    allowed = {"access_token", "refresh_token", "expires_at", "scopes", "region", "token_type", "profile"}
    unknown = set(payload) - allowed
    if unknown:
        raise client.TeslaAPIError(f"Auth import payload contains unsupported fields: {sorted(unknown)}")
    scopes = payload.get("scopes", [])
    if scopes is None:
        scopes = []
    if not isinstance(scopes, list) or any(not isinstance(item, str) for item in scopes):
        raise client.TeslaAPIError("Auth import payload field `scopes` must be a list of strings.")
    region = payload.get("region") or config.DEFAULT_REGION
    if region not in client.REGION_BASE_URLS:
        raise client.TeslaAPIError("Auth import payload field `region` is unsupported.")
    token_type = payload.get("token_type") or "Bearer"
    if token_type != "Bearer":
        raise client.TeslaAPIError("Auth import payload field `token_type` must be Bearer.")
    expires_at = payload.get("expires_at")
    if expires_at is not None and (not isinstance(expires_at, int) or expires_at < 0):
        raise client.TeslaAPIError("Auth import payload field `expires_at` must be a non-negative integer.")
    for name in ("access_token", "refresh_token"):
        if payload.get(name) is not None and not isinstance(payload.get(name), str):
            raise client.TeslaAPIError(f"Auth import payload field `{name}` must be a string when present.")

    try:
        state = config.AuthState(
            profile=profile,
            access_token=payload.get("access_token"),
            refresh_token=payload.get("refresh_token"),
            expires_at=expires_at,
            scopes=scopes,
            region=region,
            token_type=token_type,
        )
    except TypeError as exc:
        raise client.TeslaAPIError("Auth import payload is missing required fields or has invalid values.") from exc
    config.save_auth_state(state)
    return {
        "ok": True,
        "profile": profile,
        "authenticated": state.is_authenticated(),
        "region": state.region,
        "scopes": state.scopes,
    }


def generate_vehicle_command_keypair(profile: str, *, domain: str | None = None, force: bool = False) -> dict[str, Any]:
    cfg = config.load_config(profile)
    domain = domain or cfg.domain
    key_dir = config.get_plugin_home() / "keys" / profile
    key_dir.mkdir(parents=True, exist_ok=True)
    try:
        key_dir.chmod(0o700)
    except OSError:
        pass

    private_key_path = key_dir / "vehicle-command-key.pem"
    public_key_path = key_dir / "vehicle-command-key.public.pem"
    if not force and (private_key_path.exists() or public_key_path.exists()):
        raise client.TeslaAPIError("Vehicle-command key already exists. Use tescmd_key_generate with force=true if you really want to replace it.")

    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key = private_key.public_key()

    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    flags = os.O_WRONLY | os.O_CREAT | (os.O_TRUNC if force else os.O_EXCL)
    fd = os.open(private_key_path, flags, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(private_pem)
    public_key_path.write_bytes(
        public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )

    try:
        private_key_path.chmod(0o600)
        public_key_path.chmod(0o644)
    except OSError:
        pass

    cfg.vehicle_command_key_private_path = str(private_key_path)
    cfg.vehicle_command_key_public_path = str(public_key_path)
    config.save_config(cfg)

    payload = {
        "private_key_path": str(private_key_path),
        "public_key_path": str(public_key_path),
    }
    if domain:
        payload["enrollment_url"] = f"https://tesla.com/_ak/{domain}"
    return payload


def register_partner(profile: str) -> dict[str, Any]:
    fleet_client = client.TeslaFleetClient(profile=profile)
    response = fleet_client.register_partner_account()
    return {
        "ok": True,
        "profile": profile,
        "region": fleet_client.region,
        "domain": fleet_client.cfg.domain,
        "response": response,
    }
