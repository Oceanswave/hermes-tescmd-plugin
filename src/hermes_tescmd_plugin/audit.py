from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from . import config

logger = logging.getLogger(__name__)

AUDIT_LOG_NAME = "commands.jsonl"
_MAX_DETAIL_LENGTH = 320
_SENSITIVE_ARG_KEYS = {
    "access_token",
    "address",
    "auth",
    "callback_url",
    "client_id",
    "client_secret",
    "code",
    "default_vin",
    "destination",
    "email",
    "formatted_address",
    "lat",
    "latitude",
    "location",
    "lon",
    "longitude",
    "oauth_redirect_uri",
    "password",
    "pin",
    "place_ids",
    "private_key_path",
    "query",
    "refresh_token",
    "state",
    "token",
    "vin",
}
_VALUE_ARG_KEYS = {
    "amps",
    "command",
    "confirm",
    "enabled",
    "home",
    "manual_override",
    "no_cache",
    "order",
    "other",
    "passenger_temp",
    "percent",
    "profile",
    "region",
    "seat_position",
    "units",
    "volume",
    "wake",
    "work",
}


def audit_log_path() -> Path:
    path = config.get_plugin_home() / "audit" / AUDIT_LOG_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _hash_value(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _target_summary(args: dict[str, Any]) -> dict[str, Any]:
    vin = args.get("vin") or args.get("default_vin")
    if vin is None:
        try:
            vin = config.load_config(
                str(args.get("profile") or config.DEFAULT_PROFILE)
            ).default_vin
        except Exception:
            vin = None
    if vin is None:
        return {"provided": False}
    text = str(vin)
    return {
        "provided": True,
        "hash": _hash_value(text),
        "suffix": text[-4:] if len(text) >= 4 else None,
    }


def _safe_arg_summary(args: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key, value in sorted(args.items()):
        key_text = str(key)
        if key_text in _VALUE_ARG_KEYS:
            summary[key_text] = value
        elif key_text in _SENSITIVE_ARG_KEYS:
            summary[key_text] = "[REDACTED]" if value is not None else None
        elif isinstance(value, (bool, int, float)) or value is None:
            summary[key_text] = value
        else:
            summary[key_text] = _redacted_value_summary(value)
    return summary


def _redacted_value_summary(value: Any) -> dict[str, Any]:
    """Return a useful audit breadcrumb without storing arbitrary user data.

    Only explicitly allowlisted scalar fields are written verbatim. Unknown
    strings can contain addresses, names, email fragments, place queries, or raw
    API payloads, so the audit log records only type/size/hash metadata. The
    hash lets operators correlate repeated values across events without leaking
    the value itself to Hermes logs or JSONL audit storage.
    """
    summary: dict[str, Any] = {
        "redacted": True,
        "type": type(value).__name__,
    }
    if isinstance(value, str):
        summary["length"] = len(value)
        summary["hash"] = _hash_value(value)
    elif isinstance(value, (list, tuple, set)):
        summary["count"] = len(value)
        summary["hash"] = _hash_value(json.dumps(list(value), sort_keys=True, default=str, separators=(",", ":")))
    elif isinstance(value, dict):
        summary["count"] = len(value)
        summary["hash"] = _hash_value(json.dumps(value, sort_keys=True, default=str, separators=(",", ":")))
    else:
        summary["hash"] = _hash_value(value)
    return summary


def _safe_error(error: Any) -> str | None:
    if error is None:
        return None
    text = str(error)
    for word in ("token", "secret", "password", "pin", "authorization", "bearer"):
        if word in text.lower():
            return "[REDACTED]"
    if len(text) > _MAX_DETAIL_LENGTH:
        return text[:_MAX_DETAIL_LENGTH] + "…"
    return text


def append_command_event(
    *,
    tool_name: str,
    operation: str,
    args: dict[str, Any],
    stage: str,
    ok: bool | None = None,
    command_name: str | None = None,
    status_code: int | None = None,
    error: Any = None,
) -> None:
    """Append a redacted command audit event.

    Audit writes are best-effort and must never change vehicle behavior. The log
    intentionally stores only metadata plus redacted argument summaries; VINs and
    location-like values are not written in full.
    """
    if not isinstance(args, dict):
        args = {}
    event = {
        "ts": int(time.time()),
        "tool": tool_name,
        "operation": operation,
        "command_name": command_name,
        "stage": stage,
        "ok": ok,
        "profile": args.get("profile") or config.DEFAULT_PROFILE,
        "region": args.get("region"),
        "confirm": bool(args.get("confirm", False)),
        "wake": bool(args.get("wake", False)) or operation == "vehicle_wake",
        "target": _target_summary(args),
        "args": _safe_arg_summary(args),
        "status_code": status_code,
        "error": _safe_error(error),
        "pid": os.getpid(),
    }
    try:
        logger.info(
            "tescmd command audit event %s",
            json.dumps(event, sort_keys=True, separators=(",", ":")),
        )
    except Exception:
        pass
    try:
        path = audit_log_path()
        with path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n"
            )
        path.chmod(0o600)
    except Exception:
        return


def recent_command_events(limit: int = 20) -> list[dict[str, Any]]:
    path = audit_log_path()
    if not path.exists():
        return []
    if limit < 1:
        return []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]
    events: list[dict[str, Any]] = []
    for line in lines:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            events.append(payload)
    return events
