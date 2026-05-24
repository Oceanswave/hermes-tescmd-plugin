#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hermes_tescmd_plugin import config, runtime  # noqa: E402

ID_RE = re.compile(r"\b\d{8,}\b")
VIN_RE = re.compile(r"\b[A-HJ-NPR-Z0-9]{17}\b")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
TAILSCALE_RE = re.compile(r"\b[A-Za-z0-9-]+\.[A-Za-z0-9-]+\.ts\.net\b")
LOCAL_PATH_RE = re.compile(r"/(?:home|tmp|var|etc)/[^\s\"'<>]+")
LOCATION_KEYS = {
    "lat",
    "latitude",
    "lon",
    "lng",
    "longitude",
    "location",
    "location_data",
    "drive_state",
    "native_latitude",
    "native_longitude",
    "active_route_latitude",
    "active_route_longitude",
    "address",
    "formatted_address",
    "site_name",
    "installation_address",
    "home",
    "work",
}
TOKENISH_RE = re.compile(
    r"(?i)(access_token|refresh_token|client_secret|code|state|authorization|bearer)[^,}\n]*"
)


def redact_text(text: str) -> str:
    text = VIN_RE.sub("[REDACTED]", text)
    text = EMAIL_RE.sub("[REDACTED]", text)
    text = TAILSCALE_RE.sub("tesla-keyhost.example-tailnet.ts.net", text)
    text = re.sub(r"\b[0-9a-f]{40,64}\b", "[REDACTED_FINGERPRINT]", text, flags=re.I)
    text = LOCAL_PATH_RE.sub("/[PATH]", text)
    text = ID_RE.sub("[ID]", text)
    text = TOKENISH_RE.sub(
        lambda m: (
            m.group(0).split(":", 1)[0] + ":[REDACTED]"
            if ":" in m.group(0)
            else "[REDACTED]"
        ),
        text,
    )
    return text


def summarize(value: Any, depth: int = 0) -> Any:
    if depth > 3:
        return "..."
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in list(value.items())[:20]:
            out_key = redact_text(str(k)) if isinstance(k, str) else k
            lk = str(out_key).lower()
            if lk in LOCATION_KEYS or any(
                s in lk
                for s in (
                    "vin",
                    "token",
                    "secret",
                    "authorization",
                    "state",
                    "code",
                    "email",
                    "name",
                    "profile_image",
                    "vault",
                    "domain",
                    "url",
                    "uri",
                    "fingerprint",
                    "key_path",
                )
            ):
                out[out_key] = "[REDACTED]" if v else v
            elif k in {"id", "id_s", "vehicle_id", "energy_site_id", "site_id", "txid"}:
                out[out_key] = "[ID]" if v else v
            else:
                out[out_key] = summarize(v, depth + 1)
        if len(value) > 20:
            out["..."] = f"{len(value) - 20} more keys"
        return out
    if isinstance(value, list):
        return {
            "count": len(value),
            "sample": [summarize(v, depth + 1) for v in value[:2]],
        }
    if isinstance(value, str):
        if len(value) > 120:
            value = value[:120] + "..."
        return redact_text(value)
    return value


def handler(name: str):
    spec = next(s for s in runtime.list_tool_specs() if s.name == name)
    return runtime.make_handler(spec)


