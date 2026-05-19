---
name: tescmd-operator
description: Use the native hermes-tescmd-plugin tools for Tesla OAuth, readiness checks, vehicle state, navigation, and Fleet API commands without relying on the upstream tescmd CLI.
version: 0.5.0a22
---

# tescmd Operator

This plugin is a **native Hermes Tesla plugin**.

It does not shell out to or depend on the upstream `tescmd` CLI at runtime.

## Preferred usage

1. Do Tesla Developer app creation/callback/scope setup outside Hermes, following `docs/ONBOARDING.md` and the README. Tesla app callback URLs must be public HTTPS URLs; configure `domain` for the default `https://<domain>/callback` or set `oauth_redirect_uri` explicitly. Then edit `HERMES_HOME/plugins/hermes-tescmd-plugin/config.json` with the app values; there is intentionally no `tescmd_setup` tool.
2. Use `tescmd_auth_login` to start OAuth, then `tescmd_auth_complete` to finish it.
3. Use `tescmd_onboarding_status` for read-only setup guidance: current phase, missing prerequisites, next tool, docs anchor, and readiness booleans. Use `tescmd_auth_status` whenever you need to confirm profile state, token status, region, or stored key paths.
4. Use the dedicated operational tools for normal work:
   - `tescmd_status`
   - `tescmd_vehicle_*`
   - `tescmd_charge_*`
   - `tescmd_climate_*`
   - `tescmd_security_*`
   - `tescmd_energy_*`
   - `tescmd_sharing_*`
   - `tescmd_user_*`
5. Use `tescmd_key_*` tools for plugin-owned vehicle-command key generation, validation, enrollment prep, and deployment prep. Key generation/deploy and auth mutation tools require `confirm: true`.
6. Use `tescmd_raw_get` / `tescmd_raw_post` / `tescmd_raw_delete` only as escape hatches when the dedicated native tool surface is not enough; raw tools require `confirm: true` and only accept relative `/api/...` paths.
7. Treat `tescmd_auth_export` as a sensitive file-export operation: it requires `confirm: true`, writes a `0600` file, and does not return token values in tool output.
8. Use `tescmd_cache_status` / `tescmd_cache_clear` for the plugin-native response cache. The cache is local plugin state and may contain sensitive vehicle telemetry/location snapshots.
9. Use `tescmd_audit_log` to inspect recent redacted side-effect command and wake-attempt audit events; the backing JSONL file lives under `HERMES_HOME/plugins/hermes-tescmd-plugin/audit/commands.jsonl`.
10. Pass `vin` only when you want to override the configured default vehicle identifier.
11. Set `wake: true` only on status-style read tools that expose it, and only when the user really wants to wake a sleeping vehicle.
12. Treat `tescmd_serve`, `tescmd_openclaw_bridge`, and `tescmd_vehicle_telemetry_stream` as compatibility/info tools rather than long-running daemons started inside Hermes. There is no MCP server mode; Hermes loads this as a native plugin.

## Parity notes

- The native plugin covers the upstream command surface by capability, but not by identical CLI naming or process model.
- Expect some normalized Hermes names, for example:
  - upstream `nav *` → `tescmd_navigation_*`
  - upstream `trunk *` → `tescmd_vehicle_*` helpers
  - upstream `charge precondition-*` → native `tescmd_precondition_*`
  - upstream `vehicle telemetry *` → `tescmd_vehicle_telemetry_*`
- The plugin adds Hermes-native auth/status/help helpers such as `tescmd_auth_complete`, `tescmd_onboarding_status`, `tescmd_status`, and `tescmd_help`; configuration is docs-only via config.json, not a tool.
- `tescmd_serve`, `tescmd_openclaw_bridge`, and `tescmd_vehicle_telemetry_stream` are compatibility/guidance tools, not terminal dashboards or daemon launchers. MCP server mode is intentionally absent because Hermes loads the package natively.

## Admin vs operational usage

Treat these as **admin/bootstrap** tools:
- `tescmd_status`
- `tescmd_onboarding_status`
- `tescmd_auth_*`
- `tescmd_key_*`
- partner registration / partner-account inspection tools

Treat these as **normal operational** tools:
- `tescmd_vehicle_*` except `tescmd_vehicle_telemetry_stream`
- `tescmd_charge_*`
- `tescmd_climate_*`
- `tescmd_security_*`
- `tescmd_media_*`
- `tescmd_navigation_*`
- `tescmd_energy_*`
- `tescmd_sharing_*`
- `tescmd_user_*` for account reads

Use `tescmd_raw_get` / `tescmd_raw_post` / `tescmd_raw_delete` only as advanced escape hatches.

