from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from hermes_tescmd_plugin import runtime
from hermes_tescmd_plugin.dashboard import ensure_dashboard_installed

router = APIRouter()

_QUICK_ACTION_TO_TOOL = {
    "wake": "tescmd_vehicle_wake",
    "flash": "tescmd_security_flash_lights",
    "honk": "tescmd_security_honk_horn",
    "lock": "tescmd_security_lock",
    "charge-start": "tescmd_charge_start",
    "charge-stop": "tescmd_charge_stop",
    "charge-port-open": "tescmd_charge_port_open",
    "charge-port-close": "tescmd_charge_port_close",
    "climate-start": "tescmd_climate_start",
    "climate-stop": "tescmd_climate_stop",
}

_READ_TOOLS = {
    "status": "tescmd_status",
    "vehicles": "tescmd_vehicle_list",
    "vehicle-status": "tescmd_vehicle_status",
    "charge": "tescmd_charge_status",
    "climate": "tescmd_climate_status",
    "location": "tescmd_vehicle_location",
}


def _specs() -> dict[str, runtime.ToolSpec]:
    return {spec.name: spec for spec in runtime.list_tool_specs()}


def _run(tool_name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    spec = _specs().get(tool_name)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"Unknown tescmd tool: {tool_name}")
    payload = runtime.make_handler(spec)(args or {})
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail="tescmd tool returned non-JSON output") from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=502, detail="tescmd tool returned an unexpected payload")
    return data


class QuickActionBody(BaseModel):
    action: str = Field(..., description="Quick action key, e.g. flash, honk, wake, climate-start.")
    vin: str | None = None
    profile: str = "default"
    region: str | None = None
    confirm: bool = False


@router.get("/install")
def install_assets() -> dict[str, Any]:
    return ensure_dashboard_installed()


@router.get("/tools")
def tools() -> dict[str, Any]:
    return {
        "ok": True,
        "reads": _READ_TOOLS,
        "quick_actions": _QUICK_ACTION_TO_TOOL,
        "safety": "Quick actions are physical side effects and require confirm=true.",
    }


@router.get("/status")
def status(profile: str = "default") -> dict[str, Any]:
    return _run("tescmd_status", {"profile": profile})


@router.get("/vehicles")
def vehicles(profile: str = "default", region: str | None = None) -> dict[str, Any]:
    args: dict[str, Any] = {"profile": profile}
    if region:
        args["region"] = region
    return _run("tescmd_vehicle_list", args)


@router.get("/vehicle")
def vehicle(
    vin: str | None = None,
    profile: str = "default",
    region: str | None = None,
    endpoints: str | None = Query(None, description="Comma-separated vehicle_data endpoints."),
    wake: bool = False,
    confirm: bool = False,
) -> dict[str, Any]:
    args: dict[str, Any] = {"profile": profile, "wake": wake, "confirm": confirm}
    if vin:
        args["vin"] = vin
    if region:
        args["region"] = region
    if endpoints:
        args["endpoints"] = [part.strip() for part in endpoints.split(",") if part.strip()]
    return _run("tescmd_vehicle_status", args)


@router.get("/read/{read_key}")
def read(read_key: str, vin: str | None = None, profile: str = "default", region: str | None = None) -> dict[str, Any]:
    tool_name = _READ_TOOLS.get(read_key)
    if not tool_name:
        raise HTTPException(status_code=404, detail=f"Unknown read key: {read_key}")
    args: dict[str, Any] = {"profile": profile}
    if vin:
        args["vin"] = vin
    if region:
        args["region"] = region
    return _run(tool_name, args)


@router.post("/quick-action")
def quick_action(body: QuickActionBody) -> dict[str, Any]:
    tool_name = _QUICK_ACTION_TO_TOOL.get(body.action)
    if not tool_name:
        raise HTTPException(status_code=404, detail=f"Unknown quick action: {body.action}")
    args: dict[str, Any] = {"profile": body.profile, "confirm": bool(body.confirm)}
    if body.vin:
        args["vin"] = body.vin
    if body.region:
        args["region"] = body.region
    return _run(tool_name, args)
