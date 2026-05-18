# Signed Command Protocol Implementation Plan

> Historical note: the native plugin now includes signed-command session support in its current implementation. Keep this document as design history, not as pending work.

> Historical note: implementation instructions below are preserved for context only.

**Goal:** Add full Tesla Vehicle Command Protocol session support to `hermes-tescmd-plugin`, including ECDH handshake, session caching, HMAC signing, protobuf payload generation, and signed routing for commands that require it.

**Architecture:** Vendor the protocol implementation into the plugin package so there is still no runtime dependency on upstream `tescmd`. Add plugin-owned error types, crypto/protocol modules, and integrate them into the existing synchronous Fleet client so operational tools route through `/signed_command` when a vehicle-command key is available and the command registry requires signing.

**Tech Stack:** Python 3.11+, `cryptography`, `httpx`, `protobuf`, stdlib (`base64`, `hashlib`, `hmac`, `time`, `dataclasses`).

---

### Task 1: Vendor protocol/crypto/error modules into the plugin package
**Objective:** Create first-party protocol modules inside `src/hermes_tescmd_plugin/`.

**Files:**
- Create: `src/hermes_tescmd_plugin/errors.py`
- Create: `src/hermes_tescmd_plugin/crypto/ecdh.py`
- Create: `src/hermes_tescmd_plugin/protocol/__init__.py`
- Create: `src/hermes_tescmd_plugin/protocol/{commands,encoder,metadata,payloads,session,signer}.py`
- Create: `src/hermes_tescmd_plugin/protocol/protobuf/{__init__,messages}.py`

**Verification:**
- `pytest tests/test_plugin.py -q` should move past import failure into behavior failures.

### Task 2: Add signed-command client integration
**Objective:** Route supported commands through signed transport when appropriate.

**Files:**
- Modify: `src/hermes_tescmd_plugin/client.py`
- Create: `src/hermes_tescmd_plugin/signed.py` or `src/hermes_tescmd_plugin/protocol/signed_command.py`

**Verification:**
- Security and charge signed-protocol tests fail for behavior, not missing symbols.

### Task 3: Add key loading, session caching, and stale-session retry behavior
**Objective:** Complete protocol lifecycle support in the synchronous plugin client.

**Files:**
- Modify: `src/hermes_tescmd_plugin/client.py`
- Modify: `src/hermes_tescmd_plugin/protocol/session.py`
- Modify: `tests/test_plugin.py`

**Verification:**
- Signed security commands reuse one handshake across multiple commands.
- Stale session faults invalidate cache and retry once.

### Task 4: Update docs and packaging for signed support
**Objective:** Make publishable metadata honest about full signed support.

**Files:**
- Modify: `pyproject.toml`
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify: `src/hermes_tescmd_plugin/skills/tescmd-operator/SKILL.md`

**Verification:**
- `pytest -q`
- `python -m build` or `uv run --with build --with hatchling python -m build --sdist --wheel`
- `uv run --with twine twine check dist/*`

### Success Criteria
- No upstream `tescmd` runtime dependency
- Full signed session protocol code lives inside the plugin package
- Security and infotainment commands route through `/signed_command` with session caching
- Tests cover signed routing and session reuse
- Docs no longer claim signed protocol is missing
