from __future__ import annotations

import asyncio
import base64
import json as json_module
import threading
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from . import config
from .errors import NetworkError, TeslaAPIError
from .protocol.commands import get_command_spec
from .protocol.encoder import (
    build_signed_command,
    default_expiry,
    encode_routable_message,
)
from .protocol.metadata import encode_metadata
from .protocol.payloads import build_command_payload
from .protocol.protobuf.messages import (
    FAULT_DESCRIPTIONS,
    MessageFault,
    OperationStatus,
    RoutableMessage,
)
from .protocol.session import SessionManager
from .protocol.signer import compute_hmac_tag

AUTH_BASE_URL = "https://auth.tesla.com/oauth2/v3"
TOKEN_URL = "https://fleet-auth.prd.vn.cloud.tesla.com/oauth2/v3/token"
REGION_BASE_URLS = {
    "na": "https://fleet-api.prd.na.vn.cloud.tesla.com",
    "eu": "https://fleet-api.prd.eu.vn.cloud.tesla.com",
    "cn": "https://fleet-api.prd.cn.vn.cloud.tesla.cn",
}

_SESSION_MANAGERS: dict[tuple[str, str, str, int | None], SessionManager] = {}
_SESSION_MANAGERS_LOCK = threading.Lock()
_VIN_PATTERN = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")
_PATH_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")


def validate_vin(vin: str) -> str:
    """Validate a Fleet API vehicle path identifier.

    Tesla account product responses may expose `id_s`/vehicle identifiers instead of
    full 17-character VINs, depending on account/app access. Fleet vehicle endpoint
    path slots accept those opaque identifiers, so allow either a normal VIN or a
    conservative path-safe Tesla vehicle identifier.
    """
    if not isinstance(vin, str) or not vin:
        raise TeslaAPIError(
            "Vehicle identifier must be a Tesla VIN or path-safe Fleet vehicle ID."
        )
    if _VIN_PATTERN.fullmatch(vin) or _PATH_ID_PATTERN.fullmatch(vin):
        return vin
    raise TeslaAPIError(
        "Vehicle identifier must be a Tesla VIN or path-safe Fleet vehicle ID."
    )


def is_tesla_vin(value: Any) -> bool:
    """Return true when a value is a full 17-character Tesla VIN, not an id_s."""
    return isinstance(value, str) and bool(_VIN_PATTERN.fullmatch(value))


def quote_path_component(value: str, *, name: str = "path component") -> str:
    from urllib.parse import quote

    if (
        not isinstance(value, str)
        or not value
        or "\x00" in value
        or "/" in value
        or "?" in value
        or "#" in value
    ):
        raise TeslaAPIError(
            f"{name} contains invalid characters for a Fleet API path component."
        )
    if not _PATH_ID_PATTERN.fullmatch(value):
        raise TeslaAPIError(
            f"{name} contains unsupported characters for a Fleet API path component."
        )
    return quote(value, safe="")


@dataclass
class TeslaResponse:
    data: Any
    status_code: int


def fleet_base_url(region: str) -> str:
    if region not in REGION_BASE_URLS:
        raise TeslaAPIError(f"Unsupported Tesla region: {region}")
    return REGION_BASE_URLS[region]


def _json_or_text(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return response.text


def request(method: str, url: str, **kwargs: Any) -> TeslaResponse:
    try:
        response = httpx.request(
            method, url, timeout=kwargs.pop("timeout", 30), **kwargs
        )
    except httpx.HTTPError as exc:
        raise NetworkError(f"Tesla API network request failed: {exc}") from exc
    payload = _json_or_text(response)
    if response.status_code >= 400:
        message = (
            response.text.strip()
            or f"Tesla API request failed with status {response.status_code}"
        )
        raise TeslaAPIError(message, status_code=response.status_code, payload=payload)
    return TeslaResponse(data=payload, status_code=response.status_code)


def exchange_authorization_code(
    *, cfg: config.PluginConfig, code: str, code_verifier: str, redirect_uri: str
) -> config.AuthState:
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "code_verifier": code_verifier,
        "client_id": cfg.client_id,
        "audience": fleet_base_url(cfg.region),
        "redirect_uri": redirect_uri,
    }
    if cfg.client_secret:
        data["client_secret"] = cfg.client_secret
    response = request("POST", TOKEN_URL, data=data)
    return auth_state_from_token_response(cfg.profile, cfg.region, response.data)