def call(name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    args = dict(args or {})
    t0 = time.time()
    try:
        raw = handler(name)(args)
        payload = json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        payload = {"ok": False, "error": f"exception: {type(exc).__name__}: {exc}"}
    return {
        "tool": name,
        "args_keys": sorted(args),
        "ok": bool(payload.get("ok")),
        "elapsed_ms": int((time.time() - t0) * 1000),
        "error": redact_text(str(payload.get("error", "")))[:500]
        if not payload.get("ok")
        else "",
        "summary": summarize(payload),
    }


def first_site_id(energy_payload: dict[str, Any]) -> int | None:
    def walk(x: Any):
        if isinstance(x, dict):
            if x.get("device_type") == "energy" and x.get("energy_site_id"):
                try:
                    val = int(x["energy_site_id"])
                    if val > 0:
                        return val
                except Exception:
                    pass
            for key in ("energy_site_id", "site_id"):
                if key in x:
                    try:
                        val = int(x[key])
                        if val > 0:
                            return val
                    except Exception:
                        pass
            for v in x.values():
                found = walk(v)
                if found:
                    return found
        elif isinstance(x, list):
            for v in x:
                found = walk(v)
                if found:
                    return found
        return None

    return walk(energy_payload)


def main() -> None:
    cfg = config.load_config("default")
    auto_wake = os.getenv("TESCMD_E2E_WAKE", "").lower() in {"1", "true", "yes"}
    # Tesla's telemetry_history endpoint rejects date-only values with
    # "Invalid start_date"; use RFC3339 date-times for telemetry endpoints.
    start = (datetime.now(timezone.utc) - timedelta(days=7)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    end = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    tasks: list[tuple[str, dict[str, Any]]] = []

    prereq = []
    for name, args in [
        ("tescmd_auth_status", {}),
        ("tescmd_status", {}),
        ("tescmd_help", {}),
        ("tescmd_vehicle_list", {}),
        ("tescmd_energy_list", {}),
    ]:
        r = call(name, args)
        prereq.append(r)

    # Need raw unredacted payload for site/owner selection; keep it local and only
    # write redacted summaries.
    try:
        vehicle_raw = json.loads(handler("tescmd_vehicle_list")({}))
    except Exception:
        vehicle_raw = {}
    owner_vehicle_id = None
    if isinstance(vehicle_raw, dict):
        for vehicle in vehicle_raw.get("vehicles", []):
            if (
                isinstance(vehicle, dict)
                and str(vehicle.get("access_type", "")).upper() == "OWNER"
            ):
                owner_vehicle_id = vehicle.get("id_s") or vehicle.get("vin")
                break
    if auto_wake and owner_vehicle_id:
        for _ in range(3):
            wake_result = call(
                "tescmd_vehicle_wake", {"vin": owner_vehicle_id, "confirm": True}
            )
            prereq.append(wake_result)
            if (
                wake_result["ok"]
                and "online" in json.dumps(wake_result.get("summary", {})).lower()
            ):
                break
            time.sleep(10)
    try:
        energy_raw = json.loads(handler("tescmd_energy_list")({}))
    except Exception:
        energy_raw = {}
    # Prefer a Powerwall/battery site for the history endpoints; Wall Connector
    # live/status work, but Tesla returns backend-specific history errors for
    # some wall connector sites even when the plugin is constructing the request
    # correctly.
    energy_products = (
        energy_raw.get("products", []) if isinstance(energy_raw, dict) else []
    )
    site_id = None
    for product in energy_products:
        if (
            isinstance(product, dict)
            and product.get("device_type") == "energy"
            and product.get("resource_type") == "battery"
        ):
            site_id = first_site_id({"products": [product]})
            break
    if site_id is None:
        site_id = first_site_id(energy_raw)

    status_read_args = {"no_cache": True}
    tasks.extend(
        [
            ("tescmd_key_show", {}),
            ("tescmd_key_validate", {}),
            ("tescmd_user_me", {}),
            ("tescmd_user_region", {}),
            ("tescmd_user_orders", {}),
            ("tescmd_user_features", {}),
            ("tescmd_partner_public_key", {}),
            ("tescmd_partner_telemetry_error_vins", {}),
            ("tescmd_partner_telemetry_errors", {}),
            ("tescmd_billing_history", {}),
            ("tescmd_billing_sessions", {}),
            ("tescmd_raw_get", {"confirm": True, "path": "/api/1/products"}),
            ("tescmd_vehicle_get", {}),
            ("tescmd_vehicle_info", status_read_args),
            (
                "tescmd_vehicle_status",
                {
                    **status_read_args,
                    "endpoints": [
                        "charge_state",
                        "climate_state",
                        "closures_state",
                        "drive_state",
                        "gui_settings",
                        "location_data",
                        "vehicle_config",
                        "vehicle_state",
                        "charge_schedule_data",
                        "preconditioning_schedule_data",
                    ],
                },
            ),
            ("tescmd_charge_status", status_read_args),
            ("tescmd_climate_status", status_read_args),
            ("tescmd_vehicle_location", status_read_args),
            ("tescmd_vehicle_drive_status", status_read_args),
            ("tescmd_vehicle_closures_status", status_read_args),
            ("tescmd_vehicle_config_status", status_read_args),
            ("tescmd_vehicle_gui_settings", status_read_args),
            ("tescmd_vehicle_charge_schedule_status", status_read_args),
            ("tescmd_vehicle_preconditioning_schedule_status", status_read_args),
            ("tescmd_vehicle_mobile_access", {}),
            ("tescmd_vehicle_nearby_chargers", {}),
            ("tescmd_vehicle_alerts", {}),
            (
                "tescmd_vehicle_drivers",
                {"vin": owner_vehicle_id} if owner_vehicle_id else {},
            ),
            ("tescmd_vehicle_release_notes", {}),
            ("tescmd_vehicle_service", {}),
            ("tescmd_vehicle_specs", {}),
            ("tescmd_vehicle_subscriptions", {}),
            ("tescmd_vehicle_upgrades", {}),
            ("tescmd_vehicle_options", {}),
            ("tescmd_vehicle_warranty", {}),
            ("tescmd_vehicle_enterprise_roles", {}),
            ("tescmd_vehicle_fleet_status", {}),
            ("tescmd_vehicle_telemetry_config", {}),
            ("tescmd_vehicle_telemetry_errors", {}),
            ("tescmd_security_status", status_read_args),
            ("tescmd_software_status", status_read_args),
            (
                "tescmd_sharing_list_invites",
                {"vin": owner_vehicle_id} if owner_vehicle_id else {},
            ),
            ("tescmd_cache_status", {}),
        ]
    )
    if site_id:
        tasks.extend(
            [
                ("tescmd_energy_live", {"site_id": site_id}),
                ("tescmd_energy_status", {"site_id": site_id}),
                (
                    "tescmd_energy_calendar",
                    {"site_id": site_id, "kind": "energy", "period": "day"},
                ),
                (
                    "tescmd_energy_history",
                    {"site_id": site_id, "start_date": start, "end_date": end},
                ),
                (
                    "tescmd_energy_telemetry",
                    {
                        "site_id": site_id,
                        "kind": "charge",
                        "start_date": start,
                        "end_date": end,
                    },
                ),
            ]
        )
    if cfg.google_maps_api_key:
        tasks.append(
            (
                "tescmd_navigation_place_search",
                {"query": "Tesla Fremont Factory", "limit": 1},
            )
        )

    results = prereq + [call(name, args) for name, args in tasks]
    ok = sum(1 for r in results if r["ok"])
    out = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "auto_wake": auto_wake,
        "site_id_present": bool(site_id),
        "total": len(results),
        "ok": ok,
        "failed": len(results) - ok,
        "results": results,
    }
    print(json.dumps(out, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
