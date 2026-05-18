from __future__ import annotations

import hashlib
import importlib
import ipaddress
import json
import os
import re
import tempfile
import time
from contextlib import nullcontext
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

PLUGIN_DIRNAME = "hermes-tescmd-plugin"
DEFAULT_REGION = "na"
DEFAULT_PROFILE = "default"
DEFAULT_SCOPES = [
    "openid",
    "offline_access",
    "vehicle_device_data",
    "vehicle_cmds",
    "vehicle_charging_cmds",
    "vehicle_location",
    "energy_device_data",
    "energy_cmds",
    "user_data",
]
PARTNER_ONLY_SCOPES = ["vehicle_specs", "vehicle_pricing_info", "enterprise_management"]
SUPPORTED_SCOPES = [*DEFAULT_SCOPES, *PARTNER_ONLY_SCOPES]


class PluginStateError(RuntimeError):
    pass


@dataclass
class PluginConfig:
    profile: str = DEFAULT_PROFILE
    client_id: str | None = None
    client_secret: str | None = None
    region: str = DEFAULT_REGION
    domain: str | None = None
    oauth_redirect_uri: str | None = None
    default_vin: str | None = None
    scopes: list[str] = field(default_factory=lambda: list(DEFAULT_SCOPES))
    redirect_port: int = 8765
    vehicle_command_key_private_path: str | None = None
    vehicle_command_key_public_path: str | None = None
    google_maps_api_key: str | None = None


@dataclass
class AuthState:
    profile: str = DEFAULT_PROFILE
    access_token: str | None = None
    refresh_token: str | None = None
    expires_at: int | None = None
    scopes: list[str] = field(default_factory=list)
    region: str = DEFAULT_REGION
    token_type: str = "Bearer"

    def is_authenticated(self) -> bool:
        return bool(self.access_token)

    def is_expired(self, leeway_seconds: int = 60) -> bool:
        if self.expires_at is None:
            return False
        return int(time.time()) + leeway_seconds >= int(self.expires_at)


@dataclass
class PendingAuthState:
    profile: str = DEFAULT_PROFILE
    state: str = ""
    code_verifier: str = ""
    redirect_port: int = 8765
    redirect_uri: str = ""
    scopes: list[str] = field(default_factory=list)
    created_at: int = field(default_factory=lambda: int(time.time()))


def _validate_region(region: str) -> str:
    if region not in {"na", "eu", "cn"}:
        raise PluginStateError(f"Unsupported Tesla region in plugin state: {region}")
    return region


_PROFILE_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


def validate_profile(profile: str | None = None) -> str:
    value = profile or DEFAULT_PROFILE
    if not isinstance(value, str) or not _PROFILE_PATTERN.fullmatch(value) or value in {".", ".."} or ".." in value.split("."):
        raise PluginStateError("Invalid plugin profile name. Use 1-64 letters, numbers, underscore, hyphen, or dot; path traversal is not allowed.")
    return value