## Auth and bootstrap model

- Credentials and tokens are owned by the plugin.
- Auth state is stored under `HERMES_HOME/plugins/hermes-tescmd-plugin/`.
- `tescmd_auth_register` performs Tesla partner registration directly through the Fleet API.
- Browser authorization uses `https://auth.tesla.com/oauth2/v3/authorize`; token exchange, refresh, and partner tokens use Tesla's Fleet Auth token endpoint at `https://fleet-auth.prd.vn.cloud.tesla.com/oauth2/v3/token` with the selected Fleet API audience.
- `tescmd_key_generate` generates a P-256 vehicle-command keypair; `tescmd_key_show`/`tescmd_status` return the Tesla enrollment URL when a domain is configured.
- The stateful setup wizard, `tescmd_setup` config mutation tool, Tailscale hosting automation, and GitHub Pages hosting automation are intentionally absent. Keep Tesla Developer app setup, config-file editing, domain hosting, and virtual-key enrollment as explicit operator-managed steps documented in `docs/ONBOARDING.md` and the README.
- `tescmd_key_deploy` only supports `method="local"`; it prepares static public-key files to host externally and does not publish them on its own.
- Tailscale Funnel is documented only as an operator-managed external hosting recipe for both public-key hosting and the public OAuth callback path. If using it, use an example-style hostname such as `tesla-keyhost.example-tailnet.ts.net` in docs and store the real hostname only in local plugin config. For Tesla Developer fields, use `https://<domain>` for Allowed Origin URL(s), `https://<domain>/callback` for Allowed Redirect URI(s), and leave Allowed Returned URL(s) blank unless required; if required, use `https://<domain>`. Do not put the `.well-known` public-key URL in those fields.
- After hosting the public key on your own HTTPS domain, use `tescmd_key_validate` to verify the remote key fingerprint matches the local key before enrollment.

## Current transport scope

- The plugin directly uses Tesla OAuth and Fleet REST APIs.
- For commands whose native specs require signing, the current implementation also uses the signed-command session transport when a vehicle-command key is configured.
- Signed-command sessions are concurrency guarded, key-rotation aware, require verified session-info HMAC tags, and fail closed on non-OK vehicle operation statuses.
- Known commands that require Vehicle Command Protocol signing fail before network I/O if no plugin-owned vehicle-command key is configured; only commands explicitly supported by Tesla over unsigned REST use standard Fleet REST command endpoints.

## Safety notes

- Vehicle-control commands can have real-world effects.
- Prefer read tools before write tools when diagnosing vehicle state.
- Side-effecting operations require `confirm: true` before any network call or sensitive file write. This includes vehicle command tools, raw POST, sharing mutations, energy mutations, telemetry config changes, and auth export.
- Domains must be hostnames only; do not pass schemes, paths, ports, localhost, or private IPs for Tesla public-key hosting.
- Preserve user intent around waking the car and other billable or side-effecting actions.
- Login/bootstrap steps may require browser- or human-driven interaction.
- Error payloads redact token/secret fields, but still avoid pasting exported auth files or blobs into chat unless explicitly needed.
- Side-effecting vehicle commands, explicit `tescmd_vehicle_wake`, and read calls using `wake=true` append redacted audit events to `audit/commands.jsonl` and emit the same redacted metadata through Hermes' standard logger for `agent.log` visibility; full VINs, precise navigation/location inputs, tokens, PINs, and secrets are not written.

## Agentic routing quick guide

Start with `tescmd_help`, `tescmd_onboarding_status`, or `tescmd_status` when unsure. Use `tescmd_onboarding_status` for setup phase guidance and `tescmd_status.bootstrap` readiness booleans before choosing tools:

- Vehicle/account reads: `tescmd_vehicle_list`, `tescmd_vehicle_location`, `tescmd_charge_status`.
- Side effects: only call command tools with `confirm=true` after explicit user intent.
- Wake: `tescmd_vehicle_wake` and read calls with `wake=true` require `confirm=true`.
- One destination: `tescmd_navigation_send(destination, confirm=true)`.
- Known GPS point: `tescmd_navigation_gps(lat, lon, order?, confirm=true)`.
- Multi-stop route: resolve Google Place IDs first, then `tescmd_navigation_waypoints(place_ids=[...], confirm=true)`.
- Address/place-name to Place ID: configure `google_maps_api_key` in config.json, then call the advertised helper `tescmd_navigation_place_search`; never invent Place IDs.
- Partner/business-only scopes (`vehicle_specs`, `vehicle_pricing_info`, `enterprise_management`) are intentionally excluded from third-party customer OAuth and reported separately as `partner_only_scopes`; use them only with partner/business-token flows.

