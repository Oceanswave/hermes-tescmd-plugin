# Hermes Tesla Fleet plugin

Control and inspect Tesla Fleet API resources directly from Hermes.

This is a native, pip-installable Hermes plugin for Tesla owners, operators, and agents that need structured Tesla Fleet API tools instead of a terminal CLI wrapper. After you register your own Tesla Developer app and add your app credentials to the plugin config, Hermes gets a full Tesla tool surface for OAuth, vehicle reads, signed vehicle commands, charging, climate, security, energy sites, sharing, navigation, partner registration, and raw Fleet API escape hatches.

## Why use this

- Native Hermes tools, not shell commands. The plugin registers through the `hermes_agent.plugins` entry point and returns structured JSON results.
- Full Tesla Fleet coverage. The runtime registers 173 dedicated tools plus safe raw `/api/...` escape hatches for future endpoints.
- Fast operations. The plugin also registers `/tescmd-*` slash commands for common reads and guarded quick actions, and installs a Hermes dashboard tab at `/tescmd` for status, vehicle reads, and confirm-gated buttons.
- Built for real-world controls. Side-effecting commands require `confirm: true` and fail before network/file side effects when confirmation is missing.
- Plugin-owned state. Tesla app config, OAuth tokens, vehicle-command keys, exports, and response cache live under `HERMES_HOME/plugins/hermes-tescmd-plugin/`, not inside Hermes Agent config or `site-packages`.
- Signed-command aware. Known Vehicle Command Protocol commands use the plugin-owned P-256 key when required and fail closed if signing prerequisites are missing.
- Docs-only onboarding. There is intentionally no setup wizard or generic config mutation tool; Tesla app setup, HTTPS hosting, and virtual-key enrollment remain explicit operator-managed steps.

## What this is not

- Not a wrapper around the upstream `tescmd` CLI.
- Not an MCP server, bridge daemon, upstream Textual dashboard, or subprocess launcher.
- Not a tool that creates or mutates your Tesla Developer app for you.
- Not a public-key hosting automation service. `tescmd_key_deploy(method="local")` prepares files; you publish them with your own HTTPS hosting.

## Requirements

- Python 3.11+
- Hermes Agent with plugin support
- A Tesla Developer app you control
- Tesla Fleet API scopes appropriate for the operations you want
- A public HTTPS domain/callback if you use OAuth and vehicle-command key enrollment
- Optional: Google Maps Places API key for address/place-name lookup before multi-stop navigation

## Install

From a local checkout:

```bash
pip install ~/hermes-tescmd-plugin
```

From a built wheel:

```bash
pip install dist/hermes_tescmd_plugin-*.whl
```

Restart Hermes after installation so plugin entry points reload.

For editable development, TestPyPI/prerelease installs, uninstall steps, and smoke checks, see `INSTALL.md`.

## First-time setup at a glance

The full guided flow lives in `docs/ONBOARDING.md`. The short version is:

1. Create a Tesla Developer app outside Hermes.
2. Configure Tesla app URLs:

```text
Allowed Origin URL(s): https://<your-domain>
Allowed Redirect URI(s): https://<your-domain>/callback
Allowed Returned URL(s): leave blank unless Tesla requires it
```

Do not put the `.well-known` public-key URL in those fields. Tesla discovers the vehicle-command public key from your app domain.

3. Create plugin config at:

```text
$HERMES_HOME/plugins/hermes-tescmd-plugin/config.json
```

Minimal single-profile shape:

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

4. Ask Hermes to run `tescmd_status`.

That status response is the best next-step dashboard. It reports readiness booleans, missing prerequisites, derived callback/public-key URLs, and recommended next actions. The Hermes web dashboard also gets a Tesla tab at `/tescmd` after the plugin registers; restart `hermes dashboard` or use the dashboard plugin rescan button if it was already running.

5. Start OAuth with `tescmd_auth_login`, open the returned Tesla URL, then complete with `tescmd_auth_complete` using either the full callback URL or `code` + `state`.

6. For signed vehicle commands, generate and host a virtual-key public key:

```text
tescmd_key_generate({"confirm": true})
tescmd_key_deploy({"method": "local", "confirm": true})
```

Upload or serve the generated hosting tree from your public HTTPS domain so Tesla can read:

```text
https://<your-domain>/.well-known/appspecific/com.tesla.3p.public-key.pem
```

Then validate and enroll:

```text
tescmd_key_validate({})
tescmd_key_enroll({})
```

`docs/ONBOARDING.md` includes a full OAuth + virtual-key enrollment walkthrough and an operator-managed Tailscale Funnel example for prerelease/testing setups.

## Common Hermes tasks

| Goal | Start with |
| --- | --- |
| Check plugin/auth/key readiness | `tescmd_status` |
| Start Tesla OAuth | `tescmd_auth_login` |
| Complete OAuth callback | `tescmd_auth_complete` |
| List vehicles | `tescmd_vehicle_list` |
| Read vehicle status | `tescmd_vehicle_status` |
| Wake before a read | use `wake: true` with explicit confirmation where required |
| Start/stop climate | `tescmd_climate_start`, `tescmd_climate_stop` |
| Lock/unlock | `tescmd_security_lock`, `tescmd_security_unlock` |
| Set charge limit | `tescmd_charge_limit` |
| Open/close charge port | `tescmd_charge_port_open`, `tescmd_charge_port_close` |
| Search for a navigation place | `tescmd_navigation_place_search` |
| Send multi-stop navigation | `tescmd_navigation_waypoints` |
| Clear cached status data | `tescmd_cache_clear` |
| Reach a future Fleet endpoint | `tescmd_raw_get`, `tescmd_raw_post`, or `tescmd_raw_delete` |

Normal daily use should stay in the dedicated operational families: `vehicle_*`, `charge_*`, `climate_*`, `security_*`, `media_*`, `navigation_*`, `energy_*`, and `sharing_*`.

## Slash commands and dashboard

Hermes also registers a small quick-command surface for frequent reads and low-impact guarded actions:

| Slash command | Purpose |
| --- | --- |
| `/tescmd-status [profile=default]` | Show plugin/auth/key readiness and next steps. |
| `/tescmd-vehicles [profile=default] [region=na|eu|cn]` | List account vehicles. |
| `/tescmd-vehicle-status [vin] [endpoints=charge_state,drive_state] [wake=true confirm=true]` | Read vehicle state, optionally limited to selected endpoints. |
| `/tescmd-charge [vin] [wake=true confirm=true]` | Read charge state. |
| `/tescmd-climate [vin] [wake=true confirm=true]` | Read climate state. |
| `/tescmd-location [vin] [wake=true confirm=true]` | Read location state. |
| `/tescmd-wake [vin] confirm=true` | Wake the selected/default vehicle. |
| `/tescmd-flash [vin] confirm=true` | Flash lights. |
| `/tescmd-honk [vin] confirm=true` | Honk horn. |
| `/tescmd-lock [vin] confirm=true` | Lock the vehicle. |

Arguments use terse shell-style tokens: `key=value`, `key:value`, booleans like `confirm=true`, comma-separated lists like `endpoints=charge_state,drive_state`, and one bare positional vehicle identifier.

The Hermes web dashboard gets a native Tesla tab at `/tescmd`. It uses the same existing native tool handlers as Hermes tools, so confirm-gated actions still fail closed when `confirm=true` is missing.

## Tool surface

The plugin registers the complete 173-tool Hermes surface by default. Tool-load minimization is intentionally not used; if a call feels slow, profile command invocation, auth/cache behavior, and Tesla network latency rather than hiding tools from Hermes.

High-level families:

- status/help
- OAuth auth import/export/login/logout/refresh/register
- vehicle-command key generation, validation, enrollment, and local deploy prep
- user, billing, partner, energy, vehicle, charge, climate, security, media, navigation, software, power, sharing, telemetry guidance, cache, and raw Fleet API tools

For implementation details, see `src/hermes_tescmd_plugin/runtime.py`.

## Safety model

Tesla controls can have physical effects. This plugin treats them that way.

Guardrails:

- side-effecting tools require `confirm: true`
- denied side effects make zero network requests/file writes
- wake-with-read is treated as a side effect when applicable
- known signed-command-required operations fail before network when no vehicle-command key is configured
- raw Fleet API paths must be relative `/api/...` paths; absolute URLs, traversal, and NUL bytes are rejected
- sensitive error payloads are redacted before returning to Hermes
- auth export writes a `0600` file and does not return bearer/refresh tokens in tool output