def refresh_access_token(
    cfg: config.PluginConfig, auth_state: config.AuthState
) -> config.AuthState:
    if not auth_state.refresh_token:
        raise TeslaAPIError("No refresh token is stored for this profile.")
    data = {
        "grant_type": "refresh_token",
        "refresh_token": auth_state.refresh_token,
        "client_id": cfg.client_id,
        "audience": fleet_base_url(cfg.region),
    }
    if cfg.client_secret:
        data["client_secret"] = cfg.client_secret
    response = request("POST", TOKEN_URL, data=data)
    return auth_state_from_token_response(
        cfg.profile,
        cfg.region,
        response.data,
        fallback_refresh_token=auth_state.refresh_token,
    )


def get_partner_access_token(cfg: config.PluginConfig, scope: str | None = None) -> str:
    if not cfg.client_id or not cfg.client_secret:
        raise TeslaAPIError(
            "Client ID and client secret are required for partner registration."
        )
    data = {
        "grant_type": "client_credentials",
        "client_id": cfg.client_id,
        "client_secret": cfg.client_secret,
        "audience": fleet_base_url(cfg.region),
        "scope": scope
        or "openid vehicle_device_data vehicle_cmds vehicle_charging_cmds user_data",
    }
    response = request("POST", TOKEN_URL, data=data)
    token = (
        response.data.get("access_token") if isinstance(response.data, dict) else None
    )
    if not token:
        raise TeslaAPIError(
            "Tesla token endpoint did not return an access token.",
            payload=response.data,
        )
    return token


def auth_state_from_token_response(
    profile: str,
    region: str,
    payload: dict[str, Any],
    *,
    fallback_refresh_token: str | None = None,
) -> config.AuthState:
    if not isinstance(payload, dict):
        raise TeslaAPIError(
            "Tesla token endpoint returned a non-JSON-object payload.", payload=payload
        )
    expires_in = int(payload.get("expires_in", 0) or 0)
    scope_text = str(payload.get("scope", "")).strip()
    scopes = [scope for scope in scope_text.split() if scope]
    refresh_token = payload.get("refresh_token") or fallback_refresh_token
    access_token = payload.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise TeslaAPIError(
            "Tesla token endpoint did not return an access token.", payload=payload
        )
    if refresh_token is not None and not isinstance(refresh_token, str):
        raise TeslaAPIError(
            "Tesla token endpoint returned an invalid refresh token.", payload=payload
        )
    if not scopes:
        try:
            claims_part = access_token.split(".")[1]
            claims_part += "=" * (-len(claims_part) % 4)
            claims = json_module.loads(base64.urlsafe_b64decode(claims_part))
            token_scopes = claims.get("scp")
            if isinstance(token_scopes, list):
                scopes = [
                    str(scope) for scope in token_scopes if isinstance(scope, str)
                ]
        except (IndexError, ValueError, TypeError, json_module.JSONDecodeError):
            scopes = []
    if region not in REGION_BASE_URLS:
        raise TeslaAPIError(
            f"Unsupported Tesla region in token response: {region}", payload=payload
        )
    return config.AuthState(
        profile=profile,
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=int(time.time()) + expires_in if expires_in else None,
        scopes=scopes,
        region=region,
        token_type=str(payload.get("token_type", "Bearer") or "Bearer"),
    )


def load_private_key(
    profile: str = config.DEFAULT_PROFILE,
) -> ec.EllipticCurvePrivateKey:
    cfg = config.load_config(profile)
    key_path = cfg.vehicle_command_key_private_path
    if not key_path:
        raise TeslaAPIError(
            "No vehicle-command private key is configured for this profile."
        )
    pem = Path(key_path).read_bytes()
    private_key = serialization.load_pem_private_key(pem, password=None)
    if not isinstance(private_key, ec.EllipticCurvePrivateKey):
        raise TeslaAPIError("Configured vehicle-command key is not an EC private key.")
    return private_key


