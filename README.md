# Hermes Tesla Fleet plugin

Give Hermes safe, native access to your Tesla.

`hermes-tescmd-plugin` adds Tesla Fleet operations to Hermes as structured tools, quick slash commands, and a native dashboard tab. Once your Tesla Developer app and plugin-owned credentials are configured, Hermes can reason over vehicle state, select the right Tesla operation, and execute it with explicit safety gates.

Hermes can answer and act on requests like:

```text
Is my car still charging?
Warm the cabin to 70 before I leave.
Lock the Cybertruck if it is unlocked.
Send the charger near the grocery store to navigation.
Check whether my Fleet app, OAuth token, and virtual key are ready.
```

The plugin exposes OAuth/admin checks, vehicle reads, signed vehicle commands, charging, climate, security, energy sites, sharing, navigation, partner registration, and raw Fleet API escape hatches as structured Hermes tools. Common operations also show up as `/tescmd-*` slash commands and in the Hermes dashboard at `/tescmd`.

## Why use this with Hermes

- **Natural-language Tesla operations.** Ask Hermes for the outcome, not the exact command. Hermes can inspect vehicle state, resolve the target vehicle, choose the right tool, and summarize the result.
- **Works wherever Hermes runs.** Use the same Tesla controls from the terminal, gateway chats, cron jobs, webhooks, or other Hermes entry points.
- **Agent-friendly tool surface.** The plugin registers 175 typed, JSON-returning tools through the `hermes_agent.plugins` entry point. Hermes sees schemas, required args, confirmation markers, and structured errors instead of parsing terminal output.
- **Fast daily controls.** `/tescmd-*` slash commands cover common reads and guarded quick actions; the `/tescmd` dashboard gives you status panels and confirm-gated buttons for security, climate, charging, body, media, and navigation controls.
- **Real-world safety gates.** Side-effecting commands require `confirm: true` and fail before network/file side effects when confirmation is missing. Wake-with-read is also treated as a side effect when applicable.
- **Signed commands without agent-side crypto.** Known Vehicle Command Protocol operations use the plugin-owned P-256 key when required and fail closed if signing prerequisites are missing.
- **Hermes-owned auth, plugin-owned operational state.** OAuth tokens are written through Hermes' auth store when the plugin is running inside Hermes, with a plugin-local mirror for compatibility. Tesla app config, vehicle-command keys, exports, and response cache stay under `HERMES_HOME/plugins/hermes-tescmd-plugin/`, not inside `site-packages`.
- **Docs-only onboarding by design.** There is intentionally no Hermes setup wizard or generic config mutation tool; Tesla app setup, HTTPS hosting, and virtual-key enrollment remain explicit operator-managed steps.

## What this is not

- Not a tool that creates or mutates your Tesla Developer app for you.
- Not a public-key hosting automation service. `tescmd_key_deploy(method="local")` prepares files; you publish them with your own HTTPS hosting.
- Not a bypass for Tesla Fleet permissions, OAuth scopes, vehicle-command enrollment, or Hermes confirmation gates.

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

3. Configure the non-secret Tesla app defaults. When Hermes' plugin config store is available, the plugin registers a dashboard-editable config section at:

```text
plugins.entries.hermes-tescmd-plugin.config.profiles.default
```

These fields are safe to edit through Hermes' dashboard config editor when your Hermes runtime exposes plugin-provided config sections: `client_id`, `region`, `domain`, `oauth_redirect_uri`, `default_vin`, and `scopes`. Existing plugin-local config is migrated into that Hermes config section on first read when the store is available and no dashboard value exists yet. Hermes config-store values then take precedence over plugin-local values for those non-secret fields.

Secret or sensitive values stay out of the dashboard/config-store schema: `client_secret`, vehicle-command private/public key paths, Google Maps API keys, OAuth tokens, PINs, and refresh/access tokens. Keep those in plugin-owned state/auth flows.

Legacy/backcompat config still works at:

```text
$HERMES_HOME/plugins/hermes-tescmd-plugin/config.json
```

Minimal single-profile legacy shape:

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

4. Ask Hermes to run `tescmd_onboarding_status` or `tescmd_status`.

`tescmd_onboarding_status` is the guided, non-mutating checklist: it reports the current phase, missing prerequisites, next tool, docs anchor, and readiness booleans without writing config, auth, keys, or vehicle state. `tescmd_status` remains the broader readiness dashboard with derived callback/public-key URLs. The Hermes web dashboard also gets a Tesla tab at `/tescmd` after the plugin registers; restart `hermes dashboard` or use the dashboard plugin rescan button if it was already running.

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

## What you can do from Hermes

| User intent | Hermes path |
| --- | --- |
| "Is my Tesla ready for a road trip?" | Read battery, range, charging, drive state, closures, software, and nearby chargers, then summarize the useful parts. |
| "Make the car comfortable before I leave." | Start climate, set target temperature, check cabin temperature, and stop climate later through tools, slash commands, or dashboard buttons. |
| "Make sure I left it secure." | Check locks, closures, Sentry mode, and location; lock or flash/honk with explicit confirmation. |
| "Send this place to the car." | Search Google Places when configured, disambiguate candidates, and send a destination or waypoint route only after confirmation. |
| "Build an automation around my car." | Use Hermes cron jobs, webhooks, gateway chats, or agent workflows against the same structured Tesla tools. |
| "Debug my Tesla Fleet setup." | Ask `tescmd_status`, `tescmd_auth_status`, `tescmd_key_validate`, and cache/key tools for readiness booleans and next steps. |

## Common Hermes tasks

| Goal | Start with |
| --- | --- |
| Check guided onboarding phase | `tescmd_onboarding_status` |
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

Hermes also registers a broader quick-command surface for frequent reads and guarded operational actions:

| Group | Slash commands |
| --- | --- |
| Readiness/admin | `/tescmd-status`, `/tescmd-auth-status`, `/tescmd-onboarding`, `/tescmd-key-show`, `/tescmd-key-validate`, `/tescmd-cache-status`, `/tescmd-cache-clear confirm=true` |
| Vehicle reads | `/tescmd-vehicles`, `/tescmd-vehicle-status`, `/tescmd-drive`, `/tescmd-closures`, `/tescmd-config`, `/tescmd-gui`, `/tescmd-security-status`, `/tescmd-software`, `/tescmd-nearby-chargers`, `/tescmd-alerts`, `/tescmd-drivers`, `/tescmd-release-notes`, `/tescmd-mobile-access`, `/tescmd-energy`, `/tescmd-service`, `/tescmd-warranty`, `/tescmd-charge`, `/tescmd-climate`, `/tescmd-location` |
| Security/attention | `/tescmd-wake`, `/tescmd-flash`, `/tescmd-honk`, `/tescmd-lock`, `/tescmd-unlock`, `/tescmd-sentry enabled=true|false` |
| Climate/charging | `/tescmd-climate-start`, `/tescmd-climate-stop`, `/tescmd-set-temp driver_temp=70 passenger_temp=70`, `/tescmd-charge-start`, `/tescmd-charge-stop`, `/tescmd-charge-limit percent=80`, `/tescmd-charge-amps amps=32`, `/tescmd-charge-port-open`, `/tescmd-charge-port-close` |
| Body/media/navigation | `/tescmd-frunk`, `/tescmd-trunk-open`, `/tescmd-trunk-close`, `/tescmd-window-vent`, `/tescmd-window-close`, `/tescmd-media-play`, `/tescmd-media-next`, `/tescmd-media-prev`, `/tescmd-media-volume-up`, `/tescmd-media-volume-down`, `/tescmd-media-volume-set volume=3`, `/tescmd-nav 'address' confirm=true`, `/tescmd-nav 'address' vin=... confirm=true`, `/tescmd-nav-search 'place'`, `/tescmd-nav-waypoints place_ids=id1,id2` |

Side-effecting slash commands require `confirm=true`. Read commands that wake a sleeping vehicle require both `wake=true` and `confirm=true`.
For `/tescmd-nav` and `/tescmd-nav-search`, the bare or quoted positional text is treated as the destination/query. If you also need to target a specific vehicle, pass it explicitly as `vin=...`; a bare first token is not interpreted as a vehicle identifier for those navigation commands.

Arguments use terse shell-style tokens: `key=value`, `key:value`, booleans like `confirm=true`, comma-separated lists like `endpoints=charge_state,drive_state`, and one bare positional vehicle identifier for most vehicle-targeting commands.

The Hermes web dashboard gets a native Tesla tab at `/tescmd`. It uses the same existing native tool handlers as Hermes tools, so confirm-gated actions still fail closed when `confirm=true` is missing. The dashboard now includes grouped read panels, wake/no-cache/unit read options, status/auth/key/cache panels, and guarded control groups for security, climate, charging, body, media, and navigation. Non-secret plugin settings are registered for Hermes' normal dashboard config editor when supported. Higher-risk flows such as remote start, speed-limit PINs, valet/PIN-to-drive, erase-user-data, and raw Fleet API calls remain tool-only.

## Tool surface

The plugin registers the complete 175-tool Hermes surface by default. Tool-load minimization is intentionally not used; if a call feels slow, profile command invocation, auth/cache behavior, and Tesla network latency rather than hiding tools from Hermes.

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
- side-effecting vehicle commands and wake attempts append redacted audit entries to `audit/commands.jsonl` and are also emitted through Hermes' standard logger into `agent.log` when Hermes logging is configured
- auth export writes a `0600` file and does not return bearer/refresh tokens in tool output

Use the same care you would use with the Tesla app.

## Stored state

The plugin stores mutable state under:

```text
$HERMES_HOME/plugins/hermes-tescmd-plugin/
```

Typical files and stores:

- Hermes auth store (`$HERMES_HOME/auth.json`) — primary Tesla OAuth token store when running inside Hermes, under provider id `tesla`
- `config.json` — Tesla app/profile config
- `auth.json` — plugin-local OAuth token mirror for compatibility and standalone package contexts
- `pending-auth.json` — short-lived PKCE login state
- `response-cache.json` — selected read-only Fleet responses; may include sensitive vehicle/location snapshots
- `audit/commands.jsonl` — redacted JSONL command audit trail for side-effecting vehicle commands and wake attempts, written `0600`; the same redacted events are emitted through Hermes' standard logger for `agent.log` visibility
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
- profile-scoped token persistence through Hermes' auth store when available
- plugin-local token mirroring for compatibility and standalone contexts
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

## Feature scope

The plugin registers the practical Tesla Fleet surface that Hermes needs for daily use and automation:

- readiness/status, help, and next-step guidance
- OAuth login, callback completion, token refresh, import/export, logout, and partner registration
- vehicle-command key generation, local deploy prep, validation, and enrollment guidance
- vehicle reads for status, drive state, charge state, climate, closures, location, GUI settings, alerts, software, service, nearby chargers, mobile access, drivers, and schedules
- guarded controls for wake, lock/unlock, flash, honk, Sentry mode, climate, charging, charge port, trunk/frunk, windows, media, and navigation
- energy, billing, user, partner, sharing, telemetry guidance, cache, and raw Fleet API escape-hatch tools

Some surfaces are deliberately information-only or tool-only rather than dashboard buttons. Higher-risk flows such as remote start, speed-limit PINs, valet/PIN-to-drive, erase-user-data, and raw Fleet API calls stay out of the quick dashboard action surface.

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
