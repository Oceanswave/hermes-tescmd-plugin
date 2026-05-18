# hermes-tescmd-plugin

A **native Hermes plugin** for Tesla Fleet API operations.

This package no longer shells out to, imports, or depends on the upstream `tescmd` CLI at runtime. It implements plugin-owned configuration, OAuth token storage, and direct Fleet API calls inside the Hermes plugin itself. Tesla Developer app creation, OAuth prerequisite setup, domain hosting, and vehicle virtual-key enrollment remain explicit operator-managed steps documented below rather than a plugin-run wizard.

## What this plugin is

- a pip-installable Hermes plugin discovered via `hermes_agent.plugins`
- a native Tesla OAuth + Fleet API integration
- a plugin-owned credential/config store rooted in `HERMES_HOME`
- a static Hermes tool catalog designed for Tesla tasks

## What this plugin is not

- not a wrapper around the `tescmd` CLI
- not a subprocess launcher for another tool
- not a second package that requires `tescmd` to be installed
- not a Textual dashboard, telemetry daemon, or MCP/bridge server process manager inside Hermes

## Current tool surface

The native runtime currently registers the complete **173-tool Hermes surface** by default. Tool-load minimization is intentionally not used; command-dispatch latency should be optimized in the handlers/client path without hiding dedicated Tesla operations from Hermes.

The surface is grouped roughly as:

- setup/config mutation: 0 tools (configuration is docs-only via `config.json`)
- status: 1 tool
- auth: 8 tools
- key: 6 tools
- user: 4 tools
- billing: 3 tools
- energy: 12 tools
- partner: 3 tools
- vehicle: 41 tools
- charge: 17 tools
- precondition schedules: 3 tools
- climate: 15 tools
- security: 21 tools
- sharing: 6 tools
- media: 8 tools
- navigation: 6 tools
- software: 3 tools
- power: 2 tools
- raw escape hatches: 3 tools
- response cache controls: 2 tools
- plugin-native compatibility/info tools for serve/OpenClaw workflows: 2 tools
- telemetry guidance: 1 tool (`tescmd_vehicle_telemetry_stream`, still vehicle-prefixed for API compatibility)

Representative examples:

- auth/status: `tescmd_status`, `tescmd_auth_login`, `tescmd_auth_complete`, `tescmd_auth_logout`
- key/bootstrap: `tescmd_key_generate`, `tescmd_key_validate`, `tescmd_key_enroll`, `tescmd_key_deploy`
- account/partner/billing: `tescmd_user_me`, `tescmd_partner_public_key`, `tescmd_billing_history`
- vehicle: `tescmd_vehicle_list`, `tescmd_vehicle_get`, `tescmd_vehicle_info`, `tescmd_vehicle_location`, `tescmd_vehicle_release_notes`
- charging/climate/security: `tescmd_charge_limit`, `tescmd_climate_start`, `tescmd_security_lock`, `tescmd_security_status`
- energy/sharing: `tescmd_energy_live`, `tescmd_energy_mode`, `tescmd_sharing_add_driver`, `tescmd_sharing_list_invites`
- navigation/place lookup: `tescmd_navigation_place_search`, `tescmd_navigation_waypoints`, `tescmd_navigation_waypoints_raw`
- raw/cache/compatibility: `tescmd_raw_get`, `tescmd_raw_post`, `tescmd_raw_delete`, `tescmd_cache_status`, `tescmd_cache_clear`, `tescmd_serve`, `tescmd_openclaw_bridge`, `tescmd_vehicle_telemetry_stream`

For the canonical source of truth, inspect `src/hermes_tescmd_plugin/runtime.py`, which owns the static native tool catalog.

## Upstream `tescmd` parity notes

A mechanical audit against the upstream `tescmd` Click command tree currently shows **155 upstream leaf commands**.

The native Hermes plugin intentionally exposes **173 tools** instead of matching that number exactly, because Hermes-native packaging splits or renames a few flows:

- plugin configuration is intentionally docs-only through `HERMES_HOME/plugins/hermes-tescmd-plugin/config.json`; no `tescmd_setup` or setup wizard is exposed
- browser callback completion is explicit via `tescmd_auth_complete`
- upstream `vehicle low-power` / `vehicle accessory-power` also have `tescmd_power_*` aliases for grouped power controls
- upstream `charge precondition-*` maps to the native `tescmd_precondition_*` family
- some names are normalized for clearer Hermes grouping, such as `nav *` → `tescmd_navigation_*`, `trunk *` helpers under `tescmd_vehicle_*`, and `vehicle telemetry *` under `tescmd_vehicle_telemetry_*`

