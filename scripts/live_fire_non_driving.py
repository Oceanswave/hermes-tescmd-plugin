#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hermes_tescmd_plugin import runtime  # noqa: E402

VIN_RE = re.compile(r"\b[A-HJ-NPR-Z0-9]{17}\b")
SENSITIVE_KEYS = {
    "vin",
    "id",
    "id_s",
    "vehicle_id",
    "user_id",
    "email",
    "access_token",
    "refresh_token",
    "client_secret",
    "domain",
    "url",
    "oauth_redirect_uri",
    "default_vin",
    "vehicle_name",
    "target",
    "private_key_path",
    "public_key_path",
    "local_fingerprint",
    "remote_fingerprint",
}
TAILSCALE_RE = re.compile(r"\b[a-z0-9-]+\.[a-z0-9-]+\.ts\.net\b", re.I)


def redact(obj: Any) -> Any:
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            lk = str(k).lower()
            if any(s in lk for s in SENSITIVE_KEYS):
                out[k] = "[REDACTED]"
            else:
                out[k] = redact(v)
        return out
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    if isinstance(obj, str):
        s = VIN_RE.sub("[REDACTED_VIN]", obj)
        s = TAILSCALE_RE.sub("tesla-keyhost.example-tailnet.ts.net", s)
        s = re.sub(r"Bearer\s+[^\s]+", "Bearer [REDACTED]", s, flags=re.I)
        s = re.sub(r"(access_token|refresh_token|client_secret|code|state)=([^&\s]+)", r"\1=[REDACTED]", s, flags=re.I)
        s = re.sub(r"\b[0-9a-f]{40,64}\b", "[REDACTED_HASH]", s, flags=re.I)
        return s
    return obj


def call(handlers: dict[str, Any], name: str, args: dict[str, Any]) -> dict[str, Any]:
    started = datetime.now(timezone.utc).isoformat()
    try:
        raw = handlers[name](args)
        payload = json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        payload = {"ok": False, "error": str(exc)}
    return {"tool": name, "started_at": started, "ok": bool(payload.get("ok")), "result": redact(payload)}


def response_payload(step: dict[str, Any]) -> dict[str, Any]:
    res = step.get("result") or {}
    response = res.get("response")
    if isinstance(response, dict) and "response" in response and isinstance(response["response"], dict):
        return response["response"]
    if isinstance(response, dict):
        return response
    return res


def find_target(handlers: dict[str, Any], target: str) -> tuple[str | None, list[dict[str, Any]], dict[str, Any]]:
    raw = handlers["tescmd_vehicle_list"]({})
    payload = json.loads(raw)
    products = payload.get("vehicles") or payload.get("response", {}).get("response") or payload.get("response") or []
    vehicles = [p for p in products if isinstance(p, dict) and (p.get("vin") or p.get("id_s") or p.get("vehicle_id"))]
    needle = target.lower()
    matches = []
    for v in vehicles:
        hay = " ".join(str(v.get(k, "")) for k in ("display_name", "vehicle_name", "name", "model", "car_type")).lower()
        if needle in hay or "cyber" in hay:
            matches.append(v)
    chosen = matches[0] if matches else None
    identifier = None
    if chosen:
        vin = chosen.get("vin") if isinstance(chosen.get("vin"), str) else None
        identifier = vin if vin and VIN_RE.fullmatch(vin) else chosen.get("id_s") or str(chosen.get("vehicle_id") or "")
    return identifier, vehicles, redact({"vehicle_list": payload, "matches": matches})


def wait_step(seconds: float, reason: str) -> dict[str, Any]:
    time.sleep(seconds)
    return {"tool": "wait", "started_at": datetime.now(timezone.utc).isoformat(), "ok": True, "reason": reason, "seconds": seconds}


