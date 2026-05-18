# Changelog

## 0.5.0a18

- Tightened the `/tescmd` dashboard density so the vehicle overview appears immediately below the header and widgets use compact cards.
- Fixed the Leaflet map container sizing regression that could make the map thousands of pixels tall or appear broken.
- Made the vehicle map controls compact and disabled scroll-wheel zoom to keep the dashboard stable.

## 0.5.0a17

- Replaced raw JSON slash-command responses with concise human-readable success/failure summaries.
- Summarized common read payloads such as charge, climate, location, vehicle context, cache source, and Tesla API command result.
- Kept explicit retry guidance for side-effect commands that fail closed without `confirm=true`.

## 0.5.0a16

- Added a visual Tesla dashboard overview endpoint and UI with read-only vehicle snapshot cards.
- Added a Leaflet/OpenStreetMap vehicle-location map when coordinates are available.
- Added charge, climate, security/closure, and location summary widgets above the raw payload panel.

## 0.5.0a15

- Improved `/tescmd-*` slash-command confirmation failures so side-effect denials include the exact retry command, for example `/tescmd-honk confirm=true`, and a short explanation of why explicit confirmation is required.

## 0.5.0a14

- Integrated Tesla OAuth token persistence with Hermes' intrinsic auth store when running inside Hermes, while keeping the plugin-local auth mirror for compatibility and standalone package contexts.
- Added status/readiness metadata that reports whether the active auth store is Hermes-backed or plugin-local.
- Documented the Hermes auth store relationship and added regression coverage for save, load preference, clear, and status reporting behavior.

## 0.5.0a13

- Expanded `/tescmd-*` slash commands with readiness/admin checks, richer vehicle-state reads, unlock/Sentry, climate/charging controls, body controls, media controls, and navigation helpers while keeping physical actions confirm-gated.
- Expanded the `/tescmd` Hermes dashboard with grouped read panels, wake/no-cache/unit read options, extra status/auth/key/cache panels, and guarded security, climate, charging, body, media, and navigation action groups.
- Added dashboard API catalog/read/action coverage for the expanded read/action surface, including action-specific arguments such as charge limit, amperage, temperature, Sentry enabled state, media volume, destination, GPS coordinates, and waypoint Place IDs.
- Kept higher-risk flows such as remote start, speed-limit PINs, valet/PIN-to-drive, erase-user-data, and raw Fleet API calls out of the dashboard quick-action surface.

## 0.5.0a12

- Added Hermes plugin slash commands for common Tesla operations: `/tescmd-status`, `/tescmd-vehicles`, `/tescmd-vehicle-status`, `/tescmd-charge`, `/tescmd-climate`, `/tescmd-location`, `/tescmd-wake`, `/tescmd-flash`, `/tescmd-honk`, and `/tescmd-lock`.
- Added a Hermes dashboard extension tab at `/tescmd` with status/read panels, vehicle selection, and confirm-gated quick-action buttons that call the existing native Tesla tool handlers.
- Mirrored packaged dashboard assets into `HERMES_HOME/plugins/hermes-tescmd-plugin/dashboard` during plugin registration so pip entry-point installs are discoverable by the Hermes dashboard without storing mutable Tesla state in package files.
- Added slash/dashboard regression tests covering argument parsing, command registration, confirm-before-network behavior, and dashboard asset installation.

## 0.5.0a11

- Reverted the compact default tool surface. Hermes now registers the full 173-tool Tesla Fleet catalog by default again because the observed issue is command-invocation latency, not tool-load latency.
- Removed the `TESCMD_TOOL_SURFACE` compact/full selector and restored docs/tests/smoke expectations to the full dedicated command set.
- Kept the prior release-readiness hardening: vehicle commands fail closed when a command lacks an explicit signed/unsigned registry entry, and runtime tests assert every exposed vehicle-command tool is registered.
- Hardened privacy boundaries by removing private key paths and cache hash keys from public tool output, sanitizing sensitive exception payloads at the `TeslaAPIError` boundary, and adding regression tests for those behaviors.
- Added an explicit Hatch sdist policy so release source distributions include only the intended package/docs/scripts/release files and exclude tests, local JSON artifacts, caches, build output, and virtual environments.
- Sanitized release documentation to remove machine-specific absolute development paths from published markdown.
- Fixed the signed Vehicle Command Protocol session-info tag parser to decode Tesla's plain HMAC signature data shape instead of treating it as personalized command HMAC data.
- Fixed session-info HMAC verification to match Tesla's Go implementation: metadata + `0xff` + session info, with full-VIN personalization and the session-info request UUID challenge.
- Fixed native vehicle-command handlers to resolve Fleet aliases (`id_s`/vehicle_id/default identifiers) back to a full VIN before signed commands, because signed-command HMAC personalization requires the full VIN even when read endpoints accept aliases.
- Field-proved the guarded non-driving E2E flow against the selected Cybertruck target after virtual-key enrollment: wake/readiness, flash lights, climate start/stop, charge-port open/close, media volume, media playback toggle/restore, driver seat heat on/off, and steering-wheel heat on/off all returned successful signed-command responses with `confirm=true`.
- Tightened read-only and live-fire redaction for public domains, enrollment/key URLs, local/remote fingerprints, cache hashes, and key paths; redacted E2E artifacts now live under `/tmp` and scan clean for VINs, domains, tokens, Google keys, fingerprints, and configured secret values.
- Added `docs/ONBOARDING.md`, a guided docs-only OAuth + virtual-key enrollment flow that walks users through Tesla Developer app URLs/scopes, plugin config, OAuth completion, partner registration, public key hosting, Tesla app virtual-key approval, read proof, and first low-impact live-control proof.
- Documented the recommended user-stepping UX: use `tescmd_auth_status`/`tescmd_help` as state dashboards and route users through narrow auth/key/status tools rather than adding a setup wizard or config-mutating tool.
- Sanitized live-fire validation tooling so it requires `TESCMD_LIVE_TARGET` and writes redacted output to `/tmp` by default instead of embedding an instance-specific vehicle name or writing source-root artifacts.
- Removed local instance-specific artifacts from the checkout and expanded `.gitignore`/build excludes for redacted audits, private key-enrollment payloads, live-fire artifacts, generated manifests, caches, venvs, and upstream audit trees.