Intentional non-parity areas are documented rather than hidden:

- the native plugin does not launch the upstream Textual dashboard, MCP server, OpenClaw bridge, or any public-key hosting service as a long-running subprocess inside Hermes
- MCP server mode is intentionally not exposed; Hermes discovers this package as a native plugin through the `hermes_agent.plugins` entry point
- `tescmd_serve`, `tescmd_openclaw_bridge`, and `tescmd_vehicle_telemetry_stream` are compatibility/info tools only
- GitHub Pages and Tailscale hosting automation are intentionally not implemented; use manual HTTPS hosting for the Tesla public key

## Installation

See `INSTALL.md` for full install, editable-development, config, verification, TestPyPI/prerelease, and uninstall procedures. See `docs/ONBOARDING.md` for the guided OAuth + virtual-key enrollment flow and live-control proof checklist. Quick examples:

### From local source

```bash
pip install /path/to/hermes-tescmd-plugin
```

For this machine:

```bash
pip install ~/hermes-tescmd-plugin
```

### From a built wheel

```bash
pip install dist/hermes_tescmd_plugin-*.whl
```

After installation, restart Hermes so it reloads plugin entry points.

## Requirements

- Python 3.11+
- Hermes with plugin support enabled
- Tesla Fleet application credentials

## Plugin-owned state and config

This plugin intentionally uses plugin-owned state/config separate from Hermes Agent `config.yaml`. Hermes `config.yaml` remains for Hermes model/provider/tool/gateway/profile settings; Tesla app IDs, Fleet region, OAuth tokens, vehicle-command keys, cached vehicle state, and optional Google Places credentials belong to this integration and are stored under the plugin namespace. This is the recommended pattern for native pip-installable Hermes plugins with integration-specific secrets and mutable state.

The plugin stores its own state under:

```text
$HERMES_HOME/plugins/hermes-tescmd-plugin/
```

Files include:

- `config.json` — per-profile Tesla app configuration
- `auth.json` — per-profile OAuth token state
- `pending-auth.json` — in-progress PKCE login state
- `response-cache.json` — small profile-scoped cache for selected read-only Fleet API responses; this is local `0600` plugin state and may contain sensitive vehicle telemetry/location snapshots, so clear it with `tescmd_cache_clear` or delete it if you no longer want cached Tesla data on disk
- `keys/<profile>/vehicle-command-key.pem` — generated private vehicle-command key
- `keys/<profile>/vehicle-command-key.public.pem` — generated public vehicle-command key
- `hosting/<profile>/...` — local hosting tree prepared by `tescmd_key_deploy(method="local")`

No mutable auth/config is stored inside `site-packages`, and the plugin source does not need to live inside the Hermes Agent repository. For local development, this checkout can remain standalone (for example `~/hermes-tescmd-plugin`) and be editable-installed into the Hermes venv via the `hermes_agent.plugins` entry point.

## Recommended first-time configuration flow

These are **admin/bootstrap** steps, not normal day-to-day vehicle operation. They are intentionally explicit and operator-managed. The plugin does not expose a setup/config mutation tool or stateful setup wizard; edit `config.json` following this documentation, then use operational/auth/key tools.

### 1. Register your Tesla Developer app outside Hermes

In Tesla Developer Portal, create/configure your Fleet API application yourself. Tesla's app settings currently ask for these URL fields:

```text
Allowed Origin URL(s): https://<your-domain>
Allowed Redirect URI(s): https://<your-domain>/callback
Allowed Returned URL(s) (Optional): leave blank unless Tesla requires it; if required, use https://<your-domain>
```

For the example config below, that means:

```text
Allowed Origin URL(s): https://cars.example.com
Allowed Redirect URI(s): https://cars.example.com/callback
Allowed Returned URL(s) (Optional): leave blank unless Tesla requires it; if required, use https://cars.example.com
```

Do not put the `.well-known` public-key URL in those three fields. Tesla discovers the public key from the application domain at the standard path.

If `domain` is set, the plugin defaults the OAuth callback to `https://<your-domain>/callback`. You can override that with `oauth_redirect_uri` in `config.json`, for example `https://auth.example.com/tesla/callback`.

Request the scopes you need. For vehicle commands, include at least:

```text
openid offline_access vehicle_device_data vehicle_cmds
```

