# Tesla Fleet API Endpoint Coverage

This file tracks the native Hermes plugin surface against the public Tesla Fleet API endpoint pages audited for the 0.5.0a10 prerelease.

## Summary

- Default registered Hermes surface: 49 compact tools for lower agent latency; exhaustive dedicated surface: 173 tools with `TESCMD_TOOL_SURFACE=full`.
- Generated verification manifests are local artifacts only; `endpoint-tool-manifest.json` is ignored/excluded and should be regenerated during release validation when needed.
- Current documented vehicle command endpoints: 66/66 covered by dedicated command tools; the manifest contains 84 vehicle-command tool specs and 78 unique command endpoint names including upstream aliases/additions.
- Current documented vehicle REST endpoints: covered by dedicated tools, except generic future/unknown additions remain reachable through confirm-gated `tescmd_raw_get`, `tescmd_raw_post`, or `tescmd_raw_delete`.
- Current documented energy endpoints: covered by dedicated tools.
- Current documented charging endpoints: covered by dedicated tools.
- Current documented partner endpoints: covered by dedicated tools.
- Current documented user endpoints: covered by dedicated tools.
- Current live read-only E2E: 52/55 probes pass after explicit wake; remaining failures are Tesla/account authorization boundaries (`tescmd_billing_sessions`, `tescmd_vehicle_specs`, `tescmd_vehicle_enterprise_roles`).
- Current guarded live-fire E2E: passed on the selected Cybertruck target after Tesla app virtual-key enrollment. Confirmed signed-command transport and non-driving controls: flash lights, climate start/stop, charge-port open/close, media volume, media playback toggle/restore, driver seat heat on/off, and steering-wheel heat on/off. Lock/unlock and charge start/stop were skipped by state safety rules.
- Vehicle-data sections now have dedicated convenience tools as well as the generic `tescmd_vehicle_status(endpoints=[...])` wrapper.

## Vehicle-data section convenience tools

These are all read-only but can wake the car only when called with `wake: true` and `confirm: true`.

- `tescmd_charge_status` -> `vehicle_data?endpoints=charge_state`
- `tescmd_climate_status` -> `vehicle_data?endpoints=climate_state`
- `tescmd_vehicle_drive_status` -> `vehicle_data?endpoints=drive_state`
- `tescmd_vehicle_location` -> `vehicle_data?endpoints=location_data` with `drive_state` alias handling
- `tescmd_vehicle_closures_status` -> `vehicle_data?endpoints=closures_state`
- `tescmd_vehicle_config_status` -> `vehicle_data?endpoints=vehicle_config`
- `tescmd_vehicle_gui_settings` -> `vehicle_data?endpoints=gui_settings`
- `tescmd_vehicle_charge_schedule_status` -> `vehicle_data?endpoints=charge_schedule_data`
- `tescmd_vehicle_preconditioning_schedule_status` -> `vehicle_data?endpoints=preconditioning_schedule_data`
- `tescmd_security_status` -> `vehicle_data?endpoints=vehicle_state`
- `tescmd_software_status` -> `vehicle_data?endpoints=vehicle_state`

The lower-level `tescmd_vehicle_status` remains available for arbitrary Tesla-supported endpoint combinations.

## Live E2E coverage

The wake-enabled read-only audit is:

```bash
TESCMD_E2E_WAKE=true scripts/e2e_readonly_audit.py > e2e-readonly-redacted.json
```

Latest redacted run:

- total probes: 55
- successful probes: 52
- failed probes: 3
- explicit wake used: yes
- all six newly-added vehicle-data section tools: passed
- VIN/API-key leakage in redacted output: none detected

The three remaining failures are account/product authorization boundaries observed from Tesla responses, not missing plugin endpoints:

- business-only charging sessions
- partner `vehicle_specs` scope not granted to the app's partner token
- `enterprise_management` grant missing for enterprise roles

## Side-effect coverage policy

Vehicle commands, sharing mutations, raw POST/DELETE, key/auth destructive actions, cache clearing, telemetry config mutation, enterprise payer mutation, and energy mutations are not executed in live E2E without explicit user intent. They are still included as native tools and remain handler/schema confirm-gated. The final safety regression checks all 112 confirm-required tools and verifies they make zero HTTP calls when `confirm` is omitted.
