# Tesla Fleet onboarding: OAuth + virtual key enrollment

This plugin intentionally keeps setup docs-driven and validates each stage with narrow operational tools. There is no setup wizard and no generic config-mutation tool. When Hermes' plugin config store/dashboard surfaces are available, only non-secret Tesla app defaults are editable there; secrets remain in plugin-owned state/auth flows.

The best user experience is a guided checklist with explicit stop/go checkpoints:

1. Configure Tesla app + plugin config.
2. Validate public HTTPS callback and public key hosting.
3. Complete OAuth.
4. Register partner domain.
5. Generate/host/validate vehicle-command public key.
6. Enroll the virtual key in the Tesla app.
7. Prove vehicle reads.
8. Prove one reversible control command.

Each phase below names the Hermes tool that should be run next and what success looks like.

## Files and state

Plugin-owned mutable state lives under:

```text
$HERMES_HOME/plugins/hermes-tescmd-plugin/
```

For the default profile, legacy/backcompat config lives at:

```text
$HERMES_HOME/plugins/hermes-tescmd-plugin/config.json
```

Non-secret settings may also be stored in Hermes' plugin config section when available:

```text
plugins.entries.hermes-tescmd-plugin.config.profiles.default
```

The plugin registers those non-secret fields with Hermes' plugin config support when the host runtime exposes a dashboard config editor. Existing `config.json` values are migrated into the Hermes config store on first read when no Hermes value exists yet, and Hermes config-store values take precedence over legacy config for non-secret fields.

Keep plugin-owned state files mode `0600`. `config.json` may still contain Tesla OAuth client credentials, Google Places API key, default vehicle identifier, and local operational settings. The Hermes dashboard/config-store surface must not contain `client_secret`, vehicle-command key paths, Google Maps API keys, OAuth tokens, PINs, or auth state.

Never check in:

```text
config.json
auth*.json
pending*.json
keys/
hosting/
cache/
exports/
*-redacted.json
key-enroll-private.json
```

## Phase 0: choose a public HTTPS domain

Tesla needs the same public HTTPS domain for two things:

- OAuth callback, usually `https://<domain>/callback`
- public key hosting at `https://<domain>/.well-known/appspecific/com.tesla.3p.public-key.pem`

Tailscale Funnel works well for an operator-managed prerelease path, but the plugin does not manage Funnel itself.

Example placeholders only:

```text
Domain: tesla-keyhost.example-tailnet.ts.net
OAuth callback: https://tesla-keyhost.example-tailnet.ts.net/callback
Public key URL: https://tesla-keyhost.example-tailnet.ts.net/.well-known/appspecific/com.tesla.3p.public-key.pem
Virtual key enrollment URL: https://tesla.com/_ak/tesla-keyhost.example-tailnet.ts.net
```

## Phase 1: create/register the Tesla developer app

In Tesla Developer, configure the app with:

```text
Allowed Origin URL(s): https://<domain>
Allowed Redirect URI(s): https://<domain>/callback
Allowed Returned URL(s): leave blank unless Tesla requires it; if required, use https://<domain>
```

Recommended user OAuth scopes:

```text
openid offline_access vehicle_device_data vehicle_cmds vehicle_charging_cmds vehicle_location energy_device_data energy_cmds user_data
```

Do not put partner/business-only scopes into the third-party user login URL:

```text
enterprise_management vehicle_specs vehicle_pricing_info
```

Those may be configured for partner/client-credential flows when Tesla grants them, but they are not normal customer OAuth scopes.

## Phase 2: edit plugin config

Edit non-secret app defaults in one of these places:

```text
Hermes dashboard config editor (when plugin-provided config is available)
Hermes config path: plugins.entries.hermes-tescmd-plugin.config.profiles.default
Legacy config file: $HERMES_HOME/plugins/hermes-tescmd-plugin/config.json
```

Dashboard/config-store fields are intentionally limited to `client_id`, `region`, `domain`, `oauth_redirect_uri`, `default_vin`, and `scopes`. Put `client_secret` and `google_maps_api_key` only in plugin-owned secret-safe state/config, not in the dashboard-editable config store.

Legacy config example:

```json
{
  "profile": "default",
  "region": "na",
  "client_id": "YOUR_TESLA_CLIENT_ID",
  "client_secret": "YOUR_TESLA_CLIENT_SECRET",
  "domain": "tesla-keyhost.example-tailnet.ts.net",
  "oauth_redirect_uri": "https://tesla-keyhost.example-tailnet.ts.net/callback",
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
```

