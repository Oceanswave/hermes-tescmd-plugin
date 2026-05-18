# Installation and configuration

This plugin is a normal pip-installable Hermes plugin package. Hermes discovers it through the Python entry point group `hermes_agent.plugins`; it does not need to live inside the Hermes Agent source checkout.

For first-time Tesla setup, use the guided docs-only flow in `docs/ONBOARDING.md`. It walks through Tesla app registration, public OAuth callback, key hosting, partner registration, virtual-key enrollment, read proof, and the first low-impact live-control proof without adding a setup wizard or generic config-mutating tool.

## Standard locations

### Plugin package source

For local development, keep the source checkout wherever you normally keep projects. On this machine the canonical checkout is:

```text
~/hermes-tescmd-plugin
```

That standalone location is intentional. It keeps the Hermes Agent repository clean and mirrors the recommended editable-install workflow for pip entry-point plugins.

Production installs usually do not have a source checkout at all; the package is installed into the same Python environment that runs Hermes.

### Hermes environment

Install the plugin into the Python environment used by Hermes. For a git/source install of Hermes on this machine, that is usually:

```text
$HERMES_AGENT_HOME/venv
```

### Plugin state and config

Mutable Tesla state belongs under `HERMES_HOME`, not inside `site-packages` and not inside the Hermes Agent repo:

```text
$HERMES_HOME/plugins/hermes-tescmd-plugin/
```

Default local path when `HERMES_HOME` is not overridden:

```text
$HERMES_HOME/plugins/hermes-tescmd-plugin/
```

Files in that directory include:

```text
config.json          Tesla app/profile config, including optional Google Places key
auth.json            OAuth token state
pending-auth.json    in-progress PKCE login state
response-cache.json  small read-only Fleet API response cache (local 0600 plugin state; may contain sensitive vehicle telemetry/location snapshots)
keys/                vehicle-command private/public keys
hosting/             local public-key hosting tree prepared by tescmd_key_deploy
exports/             confirmed auth export files
```

This separation is deliberate:

- Hermes `config.yaml` is for Hermes itself: model/provider/tool/gateway/profile settings.
- Plugin `config.json` is for this Tesla integration: Tesla app IDs, Fleet region, default vehicle, domain, optional Google Maps key.
- Secrets/tokens stay in plugin-owned state with plugin-specific permissions and redaction rules.

## Install from PyPI or TestPyPI prerelease

Once published, install the prerelease into the Hermes venv with:

```bash
cd $HERMES_AGENT_HOME
venv/bin/python -m pip install --pre hermes-tescmd-plugin
```

For a TestPyPI prerelease smoke:

```bash
cd $HERMES_AGENT_HOME
venv/bin/python -m pip install --pre \
  --index-url https://test.pypi.org/simple/ \
  --extra-index-url https://pypi.org/simple/ \
  hermes-tescmd-plugin
```

Restart Hermes CLI/gateway after install so tool schemas reload.

## Install from a built wheel

From the plugin checkout:

```bash
cd ~/hermes-tescmd-plugin
.verify-venv/bin/python -m build --sdist --wheel
cd $HERMES_AGENT_HOME
venv/bin/python -m pip install ~/hermes-tescmd-plugin/dist/hermes_tescmd_plugin-*.whl
```

Restart Hermes CLI/gateway after install.

## Editable local development install

Use this while iterating on the plugin locally:

```bash
cd $HERMES_AGENT_HOME
venv/bin/python -m pip install -e ~/hermes-tescmd-plugin
```

Then restart the Hermes CLI/gateway or start a fresh session. Hermes loads plugin tools at process/session start; changed schemas do not apply to an already-running session.

## Verify plugin discovery

Run this from the Hermes venv:

```bash
cd $HERMES_AGENT_HOME
venv/bin/python - <<'PY'
from importlib.metadata import version
import hermes_tescmd_plugin

class Ctx:
    def __init__(self):
        self.tools = []
        self.skills = []
    def register_tool(self, **kwargs):
        self.tools.append(kwargs)
    def register_skill(self, name, path, description=None):
        self.skills.append((name, path, description))

ctx = Ctx()
hermes_tescmd_plugin.register(ctx)
names = {tool['name'] for tool in ctx.tools}
required = {
    'tescmd_status',
    'tescmd_help',
    'tescmd_auth_login',
    'tescmd_auth_complete',
    'tescmd_navigation_place_search',
    'tescmd_navigation_waypoints',
    'tescmd_vehicle_list',
    'tescmd_cache_status',
}
forbidden = {'tescmd_setup', 'tescmd_setup_wizard', 'tescmd_mcp_serve'}
print({
    'dist_version': version('hermes-tescmd-plugin'),
    'module_version': hermes_tescmd_plugin.__version__,
    'module_file': hermes_tescmd_plugin.__file__,
    'tool_count': len(ctx.tools),
    'skill_count': len(ctx.skills),
    'missing': sorted(required - names),
    'forbidden_present': sorted(forbidden & names),
})
PY
```

