# Tesla Onboarding Wizard Parity Implementation Plan

> Historical note: this plan was implemented and later intentionally superseded. The stateful `tescmd_setup_wizard`, Tailscale hosting integration, and GitHub Pages assumptions were removed to reduce bootstrap/security surface. Current setup guidance lives in the README and uses explicit operator-managed Tesla Developer app/domain/config-file steps plus `tescmd_auth_login` and `tescmd_auth_complete`; `tescmd_setup` was later removed from the tool surface.

> Historical note: implementation instructions below are preserved for context only.

Goal: Bring the battle-tested user onboarding flow from upstream tescmd into the native Hermes plugin so users can get from zero configuration to authenticated, partner-registered, and enrollment-ready without already knowing every Tesla developer setting.

Architecture: Keep the plugin fully native and plugin-owned. Do not add a runtime dependency on the upstream tescmd CLI. Instead, port the useful onboarding logic and UX into explicit native setup/bootstrap helpers layered on top of the existing config/auth/key tools.

Tech Stack: Python 3.11, httpx, cryptography, existing Hermes native plugin code in src/hermes_tescmd_plugin, pytest.

---

## Problem Summary

Current behavior is too thin for first-time setup:
- tescmd_auth_login hard-fails until client_id is already known
- tescmd_setup is a config setter, not a guided bootstrap flow
- the plugin knows the redirect URI format (http://localhost:<port>/callback) but does not actively guide the user through creating the Tesla developer app
- key generation, public-key hosting prep, partner registration, and enrollment are exposed as separate primitives, but not orchestrated into a user-safe sequence

This creates a chicken-and-egg problem for users who need Tesla callback validation before they can finish collecting the required values.

---

## Target UX

Users should be able to ask Hermes to set up the Tesla plugin and get:
1. exact redirect URI to enter into Tesla developer settings
2. exact scopes to request
3. optional domain/public-key setup guidance for vehicle command features
4. clear progress/status across bootstrap stages
5. a guided sequence for:
   - app creation prerequisites
   - local callback validation
   - PKCE login
   - token completion
   - partner registration
   - key deployment + validation
   - enrollment readiness

---

## Task 1: Add bootstrap status model

Objective: Make setup state explicit so the plugin can guide the user instead of only reporting raw config fields.

Files:
- Modify: src/hermes_tescmd_plugin/config.py
- Modify: src/hermes_tescmd_plugin/tools.py
- Test: tests/test_plugin.py

Steps:
1. Add a helper that computes bootstrap readiness from config/auth/key state.
2. Include stages like app_configured, login_ready, authenticated, partner_ready, partner_registered_candidate, key_present, key_hosting_ready, enrollment_ready.
3. Extend tescmd_status to return this structured bootstrap block.
4. Write tests asserting stage computation for empty config, auth-only config, and fully key-configured config.

## Task 2: Add guided bootstrap output to the native setup/status flow

Objective: Expose the exact values a user needs before they can create or edit the Tesla developer app.

Files:
- Modify: src/hermes_tescmd_plugin/runtime.py
- Modify: src/hermes_tescmd_plugin/tools.py
- Test: tests/test_plugin.py
- Update: README.md

Steps:
1. Return bootstrap guidance from `tescmd_setup`, `tescmd_setup_wizard`, and `tescmd_status` instead of adding a standalone guide tool.
2. Return:
   - redirect_uri derived from the configured public OAuth callback
   - scopes
   - whether client_id/client_secret/domain/default_vin are still missing
   - expected public key URL when domain + key exist
   - Tesla enrollment URL when domain + key exist
3. Include ordered next_steps text in the tool result.
4. Add tests for unconfigured and partially configured states.

## Task 3: Upgrade tescmd_setup from setter to assistant-friendly bootstrap step

Objective: Let setup return actionable guidance immediately after saving partial config.

Files:
- Modify: src/hermes_tescmd_plugin/tools.py
- Test: tests/test_plugin.py
- Update: README.md

Steps:
1. Keep existing persistence behavior.
2. After saving, return bootstrap status plus next recommended action.
3. If client_id is missing, return the redirect URI/scopes the user must enter in Tesla Developer Portal.
4. If domain is present and generate_vehicle_command_key=true, return the generated key metadata plus expected public-key URL and enrollment URL.
5. Add tests covering partial setup responses.

## Task 4: Add localhost callback helper flow

Objective: Reduce friction around the Tesla OAuth callback validation step.

Files:
- Modify: src/hermes_tescmd_plugin/auth.py
- Modify: src/hermes_tescmd_plugin/tools.py
- Modify: src/hermes_tescmd_plugin/runtime.py
- Test: tests/test_plugin.py
- Update: README.md

Steps:
1. Add a helper tool that tells the user exactly what localhost callback URL the plugin expects.
2. If useful and feasible in Hermes, add a tiny callback-capture helper that can accept the pasted callback URL and explain success/failure cleanly.
3. Ensure tescmd_auth_login returns clearer remediation when client_id is absent by pointing users to `tescmd_setup_wizard` plus the exact redirect URI/scopes.
4. Add tests for missing-client-id remediation messaging and callback parsing.

## Task 5: Orchestrate key/domain/partner bootstrap

Objective: Port the most useful battle-tested setup sequencing from tescmd into a native flow.

Files:
- Modify: src/hermes_tescmd_plugin/tools.py
- Modify: src/hermes_tescmd_plugin/runtime.py
- Test: tests/test_plugin.py
- Update: README.md
- Update: src/hermes_tescmd_plugin/skills/tescmd-operator/SKILL.md

Steps:
1. Add a tool that summarizes domain/key/public-key-hosting readiness.
2. Reuse existing key_generate, key_show, key_validate, auth_register, and key_enroll primitives.
3. Return ordered next steps based on current state, for example:
   - configure domain
   - generate key
   - deploy public key
   - validate hosted key
   - authenticate
   - register partner account
   - enroll key in Tesla app
4. Add tests for next-step sequencing.

## Task 6: Documentation and smoke-test updates

Objective: Make the new guided setup flow the documented happy path.

Files:
- Update: README.md
- Update: CHANGELOG.md
- Update: src/hermes_tescmd_plugin/skills/tescmd-operator/SKILL.md
- Test: tests/test_plugin.py

Steps:
1. Replace the current minimal setup section with a guided bootstrap walkthrough.
2. Document that the plugin remains native while porting tescmd’s setup UX.
3. Add smoke-test steps covering:
   - bootstrap guide
   - partial setup
   - auth login
   - auth complete
   - status progression
4. Run pytest -q after changes.

---

## Acceptance Criteria

- A first-time user can get the exact redirect URI and required scopes without already knowing Tesla app settings.
- tescmd_setup and/or a new guide tool returns actionable next steps instead of only raw stored fields.
- tescmd_auth_login missing-client-id errors point to the guided bootstrap path.
- Status output reports bootstrap progress in structured stages.
- Domain/key/partner/enrollment setup is presented as a coherent sequence.
- Tests cover the new bootstrap guidance behavior.
- No runtime dependency on upstream tescmd is added.
