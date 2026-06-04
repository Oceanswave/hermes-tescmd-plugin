from __future__ import annotations

import hashlib
import importlib
import inspect
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
HERMES_CONFIG_SECTION = ["plugins", "entries", PLUGIN_DIRNAME, "config"]
HERMES_CONFIG_PROFILES_KEY = "profiles"
EDITABLE_CONFIG_FIELDS = (
    "client_id",
    "region",
    "domain",
    "oauth_redirect_uri",
    "default_vin",
    "scopes",
)
SECRET_CONFIG_FIELDS = (
    "client_secret",
    "vehicle_command_key_private_path",
    "vehicle_command_key_public_path",
    "google_maps_api_key",
)
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
    if (
        not isinstance(value, str)
        or not _PROFILE_PATTERN.fullmatch(value)
        or value in {".", ".."}
        or ".." in value.split(".")
    ):
        raise PluginStateError(
            "Invalid plugin profile name. Use 1-64 letters, numbers, underscore, hyphen, or dot; path traversal is not allowed."
        )
    return value


def validate_public_domain(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    text = str(value).strip().rstrip(".")
    if not text:
        return None
    if any(ch.isspace() for ch in text) or any(ch in text for ch in "/?#@"):
        raise PluginStateError(
            "domain must be a hostname only; do not include scheme, path, query, userinfo, or whitespace."
        )
    if "://" in text:
        raise PluginStateError(
            "domain must not include a URL scheme; provide only the hostname."
        )
    parsed = urlparse(f"//{text}")
    hostname = parsed.hostname
    if (
        not hostname
        or parsed.username
        or parsed.password
        or parsed.path not in ("", None)
    ):
        raise PluginStateError("domain must be a hostname only.")
    if parsed.port is not None:
        raise PluginStateError(
            "domain must not include a port; Tesla virtual-key hosting requires HTTPS on the standard port."
        )
    try:
        ascii_host = hostname.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise PluginStateError("domain is not a valid DNS hostname.") from exc
    if len(ascii_host) > 253 or any(
        not label or len(label) > 63 for label in ascii_host.split(".")
    ):
        raise PluginStateError("domain is not a valid DNS hostname.")
    if ascii_host in {"localhost", "localhost.localdomain"}:
        raise PluginStateError("domain must be public HTTPS hostname, not localhost.")
    try:
        ip = ipaddress.ip_address(ascii_host)
    except ValueError:
        ip = None
    if ip and (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved):
        raise PluginStateError(
            "domain must not be a private, loopback, link-local, or reserved IP address."
        )
    return ascii_host


def validate_oauth_redirect_uri(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    text = str(value).strip()
    parsed = urlparse(text)
    if parsed.scheme != "https":
        raise PluginStateError("oauth_redirect_uri must be a public HTTPS URL.")
    if parsed.username or parsed.password or not parsed.hostname:
        raise PluginStateError(
            "oauth_redirect_uri must not include userinfo and must include a hostname."
        )
    if parsed.query or parsed.fragment:
        raise PluginStateError(
            "oauth_redirect_uri must not include query parameters or fragments."
        )
    if parsed.port is not None:
        raise PluginStateError(
            "oauth_redirect_uri must use standard HTTPS port 443 and must not include an explicit port."
        )
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


def _editable_config_payload(cfg: PluginConfig) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for field_name in EDITABLE_CONFIG_FIELDS:
        value = getattr(cfg, field_name)
        if value is not None:
            payload[field_name] = value
    return payload


def _non_default_editable_values(cfg: PluginConfig) -> dict[str, Any]:
    default = PluginConfig(profile=cfg.profile)
    return {
        key: value
        for key, value in _editable_config_payload(cfg).items()
        if value != getattr(default, key)
    }


def get_editable_config_schema() -> dict[str, Any]:
    """Return dashboard-editable, non-secret config metadata for Hermes."""

    base = ".".join(
        [*HERMES_CONFIG_SECTION, HERMES_CONFIG_PROFILES_KEY, DEFAULT_PROFILE]
    )
    return {
        "plugin": PLUGIN_DIRNAME,
        "title": "Tesla Fleet (tescmd)",
        "category": "tesla",
        "category_label": "Tesla",
        "description": (
            "Dashboard-editable non-secret Tesla Fleet defaults. Secrets stay "
            "in Hermes auth/plugin state and are not exposed here."
        ),
        "path": ".".join(HERMES_CONFIG_SECTION),
        "profiles_path": ".".join([*HERMES_CONFIG_SECTION, HERMES_CONFIG_PROFILES_KEY]),
        "fields": [
            {
                "key": f"{base}.client_id",
                "type": "string",
                "label": "Tesla app client ID",
                "description": "Public OAuth client identifier from the Tesla Developer app. Not a secret.",
                "secret": False,
            },
            {
                "key": f"{base}.region",
                "type": "select",
                "label": "Fleet API region",
                "options": ["na", "eu", "cn"],
                "description": "Default Tesla Fleet API region.",
                "secret": False,
            },
            {
                "key": f"{base}.domain",
                "type": "string",
                "label": "Public domain",
                "description": "HTTPS hostname for Tesla virtual-key hosting and default callback derivation.",
                "secret": False,
            },
            {
                "key": f"{base}.oauth_redirect_uri",
                "type": "string",
                "label": "OAuth redirect URI",
                "description": "Optional public HTTPS callback URL. Defaults to https://<domain>/callback.",
                "secret": False,
            },
            {
                "key": f"{base}.default_vin",
                "type": "string",
                "label": "Default vehicle identifier",
                "description": "Default VIN or Fleet vehicle id_s. Status payloads continue to redact VINs.",
                "secret": False,
            },
            {
                "key": f"{base}.scopes",
                "type": "list",
                "label": "OAuth scopes",
                "description": "Requested Tesla OAuth scopes. Token grants remain in auth state.",
                "secret": False,
            },
        ],
    }


def _hermes_config_module() -> Any | None:
    try:
        module = importlib.import_module("hermes_cli.config")
    except Exception:
        return None
    if not all(hasattr(module, name) for name in ("load_config", "save_config")):
        return None
    return module


def hermes_plugin_config_available() -> bool:
    return _hermes_config_module() is not None


def _nested_dict(
    root: dict[str, Any], path: list[str], *, create: bool = False
) -> dict[str, Any] | None:
    node: Any = root
    for part in path:
        if not isinstance(node, dict):
            return None
        child = node.get(part)
        if child is None and create:
            child = {}
            node[part] = child
        node = child
    return node if isinstance(node, dict) else None


def _load_hermes_config_profiles() -> dict[str, Any]:
    module = _hermes_config_module()
    if module is None:
        return {}
    try:
        root = module.load_config()
    except Exception:
        return {}
    section = _nested_dict(root, HERMES_CONFIG_SECTION)
    profiles = (
        section.get(HERMES_CONFIG_PROFILES_KEY) if isinstance(section, dict) else None
    )
    return dict(profiles) if isinstance(profiles, dict) else {}


def _load_hermes_config_profile(profile: str) -> dict[str, Any]:
    profiles = _load_hermes_config_profiles()
    payload = profiles.get(profile)
    if not isinstance(payload, dict):
        return {}
    return {key: payload[key] for key in EDITABLE_CONFIG_FIELDS if key in payload}


def _hermes_config_profile_contains_secrets(profile: str) -> bool:
    profiles = _load_hermes_config_profiles()
    payload = profiles.get(profile)
    if not isinstance(payload, dict):
        return False
    return any(key in payload for key in SECRET_CONFIG_FIELDS)


def _save_hermes_config_profile(cfg: PluginConfig) -> bool:
    module = _hermes_config_module()
    if module is None:
        return False
    try:
        root = module.load_config()
        if not isinstance(root, dict):
            root = {}
        section = _nested_dict(root, HERMES_CONFIG_SECTION, create=True)
        if section is None:
            return False
        profiles = section.setdefault(HERMES_CONFIG_PROFILES_KEY, {})
        if not isinstance(profiles, dict):
            profiles = {}
            section[HERMES_CONFIG_PROFILES_KEY] = profiles
        existing = profiles.get(cfg.profile)
        profile_payload = dict(existing) if isinstance(existing, dict) else {}
        for editable_name in EDITABLE_CONFIG_FIELDS:
            value = getattr(cfg, editable_name)
            if value is None:
                profile_payload.pop(editable_name, None)
            else:
                profile_payload[editable_name] = value
        for secret_name in SECRET_CONFIG_FIELDS:
            profile_payload.pop(secret_name, None)
        profiles[cfg.profile] = profile_payload
        module.save_config(root)
        return True
    except Exception:
        return False


def _migrate_legacy_config_to_hermes(cfg: PluginConfig) -> bool:
    if _load_hermes_config_profile(cfg.profile):
        return False
    if not _non_default_editable_values(cfg):
        return False
    return _save_hermes_config_profile(cfg)


def _apply_editable_payload(cfg: PluginConfig, payload: dict[str, Any]) -> PluginConfig:
    for key in EDITABLE_CONFIG_FIELDS:
        if key in payload:
            setattr(cfg, key, payload[key])
    return cfg


def register_editable_config(ctx: Any) -> bool:
    """Register tescmd's non-secret config metadata with Hermes when supported."""

    schema = get_editable_config_schema()
    candidates = (
        "register_plugin_config",
        "register_config_section",
        "register_config_schema",
        "register_config",
    )
    call_shapes: tuple[tuple[tuple[Any, ...], dict[str, Any]], ...] = (
        ((), {"plugin": PLUGIN_DIRNAME, "schema": schema}),
        ((PLUGIN_DIRNAME, schema), {}),
        ((schema,), {}),
    )
    for name in candidates:
        method = getattr(ctx, name, None)
        if not callable(method):
            continue
        for args, kwargs in call_shapes:
            try:
                inspect.signature(method).bind(*args, **kwargs)
            except (TypeError, ValueError):
                continue
            method(*args, **kwargs)
            return True
    return False


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


def _normalize_config(cfg: PluginConfig) -> PluginConfig:
    cfg.profile = validate_profile(cfg.profile)
    cfg.region = _validate_region(cfg.region)
    cfg.domain = validate_public_domain(cfg.domain)
    cfg.oauth_redirect_uri = validate_oauth_redirect_uri(cfg.oauth_redirect_uri)
    if cfg.default_vin == "":
        cfg.default_vin = None
    cfg.scopes = _coerce_scopes(cfg.scopes)
    return cfg


def load_config(profile: str = DEFAULT_PROFILE) -> PluginConfig:
    profile = validate_profile(profile)
    payload = _load_profile_map("config.json")
    profile_payload = payload.get(profile)
    if profile_payload:
        allowed = set(PluginConfig.__dataclass_fields__)
        cfg = PluginConfig(**{k: v for k, v in profile_payload.items() if k in allowed})
    else:
        cfg = PluginConfig(profile=profile)

    hermes_payload = _load_hermes_config_profile(profile)
    if hermes_payload:
        _apply_editable_payload(cfg, hermes_payload)
        cfg = _normalize_config(cfg)
        if _hermes_config_profile_contains_secrets(profile):
            _save_hermes_config_profile(cfg)
    else:
        cfg = _normalize_config(cfg)
        # First read after upgrade/backcompat: copy existing non-secret settings
        # into Hermes' plugin config section when the host config store exists.
        _migrate_legacy_config_to_hermes(cfg)
    return cfg


def save_config(cfg: PluginConfig) -> PluginConfig:
    cfg = _normalize_config(cfg)
    payload = _load_profile_map("config.json")
    payload[cfg.profile] = asdict(cfg)
    _save_profile_map("config.json", payload)
    _save_hermes_config_profile(cfg)
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
    provider_state = (
        providers.get(HERMES_AUTH_PROVIDER_ID) if isinstance(providers, dict) else None
    )
    profiles = (
        provider_state.get("profiles") if isinstance(provider_state, dict) else None
    )
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
            provider_state = (
                providers.get(HERMES_AUTH_PROVIDER_ID)
                if isinstance(providers, dict)
                else None
            )
            profiles = (
                provider_state.get("profiles")
                if isinstance(provider_state, dict)
                else None
            )
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


def save_cache_entry(
    profile: str, key: str, value: Any, *, ttl_seconds: int = 60
) -> CacheEntry:
    profile = validate_profile(profile)
    payload = _cache_payload()
    profile_payload = payload.setdefault(profile, {})
    entry = CacheEntry(
        profile=profile,
        key=key,
        value=value,
        expires_at=int(time.time()) + int(ttl_seconds),
    )
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
        expires_at = (
            entry_payload.get("expires_at") if isinstance(entry_payload, dict) else None
        )
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
