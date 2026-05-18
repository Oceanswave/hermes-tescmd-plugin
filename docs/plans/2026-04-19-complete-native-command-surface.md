# Complete Native Command Surface Implementation Plan

> Historical note: the native tool surface has been implemented. Treat this as a record of the rollout rather than a list of pending tasks.

> Historical note: implementation instructions below are preserved for context only.

**Goal:** Expose the full native Tesla command functionality already supported by the plugin’s protocol/client layers through Hermes tools, with typed schemas, handler coverage, tests, and updated docs.

**Architecture:** Keep the plugin fully native. Reuse the existing native Fleet API + signed-command path in `client.py`, and expand the user-facing surface by adding static tool specs in `runtime.py` plus thin request-normalizing handlers in `tools.py`. Group commands by domain so tests can cover representative payload mapping and registration completeness.

**Tech Stack:** Python 3.11, httpx, cryptography, native Tesla Fleet API client, native signed-command protocol modules, pytest, hatchling.

---

### Task 1: Audit-supported command inventory into an explicit exposure list

**Objective:** Define the complete set of native commands to expose based on protocol/client support.

**Files:**
- Modify: `src/hermes_tescmd_plugin/runtime.py`
- Modify: `src/hermes_tescmd_plugin/tools.py`
- Test: `tests/test_plugin.py`

**Step 1: Write failing test**
Add a test asserting the runtime exposes the full supported native command surface for the chosen inventory.

**Step 2: Run test to verify failure**
Run: `pytest tests/test_plugin.py::test_runtime_exposes_full_native_command_surface -q`
Expected: FAIL — missing tool names.

**Step 3: Write minimal implementation**
Add the missing tool specs and operation names to `runtime.py` and `tools.py`.

**Step 4: Run test to verify pass**
Run: `pytest tests/test_plugin.py::test_runtime_exposes_full_native_command_surface -q`
Expected: PASS

**Step 5: Commit**
```bash
git add tests/test_plugin.py src/hermes_tescmd_plugin/runtime.py src/hermes_tescmd_plugin/tools.py
git commit -m "feat: expose native command inventory"
```

### Task 2: Add generic native command handler plumbing

**Objective:** Avoid per-command boilerplate by routing exposed commands through shared native command helpers.

**Files:**
- Modify: `src/hermes_tescmd_plugin/tools.py`
- Test: `tests/test_plugin.py`

**Step 1: Write failing test**
Add representative tests for parameterized commands across multiple domains.

**Step 2: Run test to verify failure**
Run: `pytest tests/test_plugin.py::test_extended_native_command_tools_use_expected_payloads -q`
Expected: FAIL — missing handlers or wrong payloads.

**Step 3: Write minimal implementation**
Add shared helper(s) that normalize args into Fleet/command payloads and dispatch via `TeslaFleetClient.vehicle_command()`.

**Step 4: Run test to verify pass**
Run: `pytest tests/test_plugin.py::test_extended_native_command_tools_use_expected_payloads -q`
Expected: PASS

**Step 5: Commit**
```bash
git add tests/test_plugin.py src/hermes_tescmd_plugin/tools.py
git commit -m "feat: add shared native command handler plumbing"
```

### Task 3: Expand charging, climate, and security command surface

**Objective:** Expose the already-supported higher-value vehicle controls first.

**Files:**
- Modify: `src/hermes_tescmd_plugin/runtime.py`
- Modify: `src/hermes_tescmd_plugin/tools.py`
- Test: `tests/test_plugin.py`

**Step 1: Write failing test**
Add expectations for commands including charge port, charging amps, seat heater/cooler, bioweapon mode, valet mode, pin/speed-limit controls, trunk, horn/lights, and boombox.

**Step 2: Run test to verify failure**
Run: `pytest tests/test_plugin.py::test_runtime_exposes_full_native_command_surface tests/test_plugin.py::test_extended_native_command_tools_use_expected_payloads -q`
Expected: FAIL

**Step 3: Write minimal implementation**
Add tool specs and payload mappings for these domains.

**Step 4: Run test to verify pass**
Run the same command.
Expected: PASS