Tesla also exposes partner/business-only scopes such as `vehicle_specs`, `vehicle_pricing_info`, and `enterprise_management`. You may keep those in `config.json` for partner-token flows, but `tescmd_auth_login` intentionally omits them from the third-party customer OAuth URL because Tesla does not grant them to user tokens.

Keep your Tesla app `client_id` and optional `client_secret` in a password manager. The plugin stores them only under its plugin-owned state when you choose to save them with `config.json`.

### 2. Save plugin config in `config.json`

Create or edit `$HERMES_HOME/plugins/hermes-tescmd-plugin/config.json` once you have your Tesla app values. Configuration is documentation-only; there is intentionally no `tescmd_setup` tool.

Minimal single-profile example:

```json
{
  "default": {
    "profile": "default",
    "client_id": "YOUR_TESLA_CLIENT_ID",
    "client_secret": "YOUR_TESLA_CLIENT_SECRET_IF_USED",
    "region": "na",
    "domain": "cars.example.com",
    "oauth_redirect_uri": "https://cars.example.com/callback",
    "default_vin": "OPTIONAL_DEFAULT_VIN",
    "google_maps_api_key": "OPTIONAL_GOOGLE_MAPS_PLACES_KEY",
    "scopes": [
      "openid",
      "offline_access",
      "vehicle_device_data",
      "vehicle_cmds",
      "vehicle_charging_cmds",
      "vehicle_location",
      "energy_device_data",
      "energy_cmds",
      "user_data"
    ]
  }
}
```

Set at least:

- `client_id`
- `region`
- `client_secret` if your Tesla app uses confidential-client flows or you plan to run partner registration
- `domain` if you plan to register a partner account, enroll a vehicle-command key, or use the default `https://<domain>/callback` OAuth redirect
- optional `oauth_redirect_uri` if the public OAuth callback should differ from `https://<domain>/callback`
- optional `default_vin`
- optional `google_maps_api_key` for `tescmd_navigation_place_search`

Then run `tescmd_status` to see the computed public `redirect_uri`, structured bootstrap readiness stages, `next_action`, ordered `next_steps`, and key/enrollment URLs when a domain and vehicle-command key are present.

### 3. Start login

Run `tescmd_auth_login`.

If the plugin does not yet know your `client_id`, it will point you to this README configuration flow and show the expected public callback URL plus the required Tesla OAuth scopes.

The plugin returns:

- `auth_url`
- `state`
- `redirect_uri`
- requested `scopes`
- `partner_only_scopes` that were kept out of the third-party OAuth URL

Open the returned `auth_url` in a browser and complete Tesla login/consent. Tesla will redirect to the public callback URL; the local static host may show a 404, which is fine as long as the browser address bar contains `code` and `state`. Copy that full redirected URL into `tescmd_auth_complete`.

### 4. Complete login

Run `tescmd_auth_complete` with either:

- `callback_url`
- or `code` + `state`

The plugin exchanges the code for tokens and stores them under the selected profile.

### 5. Optional partner registration

Run `tescmd_auth_register` after configuring:

- `client_id`
- `client_secret`
- `domain`
- `region`

That performs Tesla partner registration against `POST /api/1/partner_accounts`.

### 6. Manual public-key hosting

Use `tescmd_key_generate` if you need signed vehicle commands. Then run `tescmd_key_deploy` with the only supported method:

- `local` — prepare a static hosting tree under `HERMES_HOME/plugins/hermes-tescmd-plugin/hosting/<profile>/`

`tescmd_key_deploy(method="local")` does **not** publish anything. Upload or serve the generated tree from your own HTTPS domain root so Tesla can read:

```text
https://<your-domain>/.well-known/appspecific/com.tesla.3p.public-key.pem
```

Then run `tescmd_key_validate` to confirm the hosted key is reachable and matches the plugin's local public key, and `tescmd_key_enroll` for the Tesla enrollment URL.

#### Example: operator-managed Tailscale Funnel hosting

Tailscale Funnel is a convenient operator-managed way to make the generated public key reachable during Tesla Developer app registration. This is intentionally documented as an external hosting option, not implemented as a plugin setup or hosting tool. Replace the example hostname and port with your own values.

Example values used below:

```text
Tailscale Funnel hostname: tesla-keyhost.example-tailnet.ts.net
Local static host port: 8766
Plugin profile: default
```

1. Put the Funnel hostname in plugin config as a hostname only:

```json
{
  "profile": "default",
  "domain": "tesla-keyhost.example-tailnet.ts.net"
}
```