class TeslaFleetClient:
    def __init__(
        self,
        *,
        profile: str = config.DEFAULT_PROFILE,
        region_override: str | None = None,
    ) -> None:
        self.profile = profile
        self.cfg = config.load_config(profile)
        self.auth_state = config.load_auth_state(profile)
        self.region = region_override or self.cfg.region or self.auth_state.region
        self.base_url = fleet_base_url(self.region)

    def _ensure_access_token(self) -> str:
        if not self.auth_state.access_token:
            raise TeslaAPIError(
                "Tesla authentication is not configured for this profile."
            )
        if self.auth_state.is_expired():
            self.auth_state = refresh_access_token(self.cfg, self.auth_state)
            config.save_auth_state(self.auth_state)
            self.region = self.auth_state.region or self.cfg.region
            self.base_url = fleet_base_url(self.region)
        assert self.auth_state.access_token is not None
        return self.auth_state.access_token

    def _headers(self) -> dict[str, str]:
        token = self._ensure_access_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _validate_api_path(path: str) -> str:
        if not isinstance(path, str) or not path.startswith("/api/"):
            raise TeslaAPIError(
                "Fleet API paths must be relative paths starting with /api/."
            )
        if "://" in path or ".." in path or "\x00" in path:
            raise TeslaAPIError(
                "Fleet API paths must not be absolute URLs, contain NUL bytes, or parent-directory traversal."
            )
        return path

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        path = self._validate_api_path(path)
        response = request(
            method, f"{self.base_url}{path}", headers=self._headers(), **kwargs
        )
        return response.data

    async def post(self, path: str, **kwargs: Any) -> Any:
        return self.request("POST", path, **kwargs)

    async def delete(self, path: str, **kwargs: Any) -> Any:
        return self.request("DELETE", path, **kwargs)

    def response_payload(self, payload: Any) -> Any:
        return (
            payload.get("response", payload) if isinstance(payload, dict) else payload
        )

    def raw_get(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        return self.request("GET", path, params=params)

    def raw_post(self, path: str, *, body: dict[str, Any] | None = None) -> Any:
        return self.request("POST", path, json=body)

    def raw_delete(self, path: str, *, body: dict[str, Any] | None = None) -> Any:
        return self.request("DELETE", path, json=body)

    def partner_request(
        self, method: str, path: str, *, scope: str | None = None, **kwargs: Any
    ) -> Any:
        token = get_partner_access_token(self.cfg, scope=scope)
        response = request(
            method,
            f"{self.base_url}{path}",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            **kwargs,
        )
        return response.data

    def _signed_command_session_manager(self) -> SessionManager:
        key_path = self.cfg.vehicle_command_key_private_path
        if not key_path:
            raise TeslaAPIError(
                "No vehicle-command private key is configured for this profile."
            )
        try:
            key_mtime = Path(key_path).stat().st_mtime_ns
        except OSError as exc:
            raise TeslaAPIError(
                f"Configured vehicle-command private key is not readable: {key_path}"
            ) from exc
        cache_key = (self.profile, self.region, key_path, key_mtime)
        with _SESSION_MANAGERS_LOCK:
            manager = _SESSION_MANAGERS.get(cache_key)
            if manager is None:
                manager = SessionManager(load_private_key(self.profile), self)
                _SESSION_MANAGERS[cache_key] = manager
        return manager

    def _decode_signed_command_response(
        self,
        vin: str,
        command_name: str,
        payload: Any,
        *,
        session_manager: SessionManager,
        domain: Any,
    ) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return {"result": True, "raw": payload}
        response_b64 = payload.get("response")
        if not response_b64:
            return {"result": True, "response": payload}
        try:
            decoded = base64.b64decode(response_b64, validate=True)
            response_msg = RoutableMessage.parse(decoded)
        except Exception as exc:  # pragma: no cover
            raise TeslaAPIError(
                f"Failed to parse signed-command response for {command_name}: {exc}",
                payload=payload,
            ) from exc

        operation_status = response_msg.operation_status
        if operation_status not in (
            OperationStatus.OPERATIONSTATUS_OK,
            OperationStatus.OPERATIONSTATUS_WAIT,
        ):
            session_manager.invalidate(vin, domain)
            raise TeslaAPIError(
                f"Vehicle did not complete signed command {command_name}: {operation_status.name}",
                status_code=422,
                payload=payload,
            )

        fault = response_msg.signed_message_fault
        if fault != MessageFault.ERROR_NONE:
            session_manager.invalidate(vin, domain)
            desc = FAULT_DESCRIPTIONS.get(fault, fault.name)
            raise TeslaAPIError(
                f"Vehicle rejected signed command {command_name}: {desc}",
                status_code=422,
                payload=payload,
            )
        return {"result": True, "transport": "signed_command"}

    def _signed_vehicle_command(
        self, vin: str, command_name: str, body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        spec = get_command_spec(command_name)
        if spec is None:
            raise TeslaAPIError(
                f"No signed-command registry entry exists for vehicle command: {command_name}"
            )
        if not spec.requires_signing:
            command_path = quote_path_component(command_name, name="command name")
            return self.response_payload(
                self.request(
                    "POST",
                    f"/api/1/vehicles/{validate_vin(vin)}/command/{command_path}",
                    json=body,
                )
            )

        session_manager = self._signed_command_session_manager()
        session = asyncio.run(session_manager.get_session(vin, spec.domain))
        payload_bytes = build_command_payload(command_name, body)
        counter = session.next_counter()
        expires_at = default_expiry(session.time_zero)
        metadata_bytes = encode_metadata(
            epoch=session.epoch,
            expires_at=expires_at,
            counter=counter,
            domain=spec.domain,
            vin=vin,
        )
        hmac_tag = compute_hmac_tag(session.signing_key, metadata_bytes, payload_bytes)
        routable_message = build_signed_command(
            domain=spec.domain,
            payload=payload_bytes,
            client_public_key=session_manager.client_public_key,
            epoch=session.epoch,
            counter=counter,
            expires_at=expires_at,
            hmac_tag=hmac_tag,
        )
        response = self.request(
            "POST",
            f"/api/1/vehicles/{validate_vin(vin)}/signed_command",
            json={"routable_message": encode_routable_message(routable_message)},
        )
        return self._decode_signed_command_response(
            vin,
            command_name,
            response,
            session_manager=session_manager,
            domain=spec.domain,
        )

    def list_vehicles(self) -> list[dict[str, Any]]:
        return self.response_payload(self.request("GET", "/api/1/vehicles"))

    def vehicle(self, vin: str) -> dict[str, Any]:
        return self.response_payload(
            self.request("GET", f"/api/1/vehicles/{validate_vin(vin)}")
        )

    def vehicle_status(
        self, vin: str, endpoints: list[str] | None = None
    ) -> dict[str, Any]:
        params = None
        if endpoints:
            params = {"endpoints": ";".join(endpoints)}
        return self.response_payload(
            self.request(
                "GET",
                f"/api/1/vehicles/{validate_vin(vin)}/vehicle_data",
                params=params,
            )
        )

    def wake_vehicle(self, vin: str) -> dict[str, Any]:
        return self.response_payload(
            self.request("POST", f"/api/1/vehicles/{validate_vin(vin)}/wake_up")
        )

    def mobile_enabled(self, vin: str) -> bool:
        return bool(
            self.response_payload(
                self.request(
                    "GET", f"/api/1/vehicles/{validate_vin(vin)}/mobile_enabled"
                )
            )
        )

    def nearby_charging_sites(self, vin: str) -> dict[str, Any]:
        return self.response_payload(
            self.request(
                "GET", f"/api/1/vehicles/{validate_vin(vin)}/nearby_charging_sites"
            )
        )

    def recent_alerts(self, vin: str) -> list[dict[str, Any]]:
        return self.response_payload(
            self.request("GET", f"/api/1/vehicles/{validate_vin(vin)}/recent_alerts")
        )

    def release_notes(self, vin: str) -> dict[str, Any]:
        return self.response_payload(
            self.request("GET", f"/api/1/vehicles/{validate_vin(vin)}/release_notes")
        )

    def service_data(self, vin: str) -> dict[str, Any]:
        return self.response_payload(
            self.request("GET", f"/api/1/vehicles/{validate_vin(vin)}/service_data")
        )

    def drivers(self, vin: str) -> list[dict[str, Any]]:
        return self.response_payload(
            self.request("GET", f"/api/1/vehicles/{validate_vin(vin)}/drivers")
        )

    def subscriptions(self, vin: str) -> dict[str, Any]:
        return self.response_payload(
            self.request(
                "GET",
                "/api/1/dx/vehicles/subscriptions/eligibility",
                params={"vin": vin},
            )
        )

    def upgrades(self, vin: str) -> dict[str, Any]:
        return self.response_payload(
            self.request(
                "GET", "/api/1/dx/vehicles/upgrades/eligibility", params={"vin": vin}
            )
        )

    def options(self, vin: str) -> dict[str, Any]:
        return self.response_payload(
            self.request("GET", "/api/1/dx/vehicles/options", params={"vin": vin})
        )

    def specs(self, vin: str) -> dict[str, Any]:
        return self.response_payload(
            self.partner_request(
                "GET",
                f"/api/1/vehicles/{validate_vin(vin)}/specs",
                scope="vehicle_specs",
            )
        )

    def warranty_details(self, *, vin: str | None = None) -> dict[str, Any]:
        params = {"vin": vin} if vin else None
        return self.response_payload(
            self.request("GET", "/api/1/dx/warranty/details", params=params)
        )

    def fleet_status(self, *, vins: list[str]) -> dict[str, Any]:
        return self.response_payload(
            self.request("POST", "/api/1/vehicles/fleet_status", json={"vins": vins})
        )

    def fleet_telemetry_config(self, vin: str) -> dict[str, Any]:
        return self.response_payload(
            self.request(
                "GET", f"/api/1/vehicles/{validate_vin(vin)}/fleet_telemetry_config"
            )
        )

    def fleet_telemetry_config_create(
        self, *, config_payload: dict[str, Any]
    ) -> dict[str, Any]:
        return self.response_payload(
            self.request(
                "POST", "/api/1/vehicles/fleet_telemetry_config", json=config_payload
            )
        )

    def fleet_telemetry_config_delete(self, vin: str) -> dict[str, Any]:
        return self.response_payload(
            self.request(
                "DELETE", f"/api/1/vehicles/{validate_vin(vin)}/fleet_telemetry_config"
            )
        )

    def fleet_telemetry_errors(self, vin: str) -> dict[str, Any]:
        return self.response_payload(
            self.request(
                "GET", f"/api/1/vehicles/{validate_vin(vin)}/fleet_telemetry_errors"
            )
        )

    def user_me(self) -> dict[str, Any]:
        return self.response_payload(self.request("GET", "/api/1/users/me"))

    def user_region(self) -> dict[str, Any]:
        return self.response_payload(self.request("GET", "/api/1/users/region"))

    def user_orders(self) -> list[dict[str, Any]]:
        return self.response_payload(self.request("GET", "/api/1/users/orders"))

    def user_feature_config(self) -> dict[str, Any]:
        return self.response_payload(self.request("GET", "/api/1/users/feature_config"))

    def charging_history(
        self,
        *,
        vin: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
        page_no: int | None = None,
        page_size: int | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if vin is not None:
            params["vin"] = vin
        if start_time is not None:
            params["startTime"] = start_time
        if end_time is not None:
            params["endTime"] = end_time
        if page_no is not None:
            params["pageNo"] = page_no
        if page_size is not None:
            params["pageSize"] = page_size
        return self.response_payload(
            self.request("GET", "/api/1/dx/charging/history", params=params or None)
        )

    def charging_sessions(
        self,
        *,
        vin: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if vin is not None:
            params["vin"] = vin
        if date_from is not None:
            params["date_from"] = date_from
        if date_to is not None:
            params["date_to"] = date_to
        if limit is not None:
            params["limit"] = limit
        if offset is not None:
            params["offset"] = offset
        return self.response_payload(
            self.request("GET", "/api/1/dx/charging/sessions", params=params or None)
        )

    def charging_invoice(self, invoice_id: str) -> dict[str, Any]:
        invoice_path = quote_path_component(invoice_id, name="invoice_id")
        return self.response_payload(
            self.request("GET", f"/api/1/dx/charging/invoice/{invoice_path}")
        )

    def energy_products(self) -> list[dict[str, Any]]:
        return self.response_payload(self.request("GET", "/api/1/products"))

    def energy_live_status(self, site_id: int) -> dict[str, Any]:
        return self.response_payload(
            self.request("GET", f"/api/1/energy_sites/{site_id}/live_status")
        )

    def energy_site_info(self, site_id: int) -> dict[str, Any]:
        return self.response_payload(
            self.request("GET", f"/api/1/energy_sites/{site_id}/site_info")
        )

    def energy_backup(self, site_id: int, percent: int) -> dict[str, Any]:
        return self.response_payload(
            self.request(
                "POST",
                f"/api/1/energy_sites/{site_id}/backup",
                json={"backup_reserve_percent": percent},
            )
        )

    def energy_operation_mode(self, site_id: int, mode: str) -> dict[str, Any]:
        return self.response_payload(
            self.request(
                "POST",
                f"/api/1/energy_sites/{site_id}/operation",
                json={"default_real_mode": mode},
            )
        )

    def energy_storm_mode(self, site_id: int, enabled: bool) -> dict[str, Any]:
        return self.response_payload(
            self.request(
                "POST",
                f"/api/1/energy_sites/{site_id}/storm_mode",
                json={"enabled": enabled},
            )
        )

    def energy_time_of_use(
        self, site_id: int, settings: dict[str, Any]
    ) -> dict[str, Any]:
        return self.response_payload(
            self.request(
                "POST",
                f"/api/1/energy_sites/{site_id}/time_of_use_settings",
                json={"tou_settings": settings},
            )
        )

    def energy_off_grid_vehicle_charging_reserve(
        self, site_id: int, reserve: int
    ) -> dict[str, Any]:
        return self.response_payload(
            self.request(
                "POST",
                f"/api/1/energy_sites/{site_id}/off_grid_vehicle_charging_reserve",
                json={"off_grid_vehicle_charging_reserve_percent": reserve},
            )
        )

    def energy_grid_import_export(
        self, site_id: int, config_payload: dict[str, Any]
    ) -> dict[str, Any]:
        return self.response_payload(
            self.request(
                "POST",
                f"/api/1/energy_sites/{site_id}/grid_import_export",
                json=config_payload,
            )
        )

    def energy_calendar_history(
        self,
        site_id: int,
        *,
        kind: str = "energy",
        period: str = "day",
        start_date: str | None = None,
        end_date: str | None = None,
        time_zone: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"kind": kind, "period": period}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        if time_zone:
            params["time_zone"] = time_zone
        return self.response_payload(
            self.request(
                "GET", f"/api/1/energy_sites/{site_id}/calendar_history", params=params
            )
        )

    def energy_telemetry_history(
        self,
        site_id: int,
        *,
        kind: str = "charge",
        start_date: str | None = None,
        end_date: str | None = None,
        time_zone: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"kind": kind}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        if time_zone:
            params["time_zone"] = time_zone
        return self.response_payload(
            self.request(
                "GET", f"/api/1/energy_sites/{site_id}/telemetry_history", params=params
            )
        )

    def add_driver(self, vin: str, email: str) -> dict[str, Any]:
        return self.response_payload(
            self.request(
                "POST",
                f"/api/1/vehicles/{validate_vin(vin)}/drivers",
                json={"email": email},
            )
        )

    def remove_driver(self, vin: str, share_user_id: int) -> dict[str, Any]:
        return self.response_payload(
            self.request(
                "DELETE",
                f"/api/1/vehicles/{validate_vin(vin)}/drivers",
                json={"share_user_id": share_user_id},
            )
        )

    def create_invite(self, vin: str) -> dict[str, Any]:
        return self.response_payload(
            self.request("POST", f"/api/1/vehicles/{validate_vin(vin)}/invitations")
        )

    def list_invites(self, vin: str) -> list[dict[str, Any]]:
        return self.response_payload(
            self.request("GET", f"/api/1/vehicles/{validate_vin(vin)}/invitations")
        )

    def redeem_invite(self, code: str) -> dict[str, Any]:
        return self.response_payload(
            self.request("POST", "/api/1/invitations/redeem", json={"code": code})
        )

    def revoke_invite(self, vin: str, invite_id: str) -> dict[str, Any]:
        invite_path = quote_path_component(invite_id, name="invite_id")
        return self.response_payload(
            self.request(
                "POST",
                f"/api/1/vehicles/{validate_vin(vin)}/invitations/{invite_path}/revoke",
            )
        )

    def vehicle_pricing(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.response_payload(
            self.partner_request(
                "POST",
                "/api/1/dx/vehicles/pricing",
                json=payload,
                scope="vehicle_pricing_info",
            )
        )

    def enterprise_roles(self, vin: str) -> dict[str, Any]:
        return self.response_payload(
            self.request("GET", f"/api/1/dx/enterprise/v1/{validate_vin(vin)}/roles")
        )

    def enterprise_payer(self, vin: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.response_payload(
            self.request(
                "POST",
                f"/api/1/dx/enterprise/v1/{validate_vin(vin)}/payer",
                json=payload,
            )
        )

    def fleet_telemetry_config_jws(self, token: str) -> dict[str, Any]:
        return self.response_payload(
            self.request(
                "POST",
                "/api/1/vehicles/fleet_telemetry_config_jws",
                json={"token": token},
            )
        )

    def vehicle_command(
        self, vin: str, command_name: str, body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        spec = get_command_spec(command_name)
        if spec is None:
            raise TeslaAPIError(
                f"No vehicle-command registry entry exists for command: {command_name}. "
                "Add the command to the signed/unsigned registry before exposing it.",
                status_code=422,
            )
        if spec.requires_signing:
            if not self.cfg.vehicle_command_key_private_path:
                raise TeslaAPIError(
                    "This command requires Tesla's Vehicle Command Protocol, but no plugin-owned "
                    "vehicle-command private key is configured. Run tescmd_key_generate, host the "
                    "public key, register/enroll it, then retry. The plugin will not silently fall "
                    "back to the legacy /command endpoint for signed commands.",
                    status_code=422,
                )
            return self._signed_vehicle_command(vin, command_name, body)
        command_path = quote_path_component(command_name, name="command name")
        return self.response_payload(
            self.request(
                "POST",
                f"/api/1/vehicles/{validate_vin(vin)}/command/{command_path}",
                json=body,
            )
        )

    def register_partner_account(self, domain: str | None = None) -> dict[str, Any]:
        domain = domain or self.cfg.domain
        if not domain:
            raise TeslaAPIError(
                "A configured domain is required for partner registration."
            )
        token = get_partner_access_token(self.cfg)
        response = request(
            "POST",
            f"{self.base_url}/api/1/partner_accounts",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={"domain": domain},
        )
        return self.response_payload(response.data)

    def partner_public_key(self, domain: str) -> dict[str, Any]:
        return self.response_payload(
            self.partner_request(
                "GET", "/api/1/partner_accounts/public_key", params={"domain": domain}
            )
        )

    def partner_fleet_telemetry_error_vins(self) -> list[str]:
        return self.response_payload(
            self.partner_request(
                "GET", "/api/1/partner_accounts/fleet_telemetry_error_vins"
            )
        )

    def partner_fleet_telemetry_errors(self) -> list[dict[str, Any]]:
        return self.response_payload(
            self.partner_request(
                "GET", "/api/1/partner_accounts/fleet_telemetry_errors"
            )
        )