**Step 5: Commit**
```bash
git add tests/test_plugin.py src/hermes_tescmd_plugin/runtime.py src/hermes_tescmd_plugin/tools.py
git commit -m "feat: expand charging climate and security controls"
```

### Task 4: Expose navigation, media, software, and vehicle identity commands

**Objective:** Complete the infotainment/media/navigation surface already supported in the protocol layer.

**Files:**
- Modify: `src/hermes_tescmd_plugin/runtime.py`
- Modify: `src/hermes_tescmd_plugin/tools.py`
- Test: `tests/test_plugin.py`

**Step 1: Write failing test**
Extend tests for navigation/media/software/vehicle naming and window/sunroof controls.

**Step 2: Run test to verify failure**
Run: `pytest tests/test_plugin.py::test_extended_native_command_tools_use_expected_payloads -q`
Expected: FAIL

**Step 3: Write minimal implementation**
Add the missing specs and handlers.

**Step 4: Run test to verify pass**
Run the same command.
Expected: PASS

**Step 5: Commit**
```bash
git add tests/test_plugin.py src/hermes_tescmd_plugin/runtime.py src/hermes_tescmd_plugin/tools.py
git commit -m "feat: expose navigation media software and vehicle controls"
```

### Task 5: Expose schedule-management and remaining unsigned helper commands

**Objective:** Complete the remaining supported schedule and unsigned command helpers.

**Files:**
- Modify: `src/hermes_tescmd_plugin/runtime.py`
- Modify: `src/hermes_tescmd_plugin/tools.py`
- Test: `tests/test_plugin.py`

**Step 1: Write failing test**
Add expectations for schedule-add/remove/batch-remove commands plus unsigned managed charging/location helpers.

**Step 2: Run test to verify failure**
Run: `pytest tests/test_plugin.py::test_runtime_exposes_full_native_command_surface tests/test_plugin.py::test_extended_native_command_tools_use_expected_payloads -q`
Expected: FAIL

**Step 3: Write minimal implementation**
Add the last tool specs and handlers; where Tesla only supports unsigned REST path, route through `vehicle_command()` so the existing client fallback behavior is preserved.

**Step 4: Run test to verify pass**
Run the same command.
Expected: PASS

**Step 5: Commit**
```bash
git add tests/test_plugin.py src/hermes_tescmd_plugin/runtime.py src/hermes_tescmd_plugin/tools.py
git commit -m "feat: complete native schedule and unsigned helper commands"
```

### Task 6: Fix stale docs and packaging metadata

**Objective:** Ensure docs and package metadata match the completed native functionality.

**Files:**
- Modify: `README.md`
- Modify: `pyproject.toml`
- Test: `tests/test_plugin.py`

**Step 1: Write failing test**
Add/extend tests to validate declared runtime dependencies if practical; otherwise use build/install verification.

**Step 2: Run check to verify current failure or gap**
Run: `python -m build --sdist --wheel`
Expected: Existing build passes, but metadata may omit runtime requirements like `protobuf`.

**Step 3: Write minimal implementation**
- Update README tool surface and scope notes
- Add any missing runtime dependency declarations needed by the codebase

**Step 4: Run verification**
Run:
- `pytest -q`
- `python -m build --sdist --wheel`
- `uv run --with twine twine check dist/*`
Expected: all PASS

**Step 5: Commit**
```bash
git add README.md pyproject.toml tests/test_plugin.py src/hermes_tescmd_plugin/runtime.py src/hermes_tescmd_plugin/tools.py
git commit -m "docs: align native plugin docs and metadata with full command surface"
```

### Task 7: Final integration verification

**Objective:** Confirm the completed plugin is consistent, packaged correctly, and fully verified.

**Files:**
- Modify: `README.md` (if minor fixes needed)
- Modify: `tests/test_plugin.py` (if minor fixes needed)

**Step 1: Run full suite**
Run: `pytest -q`
Expected: PASS

**Step 2: Run packaging verification**
Run:
```bash
python -m build --sdist --wheel
uv run --with twine twine check dist/*
```
Expected: PASS

**Step 3: Review resulting wheel/sdist surface**
Verify the package contains the updated tool/skill/docs behavior.

**Step 4: Commit**
```bash
git add -A
git commit -m "feat: complete native hermes tesla plugin functionality"
```