2. Generate and prepare the public-key hosting tree:

```text
tescmd_key_generate({"confirm": true})
tescmd_key_deploy({"method": "local", "confirm": true})
```

The generated hosting root is:

```text
$HERMES_HOME/plugins/hermes-tescmd-plugin/hosting/default/
```

3. Serve that directory locally. For a durable user service, create `~/.config/systemd/user/hermes-tescmd-key-host.service`:

```ini
[Unit]
Description=Hermes Tesla Fleet plugin public-key host for Tailscale Funnel
After=network-online.target

[Service]
Type=simple
WorkingDirectory=%h/.hermes/plugins/hermes-tescmd-plugin/hosting/default
ExecStart=/usr/bin/python3 -m http.server 8766 --bind 127.0.0.1
Restart=on-failure
RestartSec=2

[Install]
WantedBy=default.target
```

Create an optional extensionless static callback placeholder so the public OAuth callback path returns a human-readable page without redirecting `/callback` to `/callback/`:

```bash
printf '%s\n' \
  '<!doctype html><title>Tesla OAuth callback</title><p>Copy the full browser URL, including code and state, into tescmd_auth_complete.</p>' \
  > "$HERMES_HOME/plugins/hermes-tescmd-plugin/hosting/default/callback"
```

Enable it:

```bash
systemctl --user daemon-reload
systemctl --user enable --now hermes-tescmd-key-host.service
```

4. Expose the local service with Funnel:

```bash
tailscale funnel --bg --yes 8766
tailscale funnel status
```

5. Verify the public URL before using it in Tesla Developer / virtual-key enrollment:

```bash
curl -fsS \
  https://tesla-keyhost.example-tailnet.ts.net/.well-known/appspecific/com.tesla.3p.public-key.pem
```

Then run:

```text
tescmd_key_validate({})
tescmd_key_enroll({})
```

Tesla-facing values for this example would be:

```text
Domain: tesla-keyhost.example-tailnet.ts.net
Public key URL: https://tesla-keyhost.example-tailnet.ts.net/.well-known/appspecific/com.tesla.3p.public-key.pem
Enrollment URL: https://tesla.com/_ak/tesla-keyhost.example-tailnet.ts.net
OAuth callback URL: https://tesla-keyhost.example-tailnet.ts.net/callback
```

Tesla Developer dashboard field mapping for this Tailscale-backed setup:

```text
Allowed Origin URL(s): https://tesla-keyhost.example-tailnet.ts.net
Allowed Redirect URI(s): https://tesla-keyhost.example-tailnet.ts.net/callback
Allowed Returned URL(s) (Optional): leave blank unless Tesla requires it; if required, use https://tesla-keyhost.example-tailnet.ts.net
```

Notes:

- `Allowed Origin URL(s)` is an origin, so include `https://` but do not include a path.
- `Allowed Redirect URI(s)` must match the plugin OAuth redirect URI exactly.
- `Allowed Returned URL(s)` is optional for this plugin's OAuth flow. Leave it empty when Tesla allows that. If the dashboard requires at least one value, use the same public origin, not the `.well-known` public-key URL.
- Do not put the public-key URL in any of those three fields. Tesla discovers the public key from the application domain at the standard `.well-known` path.

To disable the example Funnel later:

```bash
tailscale funnel --https=443 off
systemctl --user disable --now hermes-tescmd-key-host.service
```

## Shared operational parameters

After bootstrap is done, normal daily use should mostly stay inside the operational tool families (`vehicle_*`, `charge_*`, `climate_*`, `security_*`, `media_*`, `navigation_*`, `energy_*`, `sharing_*`).

Operational tools commonly accept:

- `vin`
- `profile`
- `region`
- `wake`
- `confirm`
- `no_cache`
- `units`

Notes:
- `vin` falls back to the configured `default_vin`
- `wake` wakes the vehicle before some read operations
- `region` can override the configured profile region for a single call
- `confirm: true` is required before side-effecting operations run. Vehicle command tools, raw POSTs, sharing mutations, energy-site mutations, telemetry config changes, and sensitive file exports all fail before any network/file side effect when confirmation is missing.
- raw Fleet API paths are constrained to relative `/api/...` paths; absolute URLs, parent traversal, and NUL bytes are rejected.
- configured domains must be hostnames only, not full URLs. Tesla virtual-key hosting expects a public HTTPS hostname without scheme/path/port.
- the plugin maintains a small profile-scoped response cache for selected read-only vehicle status calls; use `no_cache: true` to bypass cache reads and avoid writing that fresh response back to the cache, and `tescmd_cache_clear` to clear cached entries
- `units` remains a formatting hint for callers; this plugin does not implement the upstream CLI's full unit-formatting engine