Expected for the current prerelease line:

```text
missing: []
forbidden_present: []
tool_count: 173
skill_count: 1
```

## Manual configuration

Create or edit:

```text
$HERMES_HOME/plugins/hermes-tescmd-plugin/config.json
```

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

There is intentionally no `tescmd_setup` tool or wizard. Configuration and onboarding are documentation-driven; the advertised tool surface is operational/auth/key/status focused.

Partner/business-only scopes (`vehicle_specs`, `vehicle_pricing_info`, `enterprise_management`) may be present in config for client-credentials flows, but `tescmd_auth_login` filters them out of the customer OAuth URL because Tesla does not grant them to third-party user tokens.

After editing config, call `tescmd_status` to check readiness and next steps.

## First OAuth login

1. In Tesla Developer app settings, configure the public HTTPS URLs for your domain. With the example `domain` above, use:

```text
Allowed Origin URL(s): https://cars.example.com
Allowed Redirect URI(s): https://cars.example.com/callback
Allowed Returned URL(s) (Optional): leave blank unless Tesla requires it; if required, use https://cars.example.com
```

If you set `oauth_redirect_uri`, the `Allowed Redirect URI(s)` value must match that exact URL instead. Do not put the `.well-known` public-key URL in these fields.

2. Start login with `tescmd_auth_login`.
3. Open the returned `auth_url` in a browser.
4. Complete login and consent.
5. Tesla redirects to the public callback URL. The browser may display a static-host 404; copy the full address-bar URL containing `code` and `state` and pass it to `tescmd_auth_complete`.
6. Check `tescmd_auth_status` or `tescmd_status`.

## Optional vehicle-command key setup

1. Call `tescmd_key_generate` with `confirm: true`.
2. Call `tescmd_key_deploy` with `method: "local"` and `confirm: true`.
3. Host the generated `.well-known/appspecific/com.tesla.3p.public-key.pem` from your own public HTTPS domain.
4. Call `tescmd_key_validate` to verify the hosted key fingerprint matches the local key.
5. Call `tescmd_key_enroll` for the Tesla enrollment URL.

### Example: operator-managed Tailscale Funnel key hosting

Tailscale Funnel can temporarily or permanently expose the local public-key hosting tree over HTTPS for Tesla Developer app registration and virtual-key enrollment. This is an operator-managed hosting recipe; the plugin still only prepares local files with `tescmd_key_deploy(method="local")` and does not manage Funnel itself.

Use example hostnames in docs and replace them locally. Example values:

```text
Tailscale Funnel hostname: tesla-keyhost.example-tailnet.ts.net
Local static host port: 8766
Plugin profile: default
```

Add the hostname to plugin config as a bare hostname, not a URL:

```json
{
  "domain": "tesla-keyhost.example-tailnet.ts.net",
  "oauth_redirect_uri": "https://tesla-keyhost.example-tailnet.ts.net/callback"
}
```

Prepare the plugin-owned key files:

```text
tescmd_key_generate({"confirm": true})
tescmd_key_deploy({"method": "local", "confirm": true})
```

Create a user service for the local static host:

```bash
mkdir -p ~/.config/systemd/user
$EDITOR ~/.config/systemd/user/hermes-tescmd-key-host.service
```

Example service file:

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

Enable and expose it:

```bash
systemctl --user daemon-reload
systemctl --user enable --now hermes-tescmd-key-host.service
tailscale funnel --bg --yes 8766
tailscale funnel status
```

Verify the public key URL and then ask the plugin to compare fingerprints:

```bash
curl -fsS \
  https://tesla-keyhost.example-tailnet.ts.net/.well-known/appspecific/com.tesla.3p.public-key.pem
```

```text
tescmd_key_validate({})
tescmd_key_enroll({})
```

Use these Tesla-facing values for the example domain:

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

Disable later if needed:

```bash
tailscale funnel --https=443 off
systemctl --user disable --now hermes-tescmd-key-host.service
```

## Optional Google Places setup for multi-waypoint navigation

If you already have Google Place IDs, no Google key is required. If you want Hermes to resolve place names or addresses into Place IDs, add `google_maps_api_key` to `config.json` with a Google Maps Platform key that has Places API enabled.

Then use:

1. `tescmd_navigation_place_search` to find Place IDs.
2. `tescmd_navigation_waypoints` with `place_ids` and `confirm: true` to send the multi-stop route.

## Uninstall

```bash
cd $HERMES_AGENT_HOME
venv/bin/python -m pip uninstall hermes-tescmd-plugin
```

Uninstalling the package does not remove plugin state under `$HERMES_HOME/plugins/hermes-tescmd-plugin/`. Delete that directory manually only if you intend to remove Tesla tokens, keys, cached data, and config.