Use the same care you would use with the Tesla app.

## Stored state

The plugin stores mutable state under:

```text
$HERMES_HOME/plugins/hermes-tescmd-plugin/
```

Typical files:

- `config.json` — Tesla app/profile config
- `auth.json` — OAuth token state
- `pending-auth.json` — short-lived PKCE login state
- `response-cache.json` — selected read-only Fleet responses; may include sensitive vehicle/location snapshots
- `keys/<profile>/vehicle-command-key.pem` — private vehicle-command key, written `0600`
- `keys/<profile>/vehicle-command-key.public.pem` — public vehicle-command key
- `hosting/<profile>/...` — static public-key hosting tree prepared by local deploy
- `exports/` — explicit auth exports

No mutable auth/config is stored inside `site-packages`.

## Tesla auth model

The plugin implements Tesla OAuth directly:

- browser authorization: `https://auth.tesla.com/oauth2/v3/authorize`
- token exchange/refresh/partner tokens: `https://fleet-auth.prd.vn.cloud.tesla.com/oauth2/v3/token`
- Fleet API audience derived from the selected region
- profile-scoped token persistence under plugin-owned state
- partner registration via client credentials when configured

Partner/business-only scopes such as `vehicle_specs`, `vehicle_pricing_info`, and `enterprise_management` may be useful for partner flows, but `tescmd_auth_login` intentionally omits them from third-party customer OAuth URLs because Tesla does not grant them to ordinary user tokens.

## Signed vehicle commands

`tescmd_key_generate` creates a Tesla-compatible P-256 keypair. `tescmd_key_show` and `tescmd_status` show the enrollment URL when a domain and public key are available:

```text
https://tesla.com/_ak/<your-domain>
```

After virtual-key enrollment, commands that require Vehicle Command Protocol signing use the plugin-owned key and signed-session transport. Commands marked unsigned use Fleet REST command endpoints where Tesla still allows them.

Signed-command hardening includes:

- full VIN resolution before signing
- session-info HMAC verification
- session cache invalidation on protocol faults
- command registry fail-closed behavior for unknown commands
- private key files written with `0600` permissions and no overwrite unless `force: true`

## Navigation and Google Places

Tesla multi-waypoint navigation expects Google Maps Place IDs encoded as `refId:<PLACE_ID>`. If you already have Place IDs, no Google key is needed. If you want Hermes to resolve addresses or place names, add `google_maps_api_key` to plugin config with Places API enabled.

Use:

1. `tescmd_navigation_place_search` to get candidates
2. choose the intended candidate
3. `tescmd_navigation_waypoints({"place_ids": ["..."], "confirm": true})`

Do not invent Place IDs. Use `tescmd_navigation_send` for a single address when multi-stop routing is unnecessary.

## Upstream `tescmd` parity

A mechanical audit against the upstream `tescmd` Click tree found 155 upstream leaf commands. This plugin exposes 173 Hermes tools because it splits or renames some flows for native Hermes use.

Intentional differences:

- no `tescmd_setup` or setup wizard; config is docs-only through `config.json`
- no upstream Textual dashboard, MCP server, OpenClaw bridge, telemetry daemon, or public-key hosting process launched inside Hermes
- `tescmd_serve`, `tescmd_openclaw_bridge`, and `tescmd_vehicle_telemetry_stream` are compatibility/info tools
- power, navigation, trunk, precondition, and telemetry names are normalized into clearer Hermes families
- GitHub Pages and Tailscale hosting automation are not plugin features; use your own HTTPS hosting

## Development

Install dev dependencies:

```bash
python -m pip install -e '.[dev]'
```

Run the local release gate:

```bash
python -m pytest -q
python -m ruff check .
python -m mypy src/hermes_tescmd_plugin
python -m vulture src tests --min-confidence 90
python -m compileall -q src tests scripts
rm -rf dist build *.egg-info
python -m build --sdist --wheel
python -m twine check dist/*
```

CI runs the same checks on pull requests and pushes to `main`. Release publishing is handled separately by the GitHub Release-triggered PyPI Trusted Publishing workflow. See `PUBLISHING.md`.