## CLI-compatibility tools vs native plugin behavior

Upstream `tescmd` includes CLI-first workflows such as the Textual dashboard, telemetry daemon, MCP server, OpenClaw bridge, and cache inspection commands.

In this native Hermes plugin:
- there is no `tescmd_mcp_serve` tool; Hermes plugin entry-point discovery is the integration mechanism
- `tescmd_serve`, `tescmd_openclaw_bridge`, and `tescmd_vehicle_telemetry_stream` are compatibility/info tools
- `tescmd_cache_status` and `tescmd_cache_clear` operate on the plugin-native response cache
- none of these launch or manage upstream long-running terminal applications inside Hermes

## Native auth model

This plugin owns its Tesla auth flow directly.

It implements:

- OAuth 2.0 Authorization Code + PKCE login start/completion
- Tesla's documented split auth hosts: `https://auth.tesla.com/oauth2/v3/authorize` for browser authorization and `https://fleet-auth.prd.vn.cloud.tesla.com/oauth2/v3/token` for token exchange/refresh/partner tokens
- Fleet API audience handling using the selected regional base URL
- refresh-token handling
- token import/export
- profile-scoped token persistence under `HERMES_HOME`
- partner registration via client credentials

`tescmd_auth_export` now requires `confirm: true` and writes token material to a `0600` file under the plugin export directory by default. It does not return bearer/refresh token values in Hermes tool output. Treat the file path and exported file as secrets.

Pending OAuth completions expire after ten minutes and callback URLs must match the redirect URI generated by `tescmd_auth_login`.

It does **not** delegate auth or token storage to `tescmd`.

## Notes on vehicle-command keys and signed commands

`tescmd_key_generate` generates a Tesla-compatible P-256 vehicle-command keypair. `tescmd_status` and `tescmd_key_show` return the enrollment URL when a domain and key are configured:

```text
https://tesla.com/_ak/<your-domain>
```

That is useful bootstrap material for Tesla vehicle-command enrollment.

Current scope includes native signed-command transport/session support for the implemented command set when a vehicle-command key is configured. Known Tesla commands that require Vehicle Command Protocol signing fail before network I/O if no plugin-owned vehicle-command key is configured, rather than silently falling back to legacy REST command endpoints. Commands explicitly marked unsigned still use the standard Fleet REST command endpoints where Tesla allows it.

Signed-command hardening notes:

- session managers are keyed by profile/region/private-key path and key mtime, and access is locked for concurrent Hermes tool invocations
- handshake responses must include a valid session-info HMAC tag
- command responses with non-OK/non-WAIT operation status or a signed-message fault fail closed and invalidate stale sessions
- vehicle-command keys are written with `0600` private-key permissions and are not overwritten unless `force: true` is supplied

## Development

### Run tests

```bash
pytest -q
```

### Build distributions

```bash
python -m build --sdist --wheel
```

## Safety

These tools can have real-world effects:

- waking a vehicle
- starting or stopping charging
- starting climate control
- locking or unlocking doors

Use the same care you would use with any Tesla control surface.

Production guardrails in this POC:

- high-risk commands fail before any network call unless `confirm: true` is present
- `tescmd_raw_post` requires `confirm: true`
- raw Fleet API paths must be relative `/api/...` paths, never absolute URLs or traversal paths
- tool error payloads redact token/secret fields before returning JSON to Hermes

## Google Maps / Places for multi-stop navigation

Tesla's multi-waypoint navigation command expects Google Maps Place IDs encoded as `refId:<PLACE_ID>,refId:<PLACE_ID>`. The plugin does not need a Google key when you already have Place IDs. If you want Hermes to resolve addresses or place names into Place IDs, configure a Google Maps Platform API key with Places API enabled:

```text
Edit $HERMES_HOME/plugins/hermes-tescmd-plugin/config.json and set google_maps_api_key.
```

Then use `tescmd_navigation_place_search` to find candidate Place IDs, choose the intended candidate, and call `tescmd_navigation_waypoints({"place_ids": ["..."], "confirm": true})`. Do not invent Place IDs; use `tescmd_navigation_send` for a single address if you do not need multi-stop routing.