## 0.5.0a6

- Added `endpoint-tool-manifest.json`, an exhaustive generated manifest of the native Hermes tool surface: 173 tools, 84 vehicle-command tool specs, 78 unique Fleet command endpoints/aliases, and 112 confirm-required side-effect/admin tools.
- Added an exhaustive regression test proving every `confirm`-required tool denies before network when `confirm` is omitted; the test currently checks 112 tools and asserts zero HTTP calls.
- Rebuilt the prerelease after final MVP hardening with the manifest, docs, and safety test included.

## 0.5.0a5

- Audited the plugin against current Tesla docs for vehicle endpoints, vehicle commands, energy endpoints, charging endpoints, partner endpoints, and user endpoints; the core documented REST endpoint surface is covered by dedicated tools or confirm-gated raw `/api/...` escape hatches.
- Added six dedicated vehicle-data section tools that were previously only reachable through the generic `tescmd_vehicle_status(endpoints=...)` wrapper: `tescmd_vehicle_drive_status`, `tescmd_vehicle_closures_status`, `tescmd_vehicle_config_status`, `tescmd_vehicle_gui_settings`, `tescmd_vehicle_charge_schedule_status`, and `tescmd_vehicle_preconditioning_schedule_status`.
- Expanded the wake-enabled read-only E2E audit to exercise the new vehicle-data section tools and request the broader documented vehicle-data endpoint set in one status call.
- Reran wake-enabled live E2E: 52/55 probes succeeded, including all six new section tools, with no VIN/API-key leakage in the redacted artifact. The same three Tesla/account authorization failures remain: business-only charging sessions, ungranted partner `vehicle_specs`, and missing enterprise-management grant.
- Added regression tests for the new native tool specs and section-handler extraction.

## 0.5.0a4

- Reworked OAuth scope handling so third-party login URLs omit Tesla partner/business-only scopes (`vehicle_specs`, `vehicle_pricing_info`, `enterprise_management`) even when they are present in manual config; auth status now distinguishes configured user scopes, granted user scopes, and partner-only scopes.
- Added partner-only scope support to config validation and client-credentials calls, and switched vehicle specs/pricing helpers to partner-token auth where Tesla documents those scopes.
- Added JWT `scp` parsing when Tesla token responses omit the plain `scope` field, so stored auth status reflects the scopes actually granted by Tesla.
- Added auto-wake support to the read-only E2E audit via `TESCMD_E2E_WAKE=true`; the release audit now explicitly wakes the owner vehicle before live data probes instead of treating sleep/offline state as an endpoint blocker.
- Fixed full-VIN-only endpoint resolution so a default Fleet vehicle ID / `id_s` can be resolved back to a full VIN from the live vehicle list before calling warranty/subscription/upgrade/options endpoints.
- Verified Google Places live lookup and reran wake-enabled live read-only E2E: 46/49 probes succeeded with redacted output and no VIN/API-key leakage. The remaining failures are Tesla-side product/account authorization boundaries: business-only charging sessions, ungranted partner `vehicle_specs`, and missing enterprise-management grant.
- Added tests for JWT scope extraction and full-VIN resolution from a configured Fleet ID.

## 0.5.0a2