def main() -> int:
    target = os.environ.get("TESCMD_LIVE_TARGET")
    if not target:
        print(json.dumps({"ok": False, "error": "Set TESCMD_LIVE_TARGET to a vehicle display name or identifier before running live-fire tests."}))
        return 2
    out_path = Path(os.environ.get("TESCMD_LIVE_FIRE_OUT", "/tmp/tescmd-live-fire-redacted.json"))
    handlers = {spec.name: runtime.make_handler(spec) for spec in runtime.list_tool_specs()}
    report: dict[str, Any] = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "target": target,
        "suite": "low-impact + moderate functional + broad non-driving",
        "steps": [],
        "skipped": [],
        "notes": ["All side-effecting tool calls use confirm=true.", "Artifact is redacted before write."],
    }

    identifier, vehicles, target_debug = find_target(handlers, target)
    report["vehicle_count"] = len(vehicles)
    report["target_resolution"] = target_debug
    if not identifier:
        report["ok"] = False
        report["error"] = "target vehicle not found by name/cybertruck heuristic"
        out_path.write_text(json.dumps(redact(report), indent=2, sort_keys=True) + "\n")
        print(json.dumps({"ok": False, "error": report["error"], "out": str(out_path)}))
        return 2

    base = {"vin": identifier, "no_cache": True}
    side = {"vin": identifier, "confirm": True}

    # Preflight/readiness
    for name, args in [
        ("tescmd_auth_status", {}),
        ("tescmd_key_validate", {}),
        ("tescmd_vehicle_wake", side),
    ]:
        report["steps"].append(call(handlers, name, args))
        if name == "tescmd_vehicle_wake" and not report["steps"][-1]["ok"]:
            report["ok"] = False
            report["error"] = "wake failed; stopping before additional controls"
            out_path.write_text(json.dumps(redact(report), indent=2, sort_keys=True) + "\n")
            print(json.dumps({"ok": False, "error": report["error"], "out": str(out_path)}))
            return 3

    online_info_step: dict[str, Any] | None = None
    for attempt in range(1, 13):
        report["steps"].append(wait_step(10 if attempt > 1 else 3, f"wait for target wake attempt {attempt}"))
        info_step = call(handlers, "tescmd_vehicle_info", {**base, "wake": False})
        info_step["wake_poll_attempt"] = attempt
        report["steps"].append(info_step)
        if info_step["ok"]:
            online_info_step = info_step
            break

    report["steps"].append(call(handlers, "tescmd_vehicle_mobile_access", {"vin": identifier}))
    if online_info_step is None:
        report["ok"] = False
        report["error"] = "target did not come online/readable after wake polling; no vehicle controls sent after preflight"
        out_path.write_text(json.dumps(redact(report), indent=2, sort_keys=True) + "\n")
        print(json.dumps({"ok": False, "error": report["error"], "out": str(out_path)}))
        return 4

    info = response_payload(online_info_step)
    charge_state = info.get("charge_state") if isinstance(info, dict) else {}
    vehicle_state = info.get("vehicle_state") if isinstance(info, dict) else {}
    climate_state = info.get("climate_state") if isinstance(info, dict) else {}
    drive_state = info.get("drive_state") if isinstance(info, dict) else {}

    report["preflight_summary"] = redact({
        "locked": vehicle_state.get("locked") if isinstance(vehicle_state, dict) else None,
        "sentry_mode": vehicle_state.get("sentry_mode") if isinstance(vehicle_state, dict) else None,
        "is_climate_on": climate_state.get("is_climate_on") if isinstance(climate_state, dict) else None,
        "charging_state": charge_state.get("charging_state") if isinstance(charge_state, dict) else None,
        "charge_port_door_open": charge_state.get("charge_port_door_open") if isinstance(charge_state, dict) else None,
        "shift_state": drive_state.get("shift_state") if isinstance(drive_state, dict) else None,
        "latitude_present": bool(drive_state.get("latitude")) if isinstance(drive_state, dict) else False,
    })

    # Low-impact / moderate reversible controls.
    command_sequence: list[tuple[str, dict[str, Any], str]] = [
        ("tescmd_security_flash_lights", side, "low-impact visual signal"),
        ("tescmd_climate_start", side, "start climate; will stop later"),
        ("tescmd_climate_stop", side, "restore climate off after start test"),
        ("tescmd_charge_port_open", side, "open charge port; close attempted next"),
        ("tescmd_charge_port_close", side, "close charge port after open test"),
        ("tescmd_media_volume_set", {**side, "volume": 1.0}, "set low media volume"),
        ("tescmd_media_toggle_playback", side, "toggle media playback"),
        ("tescmd_media_toggle_playback", side, "toggle media playback back"),
        ("tescmd_climate_seat_heater", {**side, "seat_position": 0, "level": 1}, "driver seat heat low"),
        ("tescmd_climate_seat_heater", {**side, "seat_position": 0, "level": 0}, "driver seat heat off"),
        ("tescmd_climate_steering_wheel_heater", {**side, "enabled": True}, "steering heat on"),
        ("tescmd_climate_steering_wheel_heater", {**side, "enabled": False}, "steering heat off"),
    ]

    locked = vehicle_state.get("locked") if isinstance(vehicle_state, dict) else None
    if locked is True:
        command_sequence.extend([
            ("tescmd_security_unlock", side, "unlock from locked state; relock next"),
            ("tescmd_security_lock", side, "restore locked state"),
        ])
    elif locked is False:
        command_sequence.extend([
            ("tescmd_security_lock", side, "lock from unlocked state; unlock next"),
            ("tescmd_security_unlock", side, "restore unlocked state"),
        ])
    else:
        report["skipped"].append({"tool": "lock_unlock", "reason": "could not determine initial lock state"})

    charging_state = str(charge_state.get("charging_state", "")).lower() if isinstance(charge_state, dict) else ""
    if charging_state in {"charging", "stopped", "complete", "no power"}:
        command_sequence.extend([
            ("tescmd_charge_stop", side, "stop charging if active"),
            ("tescmd_charge_start", side, "start/resume charging if connected"),
            ("tescmd_charge_stop", side, "restore not actively charging"),
        ])
    else:
        report["skipped"].append({"tool": "tescmd_charge_start/stop", "reason": f"charging_state not safely connected: {charging_state or 'unknown'}"})

    for name, args, reason in command_sequence:
        step = call(handlers, name, args)
        step["reason"] = reason
        report["steps"].append(step)
        report["steps"].append(wait_step(1.5, f"settle after {name}"))
        if not step["ok"]:
            # Continue for Vehicle Command Protocol signer/reporting failures? Stop after first real command failure to avoid cascading unknowns.
            report["stopped_after_failure"] = name
            break

    # Final state read.
    report["steps"].append(call(handlers, "tescmd_vehicle_info", {**base, "wake": True, "confirm": True}))
    report["completed_at"] = datetime.now(timezone.utc).isoformat()
    report["ok"] = all(step.get("ok", True) for step in report["steps"] if step.get("tool") != "wait")
    redacted = redact(report)
    out_path.write_text(json.dumps(redacted, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"ok": report["ok"], "steps": len(report["steps"]), "skipped": len(report["skipped"]), "out": str(out_path), "stopped_after_failure": report.get("stopped_after_failure")}))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