def validate_public_domain(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    text = str(value).strip().rstrip(".")
    if not text:
        return None
    if any(ch.isspace() for ch in text) or any(ch in text for ch in "/?#@"):
        raise PluginStateError("domain must be a hostname only; do not include scheme, path, query, userinfo, or whitespace.")
    if "://" in text:
        raise PluginStateError("domain must not include a URL scheme; provide only the hostname.")
    parsed = urlparse(f"//{text}")
    hostname = parsed.hostname
    if not hostname or parsed.username or parsed.password or parsed.path not in ("", None):
        raise PluginStateError("domain must be a hostname only.")
    if parsed.port is not None:
        raise PluginStateError("domain must not include a port; Tesla virtual-key hosting requires HTTPS on the standard port.")
    try:
        ascii_host = hostname.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise PluginStateError("domain is not a valid DNS hostname.") from exc
    if len(ascii_host) > 253 or any(not label or len(label) > 63 for label in ascii_host.split(".")):
        raise PluginStateError("domain is not a valid DNS hostname.")
    if ascii_host in {"localhost", "localhost.localdomain"}:
        raise PluginStateError("domain must be public HTTPS hostname, not localhost.")
    try:
        ip = ipaddress.ip_address(ascii_host)
    except ValueError:
        ip = None
    if ip and (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved):
        raise PluginStateError("domain must not be a private, loopback, link-local, or reserved IP address.")
    return ascii_host




def validate_oauth_redirect_uri(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    text = str(value).strip()
    parsed = urlparse(text)
    if parsed.scheme != "https":
        raise PluginStateError("oauth_redirect_uri must be a public HTTPS URL.")
    if parsed.username or parsed.password or not parsed.hostname:
        raise PluginStateError("oauth_redirect_uri must not include userinfo and must include a hostname.")
    if parsed.query or parsed.fragment:
        raise PluginStateError("oauth_redirect_uri must not include query parameters or fragments.")
    if parsed.port is not None:
        raise PluginStateError("oauth_redirect_uri must use standard HTTPS port 443 and must not include an explicit port.")
    host = validate_public_domain(parsed.hostname)
    path = parsed.path or "/callback"
    if not path.startswith("/") or chr(0) in path or ".." in path.split("/"):
        raise PluginStateError("oauth_redirect_uri path is invalid.")
    return f"https://{host}{path}"


def resolve_oauth_redirect_uri(cfg: PluginConfig) -> str | None:
    configured = validate_oauth_redirect_uri(cfg.oauth_redirect_uri)
    if configured:
        return configured
    domain = validate_public_domain(cfg.domain)
    if domain:
        return f"https://{domain}/callback"
    return None


def _validate_profile(profile: str) -> str:
    return validate_profile(profile)


def _coerce_scopes(value: Any) -> list[str]:
    if value is None:
        return list(DEFAULT_SCOPES)
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise PluginStateError("Invalid OAuth scopes in plugin state.")
    return value


def get_hermes_home() -> Path:
    env_home = os.environ.get("HERMES_HOME")
    if env_home:
        return Path(env_home).expanduser().resolve()
    return Path.home().joinpath(".hermes")


def get_plugin_home() -> Path:
    path = get_hermes_home() / "plugins" / PLUGIN_DIRNAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def _profiles_path(name: str) -> Path:
    return get_plugin_home() / name


def _load_profile_map(name: str) -> dict[str, Any]:
    path = _profiles_path(name)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise PluginStateError(f"Stored plugin state is corrupted: {path}") from exc
    if not isinstance(payload, dict):
        raise PluginStateError(f"Stored plugin state has an invalid shape: {path}")
    return payload


def _save_profile_map(name: str, payload: dict[str, Any]) -> None:
    path = _profiles_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False) as handle:
        handle.write(json.dumps(payload, indent=2, sort_keys=True))
        temp_path = Path(handle.name)
    temp_path.replace(path)
    try:
        path.chmod(0o600)
    except OSError:
        pass


def load_config(profile: str = DEFAULT_PROFILE) -> PluginConfig:
    profile = validate_profile(profile)
    payload = _load_profile_map("config.json")
    profile_payload = payload.get(profile)
    if not profile_payload:
        return PluginConfig(profile=profile)
    return PluginConfig(**profile_payload)


def save_config(cfg: PluginConfig) -> PluginConfig:
    cfg.profile = validate_profile(cfg.profile)
    cfg.region = _validate_region(cfg.region)
    cfg.domain = validate_public_domain(cfg.domain)
    cfg.oauth_redirect_uri = validate_oauth_redirect_uri(cfg.oauth_redirect_uri)
    if cfg.default_vin == "":
        cfg.default_vin = None
    cfg.scopes = _coerce_scopes(cfg.scopes)
    payload = _load_profile_map("config.json")
    payload[cfg.profile] = asdict(cfg)
    _save_profile_map("config.json", payload)
    return cfg


HERMES_AUTH_PROVIDER_ID = "tesla"
HERMES_AUTH_SOURCE = "hermes-tescmd-plugin"


def _hermes_auth_module() -> Any | None:
    """Return Hermes' intrinsic auth module when running inside Hermes.

    The plugin also runs in standalone test/package contexts where
    ``hermes_cli`` is intentionally absent. Treat Hermes auth as an optional
    host capability: use it when present, fall back to plugin-owned auth state
    when it is not.
    """
    try:
        module = importlib.import_module("hermes_cli.auth")
    except Exception:
        return None
    required = ("_load_auth_store", "_save_auth_store")
    if not all(hasattr(module, name) for name in required):
        return None
    return module


def _load_hermes_auth_profiles() -> dict[str, Any]:
    module = _hermes_auth_module()
    if module is None:
        return {}
    try:
        store = module._load_auth_store()  # noqa: SLF001 - host auth API has no public plugin writer yet.
    except Exception:
        return {}
    providers = store.get("providers") if isinstance(store, dict) else None
    provider_state = providers.get(HERMES_AUTH_PROVIDER_ID) if isinstance(providers, dict) else None
    profiles = provider_state.get("profiles") if isinstance(provider_state, dict) else None
    return dict(profiles) if isinstance(profiles, dict) else {}


def _save_hermes_auth_state(state: AuthState) -> bool:
    module = _hermes_auth_module()
    if module is None:
        return False
    lock_factory = getattr(module, "_auth_store_lock", None)
    lock = lock_factory() if callable(lock_factory) else nullcontext()
    try:
        with lock:
            store = module._load_auth_store()  # noqa: SLF001
            providers = store.setdefault("providers", {})
            if not isinstance(providers, dict):
                providers = {}
                store["providers"] = providers
            provider_state = providers.get(HERMES_AUTH_PROVIDER_ID)
            if not isinstance(provider_state, dict):
                provider_state = {}
            profiles = provider_state.setdefault("profiles", {})
            if not isinstance(profiles, dict):
                profiles = {}
                provider_state["profiles"] = profiles
            profiles[state.profile] = asdict(state)
            provider_state.update(
                {
                    "auth_type": "oauth",
                    "display_name": "Tesla Fleet",
                    "source": HERMES_AUTH_SOURCE,
                    "updated_at": int(time.time()),
                }
            )
            providers[HERMES_AUTH_PROVIDER_ID] = provider_state
            # Do not set active_provider: Tesla auth is service auth, not the
            # chat model provider selection.
            module._save_auth_store(store)  # noqa: SLF001
        return True
    except Exception:
        return False


def _clear_hermes_auth_state(profile: str) -> bool:
    module = _hermes_auth_module()
    if module is None:
        return False
    lock_factory = getattr(module, "_auth_store_lock", None)
    lock = lock_factory() if callable(lock_factory) else nullcontext()
    try:
        with lock:
            store = module._load_auth_store()  # noqa: SLF001
            providers = store.get("providers")
            provider_state = providers.get(HERMES_AUTH_PROVIDER_ID) if isinstance(providers, dict) else None
            profiles = provider_state.get("profiles") if isinstance(provider_state, dict) else None
            if isinstance(profiles, dict):
                profiles.pop(profile, None)
                if not profiles and isinstance(providers, dict):
                    providers.pop(HERMES_AUTH_PROVIDER_ID, None)
            module._save_auth_store(store)  # noqa: SLF001
        return True
    except Exception:
        return False


def hermes_auth_available() -> bool:
    return _hermes_auth_module() is not None


def load_auth_state(profile: str = DEFAULT_PROFILE) -> AuthState:
    profile = validate_profile(profile)
    hermes_profiles = _load_hermes_auth_profiles()
    hermes_payload = hermes_profiles.get(profile)
    if isinstance(hermes_payload, dict):
        return AuthState(**hermes_payload)
    payload = _load_profile_map("auth.json")
    profile_payload = payload.get(profile)
    if not profile_payload:
        return AuthState(profile=profile)
    state = AuthState(**profile_payload)
    _save_hermes_auth_state(state)
    return state


def save_auth_state(state: AuthState) -> AuthState:
    state.profile = validate_profile(state.profile)
    state.region = _validate_region(state.region)
    _save_hermes_auth_state(state)
    # Keep a plugin-owned mirror for backward compatibility, package tests,
    # and standalone contexts where Hermes' auth store is unavailable.
    payload = _load_profile_map("auth.json")
    payload[state.profile] = asdict(state)
    _save_profile_map("auth.json", payload)
    return state


def clear_auth_state(profile: str = DEFAULT_PROFILE) -> None:
    profile = validate_profile(profile)
    _clear_hermes_auth_state(profile)
    payload = _load_profile_map("auth.json")
    payload.pop(profile, None)
    _save_profile_map("auth.json", payload)


def load_pending_auth(profile: str = DEFAULT_PROFILE) -> PendingAuthState | None:
    profile = validate_profile(profile)
    payload = _load_profile_map("pending-auth.json")
    profile_payload = payload.get(profile)
    if not profile_payload:
        return None
    return PendingAuthState(**profile_payload)


def save_pending_auth(state: PendingAuthState) -> PendingAuthState:
    state.profile = validate_profile(state.profile)
    payload = _load_profile_map("pending-auth.json")
    payload[state.profile] = asdict(state)
    _save_profile_map("pending-auth.json", payload)
    return state


def clear_pending_auth(profile: str = DEFAULT_PROFILE) -> None:
    profile = validate_profile(profile)
    payload = _load_profile_map("pending-auth.json")
    payload.pop(profile, None)
    _save_profile_map("pending-auth.json", payload)



@dataclass
class CacheEntry:
    profile: str
    key: str
    value: Any
    created_at: int = field(default_factory=lambda: int(time.time()))
    expires_at: int | None = None

    def is_expired(self) -> bool:
        return self.expires_at is not None and int(time.time()) >= int(self.expires_at)


def _cache_payload() -> dict[str, Any]:
    return _load_profile_map("response-cache.json")


def make_cache_key(parts: dict[str, Any]) -> str:
    canonical = json.dumps(parts, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_cache_entry(profile: str, key: str) -> CacheEntry | None:
    profile = validate_profile(profile)
    payload = _cache_payload()
    profile_payload = payload.get(profile) or {}
    entry_payload = profile_payload.get(key)
    if not entry_payload:
        return None
    entry = CacheEntry(**entry_payload)
    if entry.is_expired():
        profile_payload.pop(key, None)
        payload[profile] = profile_payload
        _save_profile_map("response-cache.json", payload)
        return None
    return entry


def save_cache_entry(profile: str, key: str, value: Any, *, ttl_seconds: int = 60) -> CacheEntry:
    profile = validate_profile(profile)
    payload = _cache_payload()
    profile_payload = payload.setdefault(profile, {})
    entry = CacheEntry(profile=profile, key=key, value=value, expires_at=int(time.time()) + int(ttl_seconds))
    profile_payload[key] = asdict(entry)
    _save_profile_map("response-cache.json", payload)
    return entry


def cache_status(profile: str = DEFAULT_PROFILE) -> dict[str, Any]:
    profile = validate_profile(profile)
    payload = _cache_payload()
    profile_payload = payload.get(profile) or {}
    now = int(time.time())
    valid = 0
    expired = 0
    for entry_payload in profile_payload.values():
        expires_at = entry_payload.get("expires_at") if isinstance(entry_payload, dict) else None
        if expires_at is not None and now >= int(expires_at):
            expired += 1
        else:
            valid += 1
    return {"enabled": True, "entries": valid, "expired_entries": expired}


def clear_cache(profile: str = DEFAULT_PROFILE) -> int:
    profile = validate_profile(profile)
    payload = _cache_payload()
    profile_payload = payload.get(profile) or {}
    count = len(profile_payload)
    payload[profile] = {}
    _save_profile_map("response-cache.json", payload)
    return count