- Prepared the native Tesla Fleet plugin as a prerelease line after removing setup/config mutation tools from the advertised Hermes tool surface.
- Added `INSTALL.md` with pip, wheel, editable, TestPyPI/prerelease, discovery-smoke, manual config, OAuth, vehicle-command key, Google Places, and uninstall procedures.
- Documented the standard Hermes plugin layout: standalone pip package source, entry-point discovery via `hermes_agent.plugins`, and plugin-owned mutable state under `HERMES_HOME/plugins/hermes-tescmd-plugin/` rather than Hermes Agent `config.yaml`.
- Kept `tescmd_navigation_place_search` advertised as the Google Places resolver for multi-waypoint navigation.
- Documented operator-managed Tailscale Funnel public-key hosting and public OAuth callback registration with example-only `*.ts.net` hostnames and no project/private Tailscale subdomain in package docs.
- Added `oauth_redirect_uri` config support; when omitted, a configured `domain` now yields the public callback `https://<domain>/callback` instead of a localhost callback.
- Corrected Tesla Developer dashboard guidance for the actual fields: Allowed Origin URL(s), Allowed Redirect URI(s), and optional Allowed Returned URL(s).
- Allowed Fleet vehicle endpoint calls to use Tesla `id_s`/vehicle IDs as well as 17-character VINs, because live Fleet product responses can redact VINs while still returning endpoint-usable vehicle IDs.

## 0.4.4

- Removed the `tescmd_setup` config-mutation tool from the advertised Hermes tool surface; onboarding/configuration is docs-only through `HERMES_HOME/plugins/hermes-tescmd-plugin/config.json`.
- Kept operational/auth/key/status tools, including manual `tescmd_key_generate`, and updated status/auth guidance to point to README/manual config instead of setup tools.
- Confirmed and advertised `tescmd_navigation_place_search` as the Google Places helper for resolving addresses/place names into Place IDs before `tescmd_navigation_waypoints`.
- Added config-level public-domain validation so manual config edits are still checked before use.

## 0.4.1

- Audited native Fleet API coverage against current Tesla vehicle, vehicle-command, energy, partner, and user endpoint docs; dedicated tools cover all documented command endpoints plus selected newer upstream command aliases, with raw `/api/...` escape hatches retained for future Tesla additions.
- Added stricter VIN and path-component validation before network calls for vehicle paths, command names, invoices, invites, and similar Fleet API identifiers.
- Fixed billing invoice response handling and `navigation_request` signed-command alias support.
- Tightened confirmation schemas for admin/key/auth/cache/raw operations and updated tests to assert handler-level safety.
- Removed type/lint/dead-code smells; mypy, vulture, ruff, tests, build, and twine checks are now part of the verified release posture.

## 0.4.0

- Rewrote the plugin into a **native Hermes Tesla plugin** with no runtime dependency on the upstream `tescmd` CLI
- Removed Click discovery, argv serialization, subprocess execution, and `tescmd_run`
- Added plugin-owned config, OAuth PKCE login/completion, token refresh, auth import/export, auth logout, and partner registration flows
- Expanded the native surface to broad upstream capability coverage in plugin form for the Tesla API/tool domains, while intentionally keeping CLI-only daemon/TUI workflows as compatibility/info tools rather than claiming full runtime parity with every `tescmd` UX mode
- Removed the stateful setup wizard, Tailscale hosting automation, GitHub Pages hosting assumptions, and MCP server-mode tool to reduce bootstrap/security surface; first-time Tesla app/domain setup is now documented as explicit operator-managed README steps
- Added a plugin-native response cache for selected read-only vehicle status calls plus working `tescmd_cache_status` / `tescmd_cache_clear`
- Added plugin-owned storage under `HERMES_HOME/plugins/hermes-tescmd-plugin/`
- Added optional P-256 vehicle-command key generation during setup plus plugin-native key validation, enrollment, and local deployment-prep flows
- Added signed-command session transport for supported commands when a vehicle-command key is configured
- Updated docs and tests to reflect the safer native architecture and polished plugin UX

## 0.3.0

- Rewrote the plugin into a **native Hermes Tesla plugin** with no runtime dependency on the upstream `tescmd` CLI
- Removed Click discovery, argv serialization, subprocess execution, and `tescmd_run`
- Added plugin-owned config, OAuth PKCE login, token refresh, auth import/export, auth logout, and partner registration flows
- Added optional P-256 vehicle-command key generation during setup plus plugin-native key validation, enrollment, and deployment-prep flows
- Added signed-command session transport for supported commands when a vehicle-command key is configured
- Added a stateful setup wizard and Tailscale hosting path; these were removed in 0.4.0 in favor of explicit operator-managed setup

## 0.2.1

- Cleaned the plugin surface to remove CLI presentation concerns like `output_format`, `quiet`, and `verbose`
- Kept `background`, `timeout_seconds`, and `exact_argv` as Hermes-native integration behavior
- Reframed `setup` and `auth *` commands as delegated bootstrap/admin flows owned by upstream `tescmd`
- Removed the standalone reporting utility from the shipped plugin surface

## 0.2.0

- Switched from MCP-catalog wrapping to **full Click CLI discovery**
- Added Hermes tools for all discovered `tescmd` leaf commands
- Added `exact_argv` support to `tescmd_run`
- Added support for long-running command execution (`background`, `timeout_seconds`)
- Improved package metadata and publishing readiness

## 0.1.0

- Initial standalone Hermes plugin scaffold
- Dynamic registration from `tescmd` command metadata
- `tescmd_run` fallback tool
- Bundled `tescmd-operator` skill
