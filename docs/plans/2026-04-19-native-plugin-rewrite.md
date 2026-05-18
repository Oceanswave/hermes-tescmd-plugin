# Native Hermes Tesla Plugin Rewrite Plan

> Historical note: this rewrite is complete. The repo now ships a native Hermes plugin with plugin-owned auth/config storage and no runtime dependency on the upstream `tescmd` CLI.

> Historical note: implementation instructions below are preserved for context only.

**Goal:** Replace the current `tescmd` CLI wrapper with a publishable Hermes plugin that talks to Tesla OAuth and Fleet APIs directly, with no runtime dependency on the upstream `tescmd` CLI.

**Architecture:** Keep the package name and Hermes entry point, but replace dynamic Click discovery with a static native tool catalog. Split the implementation into plugin registration, schema generation, config/auth persistence under `HERMES_HOME`, a direct Tesla HTTP client, and domain-focused tool handlers for setup/auth, vehicle status, charging, climate, and security.

**Tech Stack:** Python 3.11+, `httpx`, `cryptography`, standard library (`json`, `hashlib`, `base64`, `http.server`, `pathlib`, `secrets`, `time`).

---

### Task 1: Replace wrapper tests with native-plugin tests

**Objective:** Define the native plugin contract in tests before implementation.

**Files:**
- Modify: `tests/test_plugin.py`
- Test support: `tests/conftest.py`

**Steps:**
1. Remove tests that depend on Click discovery, argv serialization, subprocess execution, and `tescmd` imports.
2. Add tests for:
   - native static tool registration
   - plugin-owned schema generation
   - setup/auth state persistence
   - PKCE login start/complete flow with fake transport
   - vehicle list/status calls with fake transport
   - charge/climate/security command calls with fake transport
3. Run `pytest -q` and confirm failures are from missing native implementation, not test mistakes.

### Task 2: Replace wrapper runtime with native plugin modules

**Objective:** Delete CLI-wrapper logic and create the native package structure.

**Files:**
- Replace: `src/hermes_tescmd_plugin/runtime.py`
- Replace: `src/hermes_tescmd_plugin/schemas.py`
- Modify: `src/hermes_tescmd_plugin/__init__.py`
- Create: `src/hermes_tescmd_plugin/config.py`
- Create: `src/hermes_tescmd_plugin/storage.py`
- Create: `src/hermes_tescmd_plugin/auth.py`
- Create: `src/hermes_tescmd_plugin/client.py`
- Create: `src/hermes_tescmd_plugin/tools.py`

**Steps:**
1. Introduce package-safe `get_plugin_home()` helpers rooted at `HERMES_HOME`.
2. Add config/token stores using JSON files under `~/.hermes/plugins/hermes-tescmd-plugin/`.
3. Define a static `ToolSpec` model and a schema builder for native Hermes tools.
4. Register a fixed native tool catalog in `register(ctx)`.

### Task 3: Implement Hermes-native setup/auth/bootstrap

**Objective:** Make auth feel right as a plugin instead of a transplanted CLI.

**Files:**
- Create/modify: `src/hermes_tescmd_plugin/auth.py`
- Create/modify: `src/hermes_tescmd_plugin/tools.py`
- Update docs: `README.md`

**Steps:**
1. Implement `tescmd_setup` to save Tesla app configuration (`client_id`, optional `client_secret`, `region`, `domain`, `default_vin`, scopes) and optionally generate a P-256 vehicle-command keypair.
2. Implement `tescmd_auth_login` to generate PKCE state, persist pending auth state, and return the Tesla authorize URL.
3. Implement `tescmd_auth_complete` to accept a callback URL or code/state and exchange it for tokens.
4. Implement `tescmd_auth_register` using client-credentials plus `POST /api/1/partner_accounts`.
5. Implement `tescmd_auth_status`, `tescmd_auth_refresh`, `tescmd_auth_import`, and `tescmd_auth_export`.

### Task 4: Implement native Fleet API client and operational tools

**Objective:** Provide a meaningful native Tesla tool surface with no `tescmd` dependency.

**Files:**
- Create/modify: `src/hermes_tescmd_plugin/client.py`
- Create/modify: `src/hermes_tescmd_plugin/tools.py`
- Update tests: `tests/test_plugin.py`

**Steps:**
1. Implement token-aware HTTP client with region selection and refresh support.
2. Add vehicle reads:
   - `tescmd_vehicle_list`
   - `tescmd_vehicle_status`
   - `tescmd_vehicle_wake`
3. Add charge tools:
   - `tescmd_charge_status`
   - `tescmd_charge_start`
   - `tescmd_charge_stop`
   - `tescmd_charge_limit`
4. Add climate tools:
   - `tescmd_climate_status`
   - `tescmd_climate_start`
   - `tescmd_climate_stop`
   - `tescmd_climate_set_temps`
5. Add security tools:
   - `tescmd_security_lock`
   - `tescmd_security_unlock`
6. Return stable JSON payloads for both success and error cases.

### Task 5: Update docs, packaging, and publish verification

**Objective:** Make the project honest, installable, and ready to publish.

**Files:**
- Modify: `pyproject.toml`
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify: `PUBLISHING.md`
- Modify: `src/hermes_tescmd_plugin/skills/tescmd-operator/SKILL.md`

**Steps:**
1. Remove the `tescmd` dependency and any wrapper-language from docs.
2. Document native auth/setup flow, config storage, and supported tool coverage.
3. Bump version for the native rewrite.
4. Run and verify:
   - `pytest -q`
   - `python -m build --sdist --wheel`
   - `uv run --with twine twine check dist/*`
5. Smoke-check the built wheel contents and entry point.

---

## Success Criteria

- No runtime import or subprocess use of `tescmd`
- No `tescmd` dependency in `pyproject.toml`
- Auth/setup implemented as plugin-owned flows
- Native Fleet API tools registered through `register(ctx)`
- Tests pass without `tescmd` installed
- Built wheel is valid and includes bundled skill