Then run:

```text
tescmd_auth_status
```

Success checkpoint:

```text
configured: true
bootstrap.app_configured: true
missing_for_vehicle_reads: []
```

## Phase 3: OAuth login

Run:

```text
tescmd_auth_login
```

Open the returned authorization URL in a browser, complete Tesla login, and copy the final callback URL back into:

```text
tescmd_auth_complete
```

If using a static public callback page, it is okay for the browser to show a simple placeholder page. The important part is the callback URL query string containing `code` and `state`.

Success checkpoint:

```text
tescmd_auth_status
```

Expected:

```text
authenticated: true
pending_login: false
missing_granted_user_scopes: []
ready_for_vehicle_reads: true
```

## Phase 4: generate, host, and validate the vehicle-command key

Generate or show the key:

```text
tescmd_key_generate
```

Prepare the public key for external hosting:

```text
tescmd_key_deploy {"method":"local", "confirm":true}
```

Serve the generated hosting directory from your public HTTPS domain root. The key must be reachable at:

```text
https://<domain>/.well-known/appspecific/com.tesla.3p.public-key.pem
```

Validate:

```text
tescmd_key_validate
```

Success checkpoint:

```text
accessible: true
matches_local_key: true
```

## Phase 5: partner registration

Run:

```text
tescmd_auth_register {"confirm":true}
```

Then check:

```text
tescmd_auth_status
```

Success checkpoint:

```text
partner_ready: true
key_hosting_ready: true
ready_for_vehicle_commands: true
ready_for_signed_commands: true
```

Important: these booleans mean plugin prerequisites are in place. The vehicle itself must still accept the virtual key before signed commands succeed.

## Phase 6: virtual key enrollment in the Tesla app

Run:

```text
tescmd_key_enroll
```

It returns:

```text
enroll_url: https://tesla.com/_ak/<domain>
message: Open the enroll_url on your phone and approve Add Virtual Key in the Tesla app.
```

Open `enroll_url` on a phone that has the Tesla app installed and is logged into the owner account for the vehicle. Approve `Add Virtual Key` in the Tesla app.

This is the most common live-control blocker. If the first signed command returns:

```text
Vehicle rejected handshake: Vehicle does not recognize this key
```

then the public key is hosted correctly enough for the plugin, but the specific vehicle has not enrolled/accepted the virtual key yet. Repeat this phase on the phone with the Tesla app.

## Phase 7: prove reads before controls

List vehicles:

```text
tescmd_vehicle_list
```

Pick the vehicle by display name/VIN/id_s, then wake and read:

```text
tescmd_vehicle_wake {"vin":"<vehicle>", "confirm":true}
tescmd_vehicle_info {"vin":"<vehicle>", "wake":false, "no_cache":true}
```

Success checkpoint:

```text
state: online
vehicle_config.car_type: present
vehicle_state.locked: present
charge_state.charging_state: present
```

## Phase 8: prove one reversible command

Start with one low-impact command:

```text
tescmd_security_flash_lights {"vin":"<vehicle>", "confirm":true}
```

If that succeeds, continue with reversible/non-driving commands only:

```text
tescmd_climate_start {"vin":"<vehicle>", "confirm":true}
tescmd_climate_stop {"vin":"<vehicle>", "confirm":true}
```

Only run lock/unlock if you first read and can restore the initial lock state. Only run charge start/stop if `charging_state` indicates the vehicle is connected/plugged in. Avoid movement-related, access, security, or irreversible commands during onboarding.

## Recommended guided UX without a setup wizard

The best Hermes UX is not a config-writing wizard; it is a checklist-driven assistant flow using existing narrow tools:

- `tescmd_auth_status` as the state dashboard.
- `tescmd_help` as the router from missing prerequisites to the next tool/doc section.
- `tescmd_auth_login` and `tescmd_auth_complete` for OAuth only.
- `tescmd_key_generate`, `tescmd_key_deploy`, `tescmd_key_validate`, and `tescmd_key_enroll` for key phases.
- `tescmd_vehicle_list`, `tescmd_vehicle_wake`, and `tescmd_vehicle_info` for read proof.
- one low-impact command for live control proof.

The plugin includes a non-mutating `tescmd_onboarding_status` tool that returns the current phase, next action, next tool when there is one, docs anchor, and exact missing prerequisites. It does not write config or hide Tesla app approval behind automation; it only guides users through the existing explicit tools.
