# Release checklist

Use this checklist before publishing or handing off a prerelease build of `hermes-tescmd-plugin`.

## Preflight

- Confirm `pyproject.toml`, `src/hermes_tescmd_plugin/__init__.py`, `uv.lock`, bundled skill frontmatter, and `CHANGELOG.md` all use the same prerelease version.
- Remove stale build artifacts: `rm -rf dist build *.egg-info`.
- Confirm no secrets, OAuth codes, bearer tokens, refresh tokens, VINs, or client secrets are present in docs, tests, or build artifacts.
- Confirm Tesla Developer docs use the actual app URL fields: Allowed Origin URL(s), Allowed Redirect URI(s), and optional Allowed Returned URL(s).
- Confirm the plugin is editable-installed into the Hermes environment used for smoke tests.

## Verification commands

```bash
cd ~/hermes-tescmd-plugin
.verify-venv/bin/python -m pytest -q
.verify-venv/bin/python -m ruff check .
.verify-venv/bin/python -m mypy src/hermes_tescmd_plugin
.verify-venv/bin/python -m vulture src tests --min-confidence 90
rm -rf dist build *.egg-info
.verify-venv/bin/python -m build --sdist --wheel
.verify-venv/bin/python -m twine check dist/*
```

## Hermes smoke

From the Hermes venv that will load the plugin:

```bash
cd $HERMES_AGENT_HOME
venv/bin/python -m pip install -e ~/hermes-tescmd-plugin
venv/bin/python - <<'PY'
from importlib.metadata import entry_points
import hermes_tescmd_plugin

class Ctx:
    def __init__(self):
        self.tools = []
        self.skills = []
    def register_tool(self, **kwargs):
        self.tools.append(kwargs)
    def register_skill(self, name, path, description=None):
        self.skills.append((name, path))

ctx = Ctx()
hermes_tescmd_plugin.register(ctx)
names = {t['name'] for t in ctx.tools}
required = {
    'tescmd_status',
    'tescmd_help',
    'tescmd_auth_login',
    'tescmd_auth_complete',
    'tescmd_navigation_place_search',
    'tescmd_navigation_waypoints',
    'tescmd_raw_get',
    'tescmd_raw_post',
    'tescmd_vehicle_list',
    'tescmd_security_unlock',
    'tescmd_cache_status',
    'tescmd_cache_clear',
}
forbidden = {'tescmd_setup', 'tescmd_setup_wizard', 'tescmd_mcp_serve'}
print({'tool_count': len(ctx.tools), 'skill_count': len(ctx.skills), 'missing': sorted(required - names), 'forbidden_present': sorted(forbidden & names), 'module_file': hermes_tescmd_plugin.__file__})
PY
```

Expected for the current prerelease line:

- default tool count: 48 compact tools; set `TESCMD_TOOL_SURFACE=full` before starting Hermes to smoke the 173-tool exhaustive dedicated surface
- one bundled `tescmd-operator` skill
- no `tescmd_setup`
- no `tescmd_setup_wizard`
- no `tescmd_mcp_serve`

## Live E2E gate

Do not claim live Tesla E2E until credentials/account/vehicle access have been supplied and the following have run successfully:

1. Save app/profile config manually in `HERMES_HOME/plugins/hermes-tescmd-plugin/config.json` per README; there is no setup tool.
2. Complete OAuth with `tescmd_auth_login` + `tescmd_auth_complete`.
3. Run `TESCMD_E2E_WAKE=true scripts/e2e_readonly_audit.py` when the user has approved wake as part of validation, and record only redacted summaries. The current 0.5.0a10 live read-only audit reached 52/55 successful probes after explicit wake; the remaining probes are Tesla product/account authorization boundaries: business-only charging sessions, ungranted partner `vehicle_specs`, and missing `enterprise_management` grant.
4. Host and validate the public key manually if signed commands are needed.
5. Complete Tesla app virtual-key approval via `tescmd_key_enroll` before signed-command live-fire.
6. Run any side-effecting command only with explicit user approval and `confirm: true`.
7. For field-proof, run the guarded non-driving live-fire harness with `TESCMD_LIVE_TARGET=<vehicle name or identifier>` and `TESCMD_LIVE_FIRE_OUT=/tmp/tescmd-live-fire-redacted.json`. The current 0.5.0a10 live-fire pass reached 31 guarded steps with no stopped failure after virtual-key enrollment, including flash lights, climate start/stop, charge-port open/close, media volume, media playback toggle/restore, driver seat heat on/off, and steering-wheel heat on/off. Lock/unlock and charge start/stop were skipped because the observed state did not meet the harness safety conditions.

Read-only audit command:

```bash
cd ~/hermes-tescmd-plugin
HERMES_HOME=$HERMES_HOME PYTHONPATH=src \
  .verify-venv/bin/python scripts/e2e_readonly_audit.py > /tmp/tescmd-e2e-readonly-redacted.json
```

The audit output is intentionally redacted for VINs, local paths, Tailscale hostnames, account identifiers, and location-like fields. Do not commit live E2E outputs unless you have independently scanned them for secrets/private locations.


## Publish prerelease

Publish to TestPyPI first unless explicitly releasing to production PyPI:

```bash
cd ~/hermes-tescmd-plugin
.verify-venv/bin/python -m twine upload --repository testpypi dist/*
```

Install the TestPyPI prerelease into the Hermes venv and rerun the smoke check:

```bash
cd $HERMES_AGENT_HOME
venv/bin/python -m pip install --pre \
  --index-url https://test.pypi.org/simple/ \
  --extra-index-url https://pypi.org/simple/ \
  hermes-tescmd-plugin
```

When ready for production PyPI:

```bash
cd ~/hermes-tescmd-plugin
.verify-venv/bin/python -m twine upload dist/*
```

Do not claim live Tesla E2E in release notes until a real Tesla app/account/vehicle and explicit command-scope approvals have been used.
