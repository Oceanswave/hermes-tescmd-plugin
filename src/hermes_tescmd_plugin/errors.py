from __future__ import annotations

from typing import Any

_SENSITIVE_KEY_PARTS = (
    "token",
    "secret",
    "authorization",
    "password",
    "code",
    "verifier",
    "api_key",
)


def _safe_payload(value: Any) -> Any:
    if isinstance(value, dict):
        safe: dict[Any, Any] = {}
        for key, item in value.items():
            key_text = str(key).lower()
            if any(part in key_text for part in _SENSITIVE_KEY_PARTS):
                safe[key] = "[REDACTED]" if item is not None else None
            else:
                safe[key] = _safe_payload(item)
        return safe
    if isinstance(value, list):
        return [_safe_payload(item) for item in value]
    return value


class TeslaAPIError(Exception):
    """Base exception for Tesla Fleet API and protocol failures."""

    def __init__(
        self, message: str, status_code: int | None = None, payload=None
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.payload = _safe_payload(payload)


class AuthError(TeslaAPIError):
    pass


class VehicleAsleepError(TeslaAPIError):
    pass


class VehicleNotFoundError(TeslaAPIError):
    pass


class CommandFailedError(TeslaAPIError):
    def __init__(
        self, message: str, reason: str, status_code: int | None = None, payload=None
    ) -> None:
        super().__init__(message, status_code=status_code, payload=payload)
        self.reason = reason


class RateLimitError(TeslaAPIError):
    def __init__(
        self,
        message: str = "Rate limit exceeded",
        retry_after: int | None = None,
        payload=None,
    ) -> None:
        super().__init__(message, status_code=429, payload=payload)
        self.retry_after = retry_after


class RegistrationRequiredError(TeslaAPIError):
    pass


class NetworkError(TeslaAPIError):
    pass


class ConfigError(Exception):
    pass


class SessionError(TeslaAPIError):
    pass


class MissingScopesError(AuthError):
    pass


class VCPRequiredError(TeslaAPIError):
    pass


class KeyNotEnrolledError(TeslaAPIError):
    pass
