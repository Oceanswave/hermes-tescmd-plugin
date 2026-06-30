(function () {
  "use strict";

  const SDK = window.__HERMES_PLUGIN_SDK__;
  if (!SDK) return;
  const React = SDK.React;
  const h = React.createElement;
  const hooks = SDK.hooks || React;
  const C = SDK.components || {};
  const Card = C.Card || "div";
  const CardHeader = C.CardHeader || "div";
  const CardTitle = C.CardTitle || "h2";
  const CardContent = C.CardContent || "div";
  const Badge = C.Badge || "span";
  const Button = C.Button || "button";
  const Input = C.Input || "input";
  const Label = C.Label || "label";

  const api = (path, options) => SDK.fetchJSON(`/api/plugins/hermes-tescmd-plugin${path}`, options);

  const READ_GROUPS = [
    ["Core", [["vehicle-status", "Vehicle"], ["drive", "Drive"], ["closures", "Closures"], ["charge", "Charge"], ["climate", "Climate"], ["location", "Location"]]],
    ["Diagnostics", [["security", "Security"], ["software", "Software"], ["config", "Config"], ["gui", "GUI"], ["alerts", "Alerts"], ["release-notes", "Release notes"]]],
    ["Services", [["nearby-chargers", "Nearby chargers"], ["energy", "Energy"], ["mobile-access", "Mobile access"], ["drivers", "Drivers"], ["service", "Service"], ["warranty", "Warranty"], ["charge-schedule", "Charge schedules"], ["preconditioning-schedule", "Preconditioning"]]],
    ["Admin", [["auth-status", "Auth"], ["onboarding", "Onboarding"], ["key-show", "Key"], ["key-validate", "Validate key"], ["cache-status", "Cache"]]],
  ];

  const ACTION_GROUPS = [
    ["Attention & security", [["wake", "Wake"], ["flash", "Flash"], ["honk", "Honk"], ["lock", "Lock"], ["unlock", "Unlock"], ["sentry", "Sentry on/off"]]],
    ["Climate", [["climate-start", "Climate start"], ["climate-stop", "Climate stop"], ["set-temp", "Set temp"], ["seat-heat-driver", "Driver seat heat"], ["seat-heat-passenger", "Passenger seat heat"], ["steering-heat-level", "Steering heat"]]],
    ["Charging", [["charge-start", "Charge start"], ["charge-stop", "Charge stop"], ["charge-limit", "Set limit"], ["charge-amps", "Set amps"], ["charge-port-open", "Port open"], ["charge-port-close", "Port close"]]],
    ["Body", [["frunk", "Frunk"], ["trunk-open", "Trunk open"], ["trunk-close", "Trunk close"], ["window-vent", "Vent windows"], ["window-close", "Close windows"]]],
    ["Media & navigation", [["media-play", "Play/pause"], ["media-next", "Next"], ["media-prev", "Previous"], ["media-volume-up", "Vol +"], ["media-volume-down", "Vol -"], ["media-volume-set", "Set volume"], ["nav", "Navigate"], ["nav-gps", "Nav GPS"], ["nav-waypoints", "Waypoints"]]],
  ];

  function JsonBlock({ data }) {
    const displayData = data && data.display_payload ? data.display_payload : data;
    return h("pre", { className: "tescmd-json" }, JSON.stringify(displayData, null, 2));
  }

  function PayloadPrivacyToolbar({ hasPayload, clearPayload }) {
    return h("div", { className: "tescmd-payload-privacy", role: "note", "aria-label": "Payload privacy controls" },
      h("div", null,
        h("span", { className: "tescmd-widget-label" }, "Local debug payload"),
        h("strong", null, hasPayload ? "Redacted payload is visible" : "No payload retained"),
        h("small", null, "The panel renders sanitized display_payload data for troubleshooting, including redacted driver personal details. Clearing it only removes dashboard-local display state; it does not call Tesla or the plugin.")
      ),
      h(Button, { onClick: clearPayload, disabled: !hasPayload }, "Clear payload panel")
    );
  }

  function Field({ label, children }) {
    return h("div", { className: "tescmd-field" }, h(Label, null, label), children);
  }

  function TextInput({ label, value, setValue, placeholder, type, min, max, step, inputMode, helpText }) {
    return h(Field, { label },
      h(Input, {
        type: type || "text",
        value: value ?? "",
        placeholder,
        min,
        max,
        step,
        inputMode,
        "aria-describedby": helpText ? `${label.toLowerCase().replace(/[^a-z0-9]+/g, "-")}-help` : undefined,
        onChange: (event) => setValue(event.target.value),
      }),
      helpText ? h("small", { id: `${label.toLowerCase().replace(/[^a-z0-9]+/g, "-")}-help`, className: "tescmd-muted" }, helpText) : null
    );
  }

  function bootstrapOperational(bootstrap) {
    return Boolean(
      bootstrap &&
      bootstrap.authenticated &&
      bootstrap.ready_for_vehicle_reads &&
      bootstrap.ready_for_vehicle_commands &&
      bootstrap.ready_for_signed_commands
    );
  }

  function readinessRows(status) {
    const bootstrap = (status && status.bootstrap) || {};
    const rows = [
      ["App", bootstrap.app_configured, "missing"],
      ["Auth", bootstrap.authenticated, "missing"],
      ["Reads", bootstrap.ready_for_vehicle_reads, "missing"],
      ["Commands", bootstrap.ready_for_vehicle_commands, "missing"],
      ["Signed", bootstrap.ready_for_signed_commands, "missing"],
    ];
    if (!bootstrapOperational(bootstrap)) rows.push(["OAuth app key", bootstrap.key_hosting_ready, "check"]);
    return rows;
  }

  function Readiness({ status }) {
    return h("div", { className: "tescmd-readiness" },
      readinessRows(status).map(([label, value, falseLabel]) =>
        h("div", { key: label, className: "tescmd-readiness-item" },
          h("span", null, label),
          h(Badge, { className: value ? "tescmd-ok" : "tescmd-warn" }, value ? "ready" : falseLabel)
        )
      )
    );
  }

  function onboardingOperational(onboarding) {
    const readiness = (onboarding && onboarding.readiness) || {};
    return bootstrapOperational(readiness);
  }

  function boundedPreview(items, limit) {
    const safeLimit = Math.max(0, Number(limit) || 0);
    const list = Array.isArray(items) ? items : [];
    return {
      visible: list.slice(0, safeLimit),
      hiddenCount: Math.max(0, list.length - safeLimit),
    };
  }

  function hiddenCountText(count, singular, plural) {
    if (!count) return "";
    return `+${count} more ${count === 1 ? singular : plural} hidden for brevity`;
  }

  function OnboardingCard({ onboarding }) {
    if (!onboarding) return null;
    const missing = Array.isArray(onboarding.missing_prerequisites)
      ? onboarding.missing_prerequisites.map((item) => sanitizeDashboardText(item, "setup item"))
      : [];
    const steps = Array.isArray(onboarding.next_steps)
      ? onboarding.next_steps.map((step) => sanitizeDashboardText(step, "setup step"))
      : [];
    if (onboardingOperational(onboarding)) return null;
    const next = sanitizeDashboardText(onboarding.next_tool || onboarding.next_action || "Ready", "Ready");
    const docsAnchor = sanitizeDashboardText(onboarding.docs_anchor || "docs/ONBOARDING.md", "docs/ONBOARDING.md");
    const missingPreview = boundedPreview(missing, 4);
    const stepsPreview = boundedPreview(steps, 2);
    const hiddenMissing = hiddenCountText(missingPreview.hiddenCount, "setup item", "setup items");
    const hiddenSteps = hiddenCountText(stepsPreview.hiddenCount, "next step", "next steps");
    return h("div", { className: "tescmd-onboarding-card" },
      h("div", null,
        h("span", { className: "tescmd-widget-label" }, "Next setup step"),
        h("strong", null, next),
        h("small", null, docsAnchor)
      ),
      missing.length
        ? h("div", { className: "tescmd-missing-list" },
          missingPreview.visible.map((item, index) => h(Badge, { key: `${item}-${index}`, className: "tescmd-warn" }, item)),
          hiddenMissing ? h(Badge, { className: "tescmd-warn" }, hiddenMissing) : null
        )
        : h(Badge, { className: "tescmd-ok" }, "no missing prerequisites"),
      stepsPreview.visible.length ? h("ol", null, stepsPreview.visible.map((step, index) => h("li", { key: index }, step))) : null,
      hiddenSteps ? h("small", { className: "tescmd-muted" }, hiddenSteps) : null,
      h("small", { className: "tescmd-muted" }, "Setup guidance is sanitized before display; OAuth values, vehicle identifiers, and precise route/location details stay hidden. Hidden counts describe omitted sanitized guidance without revealing raw values.")
    );
  }

  function scopeReadinessFromStatus(status) {
    const bootstrap = (status && status.bootstrap) || {};
    return bootstrap.scope_readiness || null;
  }

  function scopeCapabilityRows(scopeReadiness) {
    const capabilities = (scopeReadiness && scopeReadiness.capabilities) || {};
    return Object.entries(capabilities).map(([name, payload]) => {
      const missing = Array.isArray(payload && payload.missing_scopes)
        ? payload.missing_scopes.map((item) => sanitizeDashboardText(item, "scope"))
        : [];
      return {
        name: sanitizeDashboardText(String(name).replace(/_/g, " "), "capability"),
        ready: Boolean(payload && payload.ready),
        missing,
      };
    });
  }

  function scopeNeedsText(missing) {
    const preview = boundedPreview(missing, 3);
    if (!preview.visible.length) return "scope";
    const hidden = preview.hiddenCount ? `, +${preview.hiddenCount} more` : "";
    return `${preview.visible.join(", ")}${hidden}`;
  }

  function ScopeReadinessPanel({ status }) {
    const scopeReadiness = scopeReadinessFromStatus(status);
    if (!scopeReadiness) return null;
    const grantSource = sanitizeDashboardText(scopeReadiness.grant_scope_source || "unknown", "unknown");
    const missingGranted = Array.isArray(scopeReadiness.missing_granted_user_scopes)
      ? scopeReadiness.missing_granted_user_scopes.map((item) => sanitizeDashboardText(item, "scope"))
      : [];
    const capabilities = scopeCapabilityRows(scopeReadiness);
    const blocked = missingGranted.length > 0 || capabilities.some((item) => !item.ready);
    const missingGrantedPreview = boundedPreview(missingGranted, 4);
    const capabilitiesPreview = boundedPreview(capabilities, 4);
    const hiddenMissingGranted = hiddenCountText(missingGrantedPreview.hiddenCount, "missing granted scope", "missing granted scopes");
    const hiddenCapabilities = hiddenCountText(capabilitiesPreview.hiddenCount, "capability", "capabilities");
    return h("div", { className: blocked ? "tescmd-scope-readiness tescmd-scope-readiness-warn" : "tescmd-scope-readiness", role: "status", "aria-live": "polite" },
      h("div", null,
        h("span", { className: "tescmd-widget-label" }, "OAuth scope readiness"),
        h("strong", null, blocked ? "Some Tesla capabilities need scopes" : "Tesla OAuth scopes look ready"),
        h("small", null, `Scope source: ${grantSource}. Missing scope names are shown without tokens, vehicle identifiers, or callback values.`)
      ),
      h("div", { className: "tescmd-scope-grid" },
        missingGranted.length
          ? h("div", { className: "tescmd-scope-missing" },
            h("span", null, "Missing granted"),
            missingGrantedPreview.visible.map((scope) => h(Badge, { key: scope, className: "tescmd-warn" }, scope)),
            hiddenMissingGranted ? h(Badge, { className: "tescmd-warn" }, hiddenMissingGranted) : null
          )
          : h(Badge, { className: "tescmd-ok" }, "no missing granted scopes"),
        capabilitiesPreview.visible.map((item) => h("div", { key: item.name, className: "tescmd-scope-capability" },
          h("span", null, item.name),
          h(Badge, { className: item.ready ? "tescmd-ok" : "tescmd-warn" }, item.ready ? "ready" : `needs ${scopeNeedsText(item.missing)}`)
        )),
        hiddenCapabilities ? h("small", { className: "tescmd-muted" }, hiddenCapabilities) : null
      ),
      hiddenMissingGranted || hiddenCapabilities
        ? h("small", { className: "tescmd-muted" }, "Hidden scope-readiness counts describe omitted sanitized scopes/capabilities without exposing raw tokens, callbacks, or vehicle identifiers.")
        : null
    );
  }

  function BusyBanner({ loading, mode }) {
    if (!loading) return null;
    const initial = mode === "initial";
    return h("div", { className: "tescmd-busy-banner", role: "status", "aria-live": "polite" },
      h("strong", null, initial ? "Loading Tesla dashboard…" : "Updating Tesla data…"),
      h("span", null, initial ? "Fetching setup and vehicle status." : "This can take a moment while Tesla responds.")
    );
  }

  function EmptyState({ title, body, steps, note, action }) {
    return h("div", { className: "tescmd-empty-state", role: "region", "aria-label": title },
      h("div", { className: "tescmd-empty-icon", "aria-hidden": "true" }, "⚡"),
      h("div", { className: "tescmd-empty-copy" },
        h("strong", null, title),
        h("p", null, body),
        Array.isArray(steps) && steps.length
          ? h("ol", null, steps.map((step, index) => h("li", { key: index }, step)))
          : null,
        note ? h("small", null, note) : null
      ),
      action ? h("div", { className: "tescmd-empty-action" }, action) : null
    );
  }

  function redactVisibleIdentifierText(value) {
    return String(value ?? "")
      .replace(/Bearer\s+[^\s,;]+/gi, "Bearer [REDACTED]")
      .replace(/\b[A-HJ-NPR-Z0-9]{17}\b/g, (match) => `…${match.slice(-4)}`)
      .replace(/\b\d{12,20}\b/g, (match) => `…${match.slice(-4)}`);
  }

  function sanitizeDashboardText(value, fallback) {
    const rawText = String(value ?? "").trim();
    if (!rawText) return fallback || "";
    const secretKeys = "code|state|access_token|refresh_token|id_token|client_id|client_secret|code_verifier|code_challenge|token|pin";
    const secretValuePattern = "(\\\"[^\\\"]*\\\"|'[^']*'|[^,;})\\]\\s]+)";
    const text = redactVisibleIdentifierText(rawText)
      .replace(new RegExp(`([?#&](?:${secretKeys})=)[^&\\s#]+`, "gi"), "$1[REDACTED]")
      .replace(new RegExp(`(^|[\\s,;({\\[])((?:${secretKeys})\\s*=\\s*)${secretValuePattern}`, "gi"), (_match, prefix, key) => `${prefix}${key}[REDACTED]`)
      .replace(new RegExp(`(^|[\\s,;({\\[])(["']?(?:${secretKeys})["']?\\s*:\\s*)${secretValuePattern}`, "gi"), (_match, prefix, key) => `${prefix}${key}[REDACTED]`)
      .replace(/\b(?:lat(?:itude)?|lon(?:gitude)?|lng)\s*[:=]\s*-?\d+(?:\.\d+)?/gi, (match) => match.replace(/-?\d+(?:\.\d+)?/, "[REDACTED]"))
      .replace(/\b-?\d{1,2}\.\d{3,}\s*,\s*-?\d{1,3}\.\d{3,}\b/g, "[coordinates redacted]")
      .replace(/\b(destination|address|query|place_id|place_ids)\b\s*[:=]\s*("[^"]*"|'[^']*'|[^,;}\n]+)/gi, "$1=[REDACTED]");
    return text || fallback || "";
  }

  function visibleVehicleText(value, fallback) {
    return sanitizeDashboardText(value, fallback);
  }

  function dashboardErrorMessage(err) {
    return sanitizeDashboardText((err && err.message) || err, "Tesla dashboard request failed.");
  }

  function vehicleModelHint(vehicle) {
    const config = (vehicle && vehicle.vehicle_config) || {};
    const hints = [
      config.car_type,
      config.trim_badging,
      config.exterior_color,
      vehicle && vehicle.model,
      vehicle && vehicle.car_type,
    ].filter((value) => value !== undefined && value !== null && String(value).trim() !== "")
      .map((value) => redactVisibleIdentifierText(String(value).replace(/_/g, " ")));
    const unique = [...new Set(hints)];
    return unique.slice(0, 2).join(" · ");
  }

  function vehiclePickerLabel(vehicle, index) {
    const name = visibleVehicleText(vehicle.display_name || vehicle.vehicle_name || vehicle.name, `Vehicle ${index + 1}`);
    const state = visibleVehicleText(vehicle.state || "unknown", "unknown");
    const hint = vehicleModelHint(vehicle);
    return hint ? `${name} — ${hint} — ${state}` : `${name} — ${state}`;
  }

  function vehicleIdentitySummary(overview) {
    const vehicle = selectedVehicle(overview) || {};
    const vehiclesPayload = (overview && overview.vehicles) || {};
    const vehicles = Array.isArray(vehiclesPayload.vehicles) ? vehiclesPayload.vehicles : [];
    const index = vehicles.indexOf(vehicle);
    const name = visibleVehicleText(vehicle.display_name || vehicle.vehicle_name || vehicle.name, index >= 0 ? `Vehicle ${index + 1}` : "Configured vehicle");
    const state = visibleVehicleText(vehicle.state || "unknown", "unknown");
    const hint = vehicleModelHint(vehicle) || "model hint unavailable";
    const source = overview && overview.vin ? "Vehicle override active" : "Configured default target";
    return { name, state, hint, source };
  }

  function VehicleIdentityCard({ identity }) {
    return h("div", { className: "tescmd-identity-card", "aria-label": "Selected Tesla target" },
      h("div", null,
        h("span", { className: "tescmd-widget-label" }, "Selected target"),
        h("strong", null, identity.name),
        h("small", null, identity.hint)
      ),
      h("div", { className: "tescmd-identity-meta" },
        h(Badge, { className: identity.state === "online" ? "tescmd-ok" : "tescmd-warn" }, identity.state),
        h("small", null, identity.source),
        h("small", null, "Visible target summary omits VIN and Fleet IDs; use the vehicle menu to change target safely.")
      )
    );
  }

  function VehiclePicker({ vehicles, vin, setVin, setDefaultVehicle, loading }) {
    const list = Array.isArray(vehicles) ? vehicles : [];
    const [showIdentifier, setShowIdentifier] = hooks.useState(false);
    return h(Field, { label: "Vehicle" },
      h("select", {
        className: "tescmd-select",
        value: vin || "",
        onChange: (event) => setVin(event.target.value),
      },
        h("option", { value: "" }, "Configured default"),
        list.map((vehicle, index) => {
          const id = vehicle.id_s || vehicle.vehicle_id || vehicle.id || vehicle.vin || "";
          return h("option", { key: `${id}-${index}`, value: id }, vehiclePickerLabel(vehicle, index));
        })
      ),
      h("div", { className: "tescmd-identifier-entry" },
        h(Input, {
          type: showIdentifier ? "text" : "password",
          placeholder: "VIN or id_s override",
          value: vin || "",
          autoComplete: "off",
          spellCheck: false,
          "aria-label": "Vehicle identifier override, hidden by default",
          onChange: (event) => setVin(event.target.value),
        }),
        h(Button, {
          type: "button",
          onClick: () => setShowIdentifier(!showIdentifier),
          disabled: !vin,
          "aria-pressed": showIdentifier,
        }, showIdentifier ? "Hide identifier" : "Reveal identifier")
      ),
      h("div", { className: "tescmd-inline-actions" },
        h(Button, { onClick: () => setDefaultVehicle(vin), disabled: loading || !vin }, "Make selected default"),
        h(Button, { onClick: () => setDefaultVehicle(""), disabled: loading }, "Clear dashboard default")
      ),
      h("small", { className: "tescmd-muted" }, "Vehicle menu labels show safe model hints only; the raw override field is hidden by default and never echoed in surrounding dashboard copy. Saving a default stores the selected identifier in plugin config while visible text stays redacted.")
    );
  }

  function TargetContextPanel({ targetContext }) {
    if (!targetContext) return null;
    const usingOverride = Boolean(targetContext.using_override);
    const configuredDefault = sanitizeDashboardText(targetContext.configured_default, "not configured");
    const override = sanitizeDashboardText(targetContext.target_override, "none");
    const region = sanitizeDashboardText(targetContext.region || "configured", "configured");
    return h("div", { className: usingOverride ? "tescmd-target-context tescmd-target-context-override" : "tescmd-target-context", role: "note", "aria-label": "Dashboard target context" },
      h("div", null,
        h("span", { className: "tescmd-widget-label" }, "Target context"),
        h("strong", null, usingOverride ? "Temporary vehicle override active" : "Using configured default target"),
        h("small", null, "Target identifiers are redacted here; the dashboard shows only whether reads use the configured default or a temporary override.")
      ),
      h("div", { className: "tescmd-target-context-grid" },
        h("div", null, h("span", null, "Region"), h(Badge, { className: "tescmd-ok" }, region)),
        h("div", null, h("span", null, "Configured default"), h(Badge, { className: configuredDefault === "not configured" ? "tescmd-warn" : "tescmd-ok" }, configuredDefault)),
        h("div", null, h("span", null, "Override"), h(Badge, { className: usingOverride ? "tescmd-warn" : "tescmd-ok" }, override))
      )
    );
  }

  function ReadContextPanel({ readContext }) {
    if (!readContext) return null;
    const cacheMode = sanitizeDashboardText(readContext.cache_mode || "cache allowed", "cache allowed");
    const unitsMode = sanitizeDashboardText(readContext.units || "configured", "configured");
    const sectionCount = Number(readContext.section_count) || 0;
    const wakeFree = readContext.overview_reads_wake === false && readContext.overview_reads_confirm === false;
    const privacyNote = sanitizeDashboardText(readContext.privacy_note, "Overview refresh metadata is privacy-safe.");
    return h("div", { className: "tescmd-read-context", role: "note", "aria-label": "Overview read context" },
      h("div", null,
        h("span", { className: "tescmd-widget-label" }, "Overview read context"),
        h("strong", null, wakeFree ? "Overview refreshes stay read-only" : "Overview refresh has elevated read flags"),
        h("small", null, privacyNote)
      ),
      h("div", { className: "tescmd-read-context-grid" },
        h("div", null, h("span", null, "Wake/confirm"), h(Badge, { className: wakeFree ? "tescmd-ok" : "tescmd-warn" }, wakeFree ? "off" : "enabled")),
        h("div", null, h("span", null, "Cache"), h(Badge, { className: cacheMode.includes("fresh") ? "tescmd-warn" : "tescmd-ok" }, cacheMode)),
        h("div", null, h("span", null, "Units"), h(Badge, null, unitsMode)),
        h("div", null, h("span", null, "Sections"), h(Badge, null, sectionCount ? `${sectionCount} reads` : "configured"))
      )
    );
  }

  function actionGroupSafetyNote(title) {
    const notes = {
      "Attention & security": "Wake, lock, unlock, honk, flash, and Sentry controls can affect access or alert people near the vehicle.",
      "Climate": "Climate buttons can wake the vehicle and change cabin temperature; requested temperatures are summarized without identifiers.",
      "Charging": "Charging buttons can start, stop, or change limits/amps; success banners avoid VINs, Fleet IDs, and raw request JSON.",
      "Body": "Body controls actuate trunks, windows, or closures. Confirm the vehicle is in a safe location before sending.",
      "Media & navigation": "Media changes audio state; navigation route targets are temporary sensitive fields and are cleared after attempts.",
    };
    return notes[title] || "Quick actions require confirmation and use sanitized dashboard result summaries.";
  }

  function ActionGroup({ title, actions, runAction, loading, confirm, actionDisabledReason }) {
    const actionStates = actions.map(([action, label]) => {
      const reason = actionDisabledReason ? actionDisabledReason(action) : "";
      return { action, label, reason, disabled: loading || !confirm || Boolean(reason) };
    });
    const blockedActions = actionStates.filter((item) => item.reason);
    return h("div", { className: "tescmd-group" },
      h("div", { className: "tescmd-action-group-heading" },
        h("h3", null, title),
        h("small", null, actionGroupSafetyNote(title))
      ),
      h("div", { className: "tescmd-actions" },
        actionStates.map(({ action, label, reason, disabled }) =>
          h(Button, {
            key: action,
            onClick: () => runAction(action),
            disabled,
            title: reason || (!confirm ? "Turn on confirmation before physical Tesla actions." : undefined),
            "aria-describedby": reason ? `tescmd-action-blocker-${action}` : undefined,
          }, label)
        )
      ),
      blockedActions.length
        ? h("div", { className: "tescmd-action-blockers", role: "note", "aria-label": `${title} disabled action reasons` },
          h("span", { className: "tescmd-widget-label" }, "Why some buttons are disabled"),
          blockedActions.map(({ action, label, reason }) => h("small", { key: action, id: `tescmd-action-blocker-${action}` }, `${label}: ${reason}`))
        )
        : null
    );
  }

  function ReadGroup({ title, reads, runRead, loading }) {
    return h("div", { className: "tescmd-group" },
      h("h3", null, title),
      h("div", { className: "tescmd-actions" },
        reads.map(([kind, label]) => h(Button, { key: kind, onClick: () => runRead(kind), disabled: loading }, label))
      )
    );
  }

  function ActionSafetyPanel({ confirm, loading, lastActionStatus }) {
    const armed = Boolean(confirm);
    return h("div", { className: armed ? "tescmd-action-safety tescmd-action-safety-armed" : "tescmd-action-safety", role: "status", "aria-live": "polite" },
      h("div", { className: "tescmd-action-safety-icon", "aria-hidden": "true" }, armed ? "↯" : "○"),
      h("div", null,
        h("strong", null, armed ? "Physical actions are armed" : "Physical actions are locked"),
        h("p", null, armed
          ? "Buttons below can wake or change the vehicle. Confirmation automatically turns off after one quick action."
          : "Read panels stay available, but wake, security, charging, climate, body, media, and navigation actions require the confirmation checkbox."),
        loading ? h("small", null, "Tesla is processing the current dashboard request.") : null,
        lastActionStatus ? h("small", { className: "tescmd-muted" }, lastActionStatus) : null
      )
    );
  }

  function ReadSafetyPanel({ wakeReads, confirm }) {
    const wakeRequested = Boolean(wakeReads);
    const confirmArmed = Boolean(confirm);
    const wakeWillRun = wakeRequested && confirmArmed;
    return h("div", { className: wakeWillRun ? "tescmd-read-safety tescmd-read-safety-wake" : "tescmd-read-safety", role: "note", "aria-label": "Read safety guardrails" },
      h("div", null,
        h("span", { className: "tescmd-widget-label" }, "Read safety"),
        h("strong", null, wakeWillRun ? "Wake-enabled reads are armed" : "Reads are non-waking"),
        h("small", null, wakeWillRun
          ? "A read can wake a sleeping vehicle because wake and confirmation are both enabled."
          : wakeRequested
            ? "Wake is requested, but the dashboard will not send wake-enabled reads until physical-action confirmation is also checked."
            : "Read buttons fetch cached or available Tesla data without arming physical side effects.")
      ),
      h("div", { className: "tescmd-read-safety-badges" },
        h(Badge, { className: wakeRequested ? "tescmd-warn" : "tescmd-ok" }, wakeRequested ? "wake requested" : "wake off"),
        h(Badge, { className: confirmArmed ? "tescmd-warn" : "tescmd-ok" }, confirmArmed ? "confirmation armed" : "confirmation locked"),
        h(Badge, { className: wakeWillRun ? "tescmd-warn" : "tescmd-ok" }, wakeWillRun ? "wake-capable read" : "fail-closed read")
      )
    );
  }

  function routeReadiness(destination, lat, lon, placeIds) {
    const hasDestination = String(destination || "").trim() !== "";
    const hasLat = String(lat || "").trim() !== "";
    const hasLon = String(lon || "").trim() !== "";
    const latitudeReady = boundedNumberReady(lat, -90, 90);
    const longitudeReady = boundedNumberReady(lon, -180, 180);
    const waypointCount = String(placeIds || "").split(",").map((value) => value.trim()).filter(Boolean).length;
    return {
      navReady: hasDestination,
      gpsReady: latitudeReady && longitudeReady,
      gpsFieldsPresent: hasLat || hasLon,
      gpsFieldsComplete: hasLat && hasLon,
      latitudeReady,
      longitudeReady,
      waypointReady: waypointCount > 0,
      waypointCount,
      routeFieldsPresent: hasDestination || (hasLat && hasLon) || waypointCount > 0,
    };
  }

  function numericTextReady(text) {
    if (text === "" || text === null || text === undefined) return false;
    return Number.isFinite(Number(text));
  }

  function boundedNumberReady(text, min, max) {
    if (!numericTextReady(text)) return false;
    const value = Number(text);
    return value >= min && value <= max;
  }

  function controlReadiness(percent, amps, driverTemp, passengerTemp, volume, heaterLevel) {
    const driverReady = boundedNumberReady(driverTemp, 50, 90);
    const passengerReady = boundedNumberReady(passengerTemp, 50, 90);
    return {
      chargeLimitReady: boundedNumberReady(percent, 1, 100),
      chargeAmpsReady: boundedNumberReady(amps, 1, 80),
      temperatureReady: driverReady && passengerReady,
      heaterLevelReady: boundedNumberReady(heaterLevel, 0, 3),
      volumeReady: boundedNumberReady(volume, 0, 11),
    };
  }

  function NavigationGuardPanel({ destination, lat, lon, placeIds, clearRouteFields }) {
    const readiness = routeReadiness(destination, lat, lon, placeIds);
    return h("div", { className: "tescmd-nav-guard", role: "note", "aria-label": "Navigation action guardrails" },
      h("div", null,
        h("span", { className: "tescmd-widget-label" }, "Navigation guardrail"),
        h("strong", null, readiness.routeFieldsPresent ? "Route fields ready" : "No route target entered"),
        h("small", null, "Navigation buttons stay unavailable until their required destination fields are present. Route text, coordinates, and place IDs are treated as temporary sensitive state.")
      ),
      h("div", { className: "tescmd-nav-guard-badges" },
        h(Badge, { className: readiness.navReady ? "tescmd-ok" : "tescmd-warn" }, readiness.navReady ? "destination set" : "destination needed"),
        h(Badge, { className: readiness.gpsReady ? "tescmd-ok" : "tescmd-warn" }, readiness.gpsReady ? "GPS pair in range" : readiness.gpsFieldsPresent ? "GPS range needed" : "lat/lon needed"),
        h(Badge, { className: readiness.waypointReady ? "tescmd-ok" : "tescmd-warn" }, readiness.waypointReady ? `${readiness.waypointCount} waypoint${readiness.waypointCount === 1 ? "" : "s"}` : "place IDs needed")
      ),
      h("div", { className: "tescmd-nav-guard-actions" },
        h(Button, { onClick: clearRouteFields, disabled: !readiness.routeFieldsPresent }, "Clear route fields"),
        h("small", { className: "tescmd-muted" }, "Clearing only edits dashboard form state; it does not call Tesla or the plugin.")
      )
    );
  }

  function ActionRequirementsPanel({ confirm, destination, lat, lon, placeIds, percent, amps, driverTemp, passengerTemp, volume, heaterLevel }) {
    const readiness = routeReadiness(destination, lat, lon, placeIds);
    const controls = controlReadiness(percent, amps, driverTemp, passengerTemp, volume, heaterLevel);
    const requirements = [
      ["Physical confirmation", Boolean(confirm), confirm ? "armed for one action" : "check the confirmation box before any physical action"],
      ["Charge limit", controls.chargeLimitReady, controls.chargeLimitReady ? "percent ready" : "enter a charge limit from 1 to 100"],
      ["Charge amps", controls.chargeAmpsReady, controls.chargeAmpsReady ? "amps ready" : "enter charging amps from 1 to 80"],
      ["Cabin temperatures", controls.temperatureReady, controls.temperatureReady ? "temperatures ready" : "enter driver and passenger temperatures from 50° to 90°"],
      ["Seat/steering heat", controls.heaterLevelReady, controls.heaterLevelReady ? "heater level ready" : "enter a heater level from 0 to 3"],
      ["Media volume", controls.volumeReady, controls.volumeReady ? "volume ready" : "enter a volume level from 0 to 11"],
      ["Navigate", readiness.navReady, readiness.navReady ? "destination ready" : "enter a destination"],
      ["GPS navigation", readiness.gpsReady, readiness.gpsReady ? "latitude/longitude in range" : readiness.gpsFieldsComplete ? "enter latitude from -90 to 90 and longitude from -180 to 180" : "enter both latitude and longitude"],
      ["Waypoints", readiness.waypointReady, readiness.waypointReady ? `${readiness.waypointCount} place ID${readiness.waypointCount === 1 ? "" : "s"} ready` : "enter at least one place ID"],
    ];
    const blockedCount = requirements.filter((item) => !item[1]).length;
    return h("div", { className: blockedCount ? "tescmd-action-requirements tescmd-action-requirements-warn" : "tescmd-action-requirements", role: "note", "aria-label": "Quick action readiness checklist" },
      h("div", null,
        h("span", { className: "tescmd-widget-label" }, "Action readiness"),
        h("strong", null, blockedCount ? `${blockedCount} guardrail${blockedCount === 1 ? "" : "s"} still blocking some buttons` : "All quick-action guardrails are satisfied"),
        h("small", null, "Disabled-button reasons are shown here without echoing destinations, coordinates, place IDs, VINs, or Fleet IDs.")
      ),
      h("div", { className: "tescmd-action-requirement-list" },
        requirements.map(([label, ready, copy]) => h("div", { key: label, className: "tescmd-action-requirement" },
          h("span", null, label),
          h(Badge, { className: ready ? "tescmd-ok" : "tescmd-warn" }, copy)
        ))
      )
    );
  }

  function objectAt(payload, keys) {
    for (const key of keys) {
      if (payload && typeof payload === "object" && payload[key] && typeof payload[key] === "object") return payload[key];
      if (payload && payload.data && typeof payload.data === "object" && payload.data[key] && typeof payload.data[key] === "object") return payload.data[key];
    }
    return {};
  }

  function firstDefined(...values) {
    return values.find((value) => value !== undefined && value !== null && value !== "");
  }

  function numericValue(...values) {
    const value = firstDefined(...values);
    if (value === undefined) return null;
    const number = Number(value);
    return Number.isFinite(number) ? number : null;
  }

  function section(overview, key) {
    return (overview && overview.sections && overview.sections[key]) || {};
  }

  function chargeSummary(overview) {
    const charge = objectAt(section(overview, "charge"), ["charge_state"]);
    const level = numericValue(charge.battery_level, charge.usable_battery_level, charge.soc, charge.battery_soc);
    const limit = numericValue(charge.charge_limit_soc, charge.charge_limit_soc_std, charge.charge_limit_soc_min);
    const range = numericValue(charge.battery_range, charge.est_battery_range, charge.ideal_battery_range);
    const power = numericValue(charge.charger_power, charge.charge_rate);
    return { level, limit, range, power, state: firstDefined(charge.charging_state, charge.charge_state, "unknown") };
  }

  function climateSummary(overview) {
    const climate = objectAt(section(overview, "climate"), ["climate_state"]);
    return {
      inside: numericValue(climate.inside_temp),
      outside: numericValue(climate.outside_temp),
      target: numericValue(climate.driver_temp_setting, climate.passenger_temp_setting),
      on: Boolean(firstDefined(climate.is_climate_on, climate.climate_keeper_mode && climate.climate_keeper_mode !== "off")),
    };
  }

  const closureLabels = {
    df: "driver front door",
    pf: "passenger front door",
    dr: "driver rear door",
    pr: "passenger rear door",
    ft: "front trunk",
    rt: "rear trunk",
    fd_window: "driver front window",
    fp_window: "passenger front window",
    rd_window: "driver rear window",
    rp_window: "passenger rear window",
  };

  function closureIsOpen(value) {
    if (value === true || value === 1) return true;
    if (value === false || value === 0 || value == null) return false;
    const normalized = String(value).trim().toLowerCase();
    if (["open", "opened", "ajar", "vent", "vented", "true", "1"].includes(normalized)) return true;
    if (["closed", "close", "off", "false", "0", "locked"].includes(normalized)) return false;
    return Boolean(normalized);
  }

  function securitySummary(overview) {
    const security = objectAt(section(overview, "security"), ["vehicle_state", "security_state"]);
    const closures = objectAt(section(overview, "closures"), ["closures_state", "vehicle_state"]);
    const locked = firstDefined(security.locked, closures.locked);
    const sentry = firstDefined(security.sentry_mode, security.sentry_mode_available && security.sentry_mode);
    const openLabels = Object.entries(closureLabels)
      .filter(([key]) => closureIsOpen(closures[key]))
      .map(([, label]) => label);
    return { locked, sentry, openCount: openLabels.length, openLabels };
  }

  function locationSummary(overview) {
    const location = objectAt(section(overview, "location"), ["location", "location_data", "drive_state"]);
    const drive = objectAt(section(overview, "drive"), ["drive_state", "location_data"]);
    const lat = numericValue(location.latitude, location.lat, drive.latitude, drive.lat);
    const lon = numericValue(location.longitude, location.lon, location.lng, drive.longitude, drive.lon, drive.lng);
    const heading = numericValue(location.heading, location.vehicle_heading, drive.heading, drive.vehicle_heading);
    const speed = numericValue(drive.speed, location.speed);
    return { lat, lon, heading, speed, raw: Object.keys(location).length ? location : drive };
  }

  function compassHeadingLabel(heading) {
    if (heading == null) return "heading unavailable";
    const normalized = ((Number(heading) % 360) + 360) % 360;
    const directions = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"];
    const index = Math.round(normalized / 45) % directions.length;
    return `heading ${Math.round(normalized)}° ${directions[index]}`;
  }

  function displayLocation(location, precision) {
    const lat = location && location.lat;
    const lon = location && location.lon;
    if (lat == null || lon == null) return { lat: null, lon: null, label: "No coordinates", note: "Speed and heading unavailable", precise: false };
    const precise = precision === "precise";
    const displayLat = precise ? lat : Number(lat.toFixed(2));
    const displayLon = precise ? lon : Number(lon.toFixed(2));
    const coordLabel = precise
      ? `${lat.toFixed(5)}, ${lon.toFixed(5)}`
      : `≈ ${displayLat.toFixed(2)}, ${displayLon.toFixed(2)}`;
    const speedNote = location.speed == null ? "speed unavailable" : `${location.speed} mph`;
    const headingNote = compassHeadingLabel(location.heading);
    return {
      lat: displayLat,
      lon: displayLon,
      label: coordLabel,
      note: precise ? `${speedNote} · ${headingNote} · precise coordinates visible` : `${speedNote} · ${headingNote} · precise coordinates hidden`,
      precise,
      zoom: precise ? 14 : 10,
      popup: precise ? "Vehicle location" : "Approximate vehicle area",
    };
  }

  function selectedVehicle(overview) {
    const vehiclesPayload = (overview && overview.vehicles) || {};
    const vehicles = Array.isArray(vehiclesPayload.vehicles) ? vehiclesPayload.vehicles : [];
    const target = overview && overview.vin ? String(overview.vin) : "";
    if (target) {
      return vehicles.find((vehicle) => [vehicle.id_s, vehicle.vehicle_id, vehicle.id, vehicle.vin].some((id) => id != null && String(id) === target)) || null;
    }
    return vehicles.find((vehicle) => String(vehicle.state || "").toLowerCase() === "asleep") || vehicles[0] || null;
  }

  function sectionErrorText(overview) {
    const sections = (overview && overview.sections) || {};
    return Object.values(sections).map((payload) => {
      if (!payload || typeof payload !== "object") return "";
      const nested = payload.payload && typeof payload.payload === "object" ? payload.payload.error : "";
      return [payload.error, nested].filter(Boolean).join(" ");
    }).join(" ").toLowerCase();
  }

  function sectionIssueLabel(payload) {
    const raw = [
      payload && payload.error,
      payload && payload.message,
      payload && payload.payload && payload.payload.error,
      payload && payload.response && payload.response.error,
    ].filter(Boolean).join(" ").toLowerCase();
    const status = firstDefined(payload && payload.status_code, payload && payload.response && payload.response.status_code);
    let reason = "read failed";
    if (raw.includes("login") || raw.includes("auth") || raw.includes("token")) reason = "auth/login required";
    else if (raw.includes("asleep")) reason = "vehicle asleep";
    else if (raw.includes("offline") || raw.includes("unavailable")) reason = "vehicle unavailable";
    else if (raw.includes("scope")) reason = "missing scope";
    else if (raw.includes("rate") || status === 429) reason = "rate limited";
    else if (raw.includes("config") || raw.includes("setup")) reason = "setup/config needed";
    return status ? `${reason} · status ${status}` : reason;
  }

  function sectionHealthItems(overview) {
    const serverIssues = overview && overview.section_health && Array.isArray(overview.section_health.issues)
      ? overview.section_health.issues
      : null;
    if (serverIssues) {
      return serverIssues.map((item) => ({
        name: visibleVehicleText(item && item.name, "section"),
        reason: visibleVehicleText(item && item.reason, "read failed"),
      }));
    }
    const sections = (overview && overview.sections) || {};
    return Object.entries(sections).filter(([, payload]) => {
      if (!payload || typeof payload !== "object") return false;
      const nestedError = payload.payload && typeof payload.payload === "object" && payload.payload.error;
      return payload.ok === false || Boolean(payload.error) || Boolean(nestedError);
    }).map(([name, payload]) => ({ name: visibleVehicleText(name.replace(/-/g, " "), "section"), reason: sectionIssueLabel(payload) }));
  }

  function SectionHealthPanel({ overview }) {
    const issues = sectionHealthItems(overview);
    const shownIssues = issues.slice(0, 6);
    const hiddenCount = Math.max(0, issues.length - shownIssues.length);
    return h("div", { className: issues.length ? "tescmd-section-health tescmd-section-health-warn" : "tescmd-section-health", role: "status", "aria-live": "polite" },
      h("div", null,
        h("span", { className: "tescmd-widget-label" }, "Read health"),
        h("strong", null, issues.length ? `${issues.length} overview read issue${issues.length === 1 ? "" : "s"}` : "Overview reads look clean"),
        h("small", null, issues.length
          ? ((overview && overview.section_health && overview.section_health.privacy_note) || "Section errors are summarized without VINs, tokens, destinations, or precise location data. Use the redacted payload panel for detail.")
          : "No failed overview read sections were reported in the latest dashboard payload.")
      ),
      issues.length ? h("ul", null,
        shownIssues.map((item) => h("li", { key: item.name }, h("span", null, item.name), h(Badge, { className: "tescmd-warn" }, item.reason))),
        hiddenCount ? h("li", { key: "more" }, h(Badge, { className: "tescmd-warn" }, `+${hiddenCount} more`)) : null
      ) : h(Badge, { className: "tescmd-ok" }, "all sections ok")
    );
  }

  function displayPayload(detail) {
    return detail && detail.display_payload ? detail.display_payload : (detail || {});
  }

  function nestedPayload(detail) {
    const payload = displayPayload(detail);
    return payload.response || payload.data || payload.service || payload.mobile_access || payload;
  }

  function arrayCount(payload, keys) {
    for (const key of keys) {
      const value = payload && payload[key];
      if (Array.isArray(value)) return value.length;
      if (Number.isFinite(Number(value))) return Number(value);
    }
    return null;
  }

  function booleanLabel(value) {
    if (value === true || value === "true" || value === "enabled") return "enabled";
    if (value === false || value === "false" || value === "disabled") return "disabled";
    return "unknown";
  }

  function yesNoUnknown(value) {
    if (value === true || value === "true" || value === "yes" || value === "ready") return "yes";
    if (value === false || value === "false" || value === "no" || value === "missing") return "no";
    return "unknown";
  }

  function setupReadinessValue(payload, key) {
    const bootstrap = (payload && payload.bootstrap) || {};
    const readiness = (payload && payload.readiness) || {};
    return firstDefined(payload && payload[key], bootstrap[key], readiness[key]);
  }

  function cacheValue(payload, ...keys) {
    const status = payload && payload.cache_status;
    for (const container of [payload, payload && payload.response, payload && payload.data, status]) {
      if (!container || typeof container !== "object" || Array.isArray(container)) continue;
      for (const key of keys) {
        if (container[key] !== undefined && container[key] !== null && String(container[key]).trim() !== "") return container[key];
      }
    }
    return undefined;
  }

  function cacheCountLabel(label, value, pluralLabel) {
    const count = numericValue(value);
    const unit = count === 1 ? label : (pluralLabel || `${label}s`);
    if (count == null) return `${label} unknown`;
    return `${count} ${unit}`;
  }

  function cacheFreshnessLabel(payload) {
    const stale = cacheValue(payload, "stale_entries", "stale_count", "expired_entries", "expired_count");
    const newest = cacheValue(payload, "newest_age_seconds", "freshest_age_seconds", "youngest_age_seconds", "last_refresh_age_seconds", "age_seconds");
    const oldest = cacheValue(payload, "oldest_age_seconds", "oldest_entry_age_seconds", "max_age_seconds");
    const nextExpiry = cacheValue(payload, "next_expiry_seconds", "next_expires_in_seconds", "expires_in_seconds");
    const ttl = cacheValue(payload, "ttl_seconds", "cache_ttl_seconds");
    if (newest !== undefined) return `freshest ${sanitizeDashboardText(newest, "age unknown")}s old`;
    if (oldest !== undefined) return `oldest ${sanitizeDashboardText(oldest, "age unknown")}s old`;
    if (nextExpiry !== undefined) return `next expiry ${sanitizeDashboardText(nextExpiry, "expiry unknown")}s`;
    if (ttl !== undefined) return `ttl ${sanitizeDashboardText(ttl, "ttl unknown")}s`;
    if (stale !== undefined) return cacheCountLabel("stale/expired entry", stale, "stale/expired entries");
    return "freshness unknown";
  }

  function cacheModeLabel(payload) {
    const enabled = yesNoUnknown(cacheValue(payload, "enabled", "cache_enabled"));
    const entries = cacheValue(payload, "entries", "entry_count", "count", "current_entries");
    const expired = cacheValue(payload, "expired_entries", "expired_count", "stale_entries", "stale_count") ?? 0;
    return `cache ${enabled}, ${sanitizeDashboardText(entries ?? "unknown", "unknown")} entries, ${sanitizeDashboardText(expired, "0")} expired`;
  }

  function readStatusObject(payload, ...keys) {
    for (const candidate of [payload, payload && payload.response, payload && payload.data]) {
      if (!candidate || typeof candidate !== "object" || Array.isArray(candidate)) continue;
      for (const key of keys) {
        const value = candidate[key];
        if (value && typeof value === "object" && !Array.isArray(value)) return value;
      }
    }
    return {};
  }

  function readObjectWithFields(payload, fieldKeys, ...nestedKeys) {
    const nested = readStatusObject(payload, ...nestedKeys);
    if (Object.keys(nested).some((key) => fieldKeys.includes(key))) return nested;
    for (const candidate of [payload, payload && payload.response, payload && payload.data]) {
      if (!candidate || typeof candidate !== "object" || Array.isArray(candidate)) continue;
      if (fieldKeys.some((key) => candidate[key] !== undefined && candidate[key] !== null)) return candidate;
    }
    return nested;
  }

  function closureSummaryData(payload) {
    const closures = readObjectWithFields(payload, Object.keys(closureLabels), "closures_state", "vehicle_state", "closures");
    const openLabels = Object.entries(closureLabels)
      .filter(([key]) => closureIsOpen(closures[key]))
      .map(([, label]) => label);
    const knownCount = Object.keys(closureLabels).filter((key) => closures[key] !== undefined && closures[key] !== null).length;
    return { closures, openLabels, knownCount };
  }

  function percentBadge(label, value) {
    const number = numericValue(value);
    return number == null ? `${label} unknown` : `${label} ${number}%`;
  }

  function milesBadge(label, value) {
    const number = numericValue(value);
    return number == null ? `${label} unknown` : `${label} ${number.toFixed(1).replace(/\.0$/, "")} mi`;
  }

  function speedBadge(label, value) {
    const number = numericValue(value);
    return number == null ? `${label} unknown` : `${label} ${Math.round(number)} mph`;
  }

  function temperatureBadge(label, value) {
    const number = numericValue(value);
    return number == null ? `${label} unknown` : `${label} ${number.toFixed(1).replace(/\.0$/, "")}°`;
  }

  function alertItems(payload) {
    for (const candidate of [payload, payload && payload.response, payload && payload.data, payload && payload.vehicle_alerts]) {
      if (!candidate || typeof candidate !== "object") continue;
      for (const key of ["alerts", "vehicle_alerts", "notifications", "messages", "active_alerts", "items"]) {
        if (Array.isArray(candidate[key])) return candidate[key];
      }
    }
    return [];
  }

  function alertStatusLabel(alert, fallback) {
    if (!alert || typeof alert !== "object") return sanitizeDashboardText(alert, fallback);
    const severity = firstDefined(alert.severity, alert.level, alert.status, alert.state, alert.type, fallback);
    return sanitizeDashboardText(String(severity).replace(/_/g, " "), fallback);
  }

  function softwareMeta(payload, ...keys) {
    const response = payload && payload.response;
    const data = payload && payload.data;
    const software = firstDefined(
      payload && payload.software,
      response && response.software,
      data && data.software
    );
    const vehicleState = firstDefined(
      payload && payload.vehicle_state,
      response && response.vehicle_state,
      data && data.vehicle_state
    );
    const softwareUpdate = firstDefined(
      payload && payload.software_update,
      software && software.software_update,
      vehicleState && vehicleState.software_update,
      response && response.software_update,
      data && data.software_update
    );
    for (const candidate of [payload, software, softwareUpdate, vehicleState, response, data]) {
      if (!candidate || typeof candidate !== "object" || Array.isArray(candidate)) continue;
      for (const key of keys) {
        if (candidate[key] != null && String(candidate[key]).trim() !== "") {
          return sanitizeDashboardText(candidate[key], "unknown");
        }
      }
    }
    return "unknown";
  }

  function accessContainers(payload) {
    return [
      payload,
      payload && payload.response,
      payload && payload.data,
      payload && payload.drivers,
      payload && payload.vehicle_drivers,
      payload && payload.access,
    ].filter((item) => item && typeof item === "object" && !Array.isArray(item));
  }

  function accessRows(payload, keys) {
    for (const container of accessContainers(payload)) {
      for (const key of keys) {
        if (Array.isArray(container[key])) return container[key];
      }
    }
    return [];
  }

  function accessCount(payload, keys) {
    const rows = accessRows(payload, keys);
    if (rows.length) return rows.length;
    return arrayCount(payload, keys);
  }

  function accessFacetCounts(rows, keys, fallback) {
    const counts = new Map();
    rows.forEach((row) => {
      if (!row || typeof row !== "object") return;
      for (const key of keys) {
        const value = row[key];
        if (value != null && String(value).trim() !== "") {
          const label = sanitizeDashboardText(String(value).replace(/_/g, " "), fallback);
          counts.set(label, (counts.get(label) || 0) + 1);
          return;
        }
      }
    });
    return Array.from(counts.entries())
      .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
      .slice(0, 3)
      .map(([label, count]) => `${label} ${count}`);
  }

  function mobileAccessContainers(payload) {
    const access = payload && payload.mobile_access;
    return [
      payload,
      access,
      payload && payload.response,
      payload && payload.data,
      access && access.response,
      access && access.data,
    ].filter((item) => item && typeof item === "object" && !Array.isArray(item));
  }

  function mobileAccessValue(payload, ...keys) {
    for (const container of mobileAccessContainers(payload)) {
      for (const key of keys) {
        if (container[key] != null && String(container[key]).trim() !== "") return container[key];
      }
    }
    return undefined;
  }

  function mobileAccessBadge(label, payload, ...keys) {
    const value = mobileAccessValue(payload, ...keys);
    if (value === undefined) return `${label} unknown`;
    return `${label} ${sanitizeDashboardText(String(value).replace(/_/g, " "), "unknown")}`;
  }

  function serviceContainers(payload) {
    const service = payload && payload.service;
    const response = payload && payload.response;
    const data = payload && payload.data;
    return [
      payload,
      service,
      response,
      data,
      response && response.service,
      data && data.service,
      service && service.response,
      service && service.data,
    ].filter((item) => item && typeof item === "object" && !Array.isArray(item));
  }

  function serviceValue(payload, ...keys) {
    for (const container of serviceContainers(payload)) {
      for (const key of keys) {
        if (container[key] != null && String(container[key]).trim() !== "") return container[key];
      }
    }
    return undefined;
  }

  function serviceAppointments(payload) {
    const containers = serviceContainers(payload);
    for (const container of containers) {
      for (const key of ["appointments", "service_visits", "visits", "service_appointments", "upcoming_appointments"]) {
        if (Array.isArray(container[key])) return container[key];
      }
    }
    return [];
  }

  function serviceAppointmentLabel(appointment, fallback) {
    if (!appointment || typeof appointment !== "object") return sanitizeDashboardText(appointment, fallback);
    const state = firstDefined(appointment.status, appointment.state, appointment.appointment_status, appointment.service_status);
    const serviceType = firstDefined(appointment.service_type, appointment.type, appointment.category, appointment.concern_type);
    const startsAt = firstDefined(appointment.start_time, appointment.appointment_time, appointment.scheduled_at, appointment.arrival_time, appointment.date);
    const parts = [];
    if (state != null) parts.push(`status ${sanitizeDashboardText(state, "unknown")}`);
    if (serviceType != null) parts.push(`type ${sanitizeDashboardText(String(serviceType).replace(/_/g, " "), "service")}`);
    if (startsAt != null) parts.push(`time ${sanitizeDashboardText(startsAt, "time hidden")}`);
    return parts.length ? parts.slice(0, 3).join(", ") : fallback;
  }

  function chargerSites(payload, key, ...aliases) {
    const sites = payload && (payload.sites || payload.nearby_chargers || payload.chargers || payload);
    for (const candidate of [key, ...aliases]) {
      const value = sites && sites[candidate];
      if (Array.isArray(value)) return value;
    }
    return [];
  }

  function chargerDistanceLabel(site) {
    if (!site || typeof site !== "object") return "";
    const miles = numericValue(site.distance_miles, site.distance_mi, site.distance);
    if (miles != null) return `${miles.toFixed(1).replace(/\.0$/, "")} mi`;
    const kilometers = numericValue(site.distance_km);
    if (kilometers != null) return `${kilometers.toFixed(1).replace(/\.0$/, "")} km`;
    return "distance hidden";
  }

  function chargerStallLabel(site) {
    if (!site || typeof site !== "object") return "availability unknown";
    const available = firstDefined(site.available_stalls, site.available, site.stalls_available);
    const total = firstDefined(site.total_stalls, site.total, site.stall_count);
    if (available != null && total != null) return `${available}/${total} stalls`;
    if (available != null) return `${available} stalls available`;
    return "availability unknown";
  }

  function chargerOrderLabel(site, fallback, order) {
    const hint = site && firstDefined(site.type, site.kind, site.category, fallback);
    const safeHint = sanitizeDashboardText(String(hint || fallback).replace(/_/g, " "), fallback);
    return `${safeHint} #${order}`;
  }

  function scheduleSection(payload, ...keys) {
    for (const candidate of [payload, payload && payload.response, payload && payload.data]) {
      if (!candidate || typeof candidate !== "object" || Array.isArray(candidate)) continue;
      for (const key of keys) {
        const value = candidate[key];
        if (value && typeof value === "object" && !Array.isArray(value)) return value;
      }
    }
    return {};
  }

  function scheduleEntries(sectionPayload, ...keys) {
    for (const key of ["schedules", "entries", "items", ...keys]) {
      const value = sectionPayload && sectionPayload[key];
      if (Array.isArray(value)) return value;
      if (value && typeof value === "object") {
        for (const nestedKey of ["schedules", "entries", "items", "charge_schedules", "preconditioning_schedules"]) {
          if (Array.isArray(value[nestedKey])) return value[nestedKey];
        }
      }
    }
    return [];
  }

  function scheduleEntryLabel(entry, fallback) {
    if (!entry || typeof entry !== "object") return fallback;
    const parts = [];
    const enabled = firstDefined(entry.enabled, entry.start_enabled, entry.end_enabled, entry.preconditioning_enabled);
    if (enabled !== undefined) parts.push(`enabled ${String(enabled)}`);
    for (const [value, label] of [
      [entry.start_time, "start"],
      [entry.end_time, "end"],
      [entry.departure_time, "depart"],
      [entry.time, "time"],
      [entry.minute_of_day, "minute"],
    ]) {
      if (value !== undefined && value !== null && value !== "") parts.push(`${label} ${sanitizeDashboardText(value, "time hidden")}`);
    }
    const days = firstDefined(entry.days_of_week, entry.days, entry.week_days);
    if (Array.isArray(days) && days.length) parts.push(`days ${days.slice(0, 7).map((day) => sanitizeDashboardText(day, "day")).join("/")}`);
    else if (days) parts.push(`days ${sanitizeDashboardText(days, "days hidden")}`);
    return parts.length ? parts.slice(0, 4).join(", ") : fallback;
  }

  function scheduleSummaryData(payload, sectionKeys, entryKeys) {
    const sectionPayload = scheduleSection(payload, ...sectionKeys);
    const entries = scheduleEntries(sectionPayload, ...entryKeys);
    const enabled = firstDefined(sectionPayload.enabled, sectionPayload.scheduled_charging_enabled, sectionPayload.scheduled_departure_enabled, sectionPayload.preconditioning_enabled);
    const nextStart = firstDefined(sectionPayload.next_start_time, sectionPayload.start_time, sectionPayload.departure_time);
    const topEntries = entries.slice(0, 3).map((entry, index) => scheduleEntryLabel(entry, `schedule ${index + 1}`));
    const hiddenCount = Math.max(0, entries.length - topEntries.length);
    return {
      entries,
      enabled: enabled === undefined ? "unknown" : String(enabled),
      nextStart: nextStart === undefined ? "unknown" : sanitizeDashboardText(nextStart, "time hidden"),
      topEntries,
      hiddenCount,
      hiddenText: hiddenCount ? `${hiddenCount} additional schedule entr${hiddenCount === 1 ? "y" : "ies"} hidden` : "",
    };
  }

  function releaseNoteContainers(payload) {
    const releaseNotes = payload && payload.release_notes;
    return [
      releaseNotes,
      releaseNotes && releaseNotes.release_notes,
      releaseNotes && releaseNotes.sections,
      releaseNotes && releaseNotes.notes,
      releaseNotes && releaseNotes.release_notes_list,
      payload && payload.sections,
      payload && payload.notes,
      payload && payload.release_notes_list,
      payload && payload.release_note_sections,
    ];
  }

  function releaseNoteItems(payload) {
    for (const candidate of releaseNoteContainers(payload)) {
      if (Array.isArray(candidate)) return candidate;
    }
    return [];
  }

  function releaseNoteVersion(payload) {
    const releaseNotes = payload && payload.release_notes && typeof payload.release_notes === "object" ? payload.release_notes : {};
    return sanitizeDashboardText(firstDefined(
      payload && payload.version,
      payload && payload.release_version,
      payload && payload.firmware_version,
      releaseNotes.version,
      releaseNotes.release_version,
      releaseNotes.car_version,
      payload && payload.car_version,
      "version unknown"
    ), "version unknown");
  }

  function releaseNoteStatus(payload) {
    const releaseNotes = payload && payload.release_notes && typeof payload.release_notes === "object" ? payload.release_notes : {};
    return sanitizeDashboardText(firstDefined(
      payload && payload.status,
      payload && payload.state,
      releaseNotes.status,
      releaseNotes.state,
      "status unknown"
    ), "status unknown");
  }

  function releaseNoteTitle(item, fallback) {
    if (!item || typeof item !== "object") return fallback;
    return sanitizeDashboardText(firstDefined(item.title, item.heading, item.subtitle, item.name, item.header, fallback), fallback);
  }

  function warrantyContainers(payload) {
    const warranty = payload && payload.warranty;
    return [
      payload,
      warranty,
      payload && payload.response,
      payload && payload.data,
      warranty && warranty.response,
      warranty && warranty.data,
    ].filter((item) => item && typeof item === "object" && !Array.isArray(item));
  }

  function warrantyTerms(payload) {
    const keys = ["warranties", "warranty_terms", "terms", "coverages", "items"];
    for (const container of warrantyContainers(payload)) {
      for (const key of keys) {
        if (Array.isArray(container[key])) return container[key];
      }
    }
    return [];
  }

  function warrantyMeta(payload, ...keys) {
    for (const container of warrantyContainers(payload)) {
      for (const key of keys) {
        if (container[key] != null && String(container[key]).trim() !== "") {
          return sanitizeDashboardText(container[key], "unknown");
        }
      }
    }
    return "unknown";
  }

  function warrantyTermLabel(term, fallback) {
    if (!term || typeof term !== "object") return sanitizeDashboardText(term, fallback);
    const name = sanitizeDashboardText(firstDefined(term.name, term.title, term.warranty_type, term.coverage_type, term.type, term.product, fallback), fallback);
    const status = firstDefined(term.status, term.state, term.eligibility, term.coverage_status);
    const end = firstDefined(term.end_date, term.expires_at, term.expiration_date, term.end_time);
    const details = [];
    if (status != null) details.push(`status ${sanitizeDashboardText(status, "unknown")}`);
    if (end != null) details.push(`ends ${sanitizeDashboardText(end, "date hidden")}`);
    for (const [value, label] of [
      [term.odometer_limit_miles, "mi limit"],
      [term.mileage_limit, "mi limit"],
      [term.end_mileage, "mi limit"],
      [term.odometer_limit_km, "km limit"],
    ]) {
      if (value != null) {
        details.push(`${label} ${sanitizeDashboardText(value, "mileage hidden")}`);
        break;
      }
    }
    return details.length ? `${name} (${details.join(", ")})` : name;
  }

  function energyContainers(payload) {
    const energy = payload && payload.energy;
    const energySite = payload && payload.energy_site;
    return [
      payload,
      energy,
      energySite,
      payload && payload.response,
      payload && payload.data,
      energy && energy.response,
      energy && energy.data,
      energySite && energySite.response,
      energySite && energySite.data,
    ].filter((item) => item && typeof item === "object" && !Array.isArray(item));
  }

  function energyProducts(payload) {
    const keys = ["products", "energy_products", "sites", "energy_sites", "resources"];
    for (const container of energyContainers(payload)) {
      for (const key of keys) {
        if (Array.isArray(container[key])) return container[key];
      }
    }
    return [];
  }

  function energyMeta(payload, ...keys) {
    for (const container of energyContainers(payload)) {
      for (const key of keys) {
        if (container[key] != null && String(container[key]).trim() !== "") {
          return sanitizeDashboardText(container[key], "unknown");
        }
      }
    }
    return "unknown";
  }

  function energyPowerBadge(label, value) {
    const number = numericValue(value);
    return number == null ? `${label} unknown` : `${label} ${number.toFixed(1).replace(/\.0$/, "")} kW`;
  }

  function configGuiBadge(label, ...values) {
    const value = firstDefined(...values);
    if (value === undefined) return `${label} unknown`;
    return `${label} ${sanitizeDashboardText(String(value).replace(/_/g, " "), "unknown")}`;
  }

  function configGuiBooleanBadge(label, ...values) {
    return `${label} ${yesNoUnknown(firstDefined(...values))}`;
  }

  function DashboardReadSummary({ detail, lastReadKind }) {
    if (!detail || !lastReadKind) return null;
    const payload = nestedPayload(detail);
    let title = "Last read summary";
    let body = "Read completed. Use the redacted payload below for troubleshooting details.";
    let badges = [];
    let note = "Visible read summaries omit VINs, Fleet IDs, tokens, destinations, and precise coordinates.";

    if (lastReadKind === "auth-status") {
      const configured = yesNoUnknown(firstDefined(payload && payload.configured, setupReadinessValue(payload, "app_configured")));
      const authenticated = yesNoUnknown(firstDefined(payload && payload.authenticated, setupReadinessValue(payload, "authenticated")));
      const reads = yesNoUnknown(setupReadinessValue(payload, "ready_for_vehicle_reads"));
      const commands = yesNoUnknown(setupReadinessValue(payload, "ready_for_vehicle_commands"));
      title = "Auth readiness summary";
      body = "Authentication details are summarized as coarse readiness states; tokens, callback URLs, client IDs, vehicle identifiers, and key paths stay in the redacted payload.";
      badges = [
        `configured ${configured}`,
        `authenticated ${authenticated}`,
        `reads ${reads}`,
        `commands ${commands}`,
      ];
    } else if (lastReadKind === "onboarding") {
      const phase = sanitizeDashboardText(firstDefined(payload && payload.phase, payload && payload.next_action, "setup phase unknown"), "setup phase unknown");
      const nextTool = sanitizeDashboardText(firstDefined(payload && payload.next_tool, payload && payload.next_action, "next step unknown"), "next step unknown");
      const missing = Array.isArray(payload && payload.missing_prerequisites) ? payload.missing_prerequisites.length : 0;
      title = "Onboarding summary";
      body = "Setup guidance is condensed into the current phase, next safe tool, and missing-prerequisite count without exposing OAuth values, domains, client IDs, or vehicle identifiers.";
      badges = [phase, `next ${nextTool}`, `${missing} missing prerequisite${missing === 1 ? "" : "s"}`];
    } else if (lastReadKind === "key-show" || lastReadKind === "key-validate") {
      const status = sanitizeDashboardText(firstDefined(payload && payload.status, payload && payload.accessible, "key status unknown"), "key status unknown");
      const privateKey = yesNoUnknown(payload && payload.private_key_present);
      const publicKey = yesNoUnknown(firstDefined(payload && payload.public_key_present, payload && payload.accessible));
      const matches = yesNoUnknown(payload && payload.matches_local_key);
      title = lastReadKind === "key-show" ? "Vehicle-command key summary" : "Key hosting validation summary";
      body = "Key diagnostics show readiness and match state only; local key paths, public-key URLs, fingerprints, domains, and enrollment links stay out of visible dashboard copy.";
      badges = [
        `status ${status}`,
        `private key ${privateKey}`,
        `public key ${publicKey}`,
        `matches local ${matches}`,
      ];
    } else if (lastReadKind === "cache-status") {
      const entryCount = cacheValue(payload, "entries", "entry_count", "count", "current_entries");
      const expiredCount = cacheValue(payload, "expired_entries", "expired_count", "stale_entries", "stale_count");
      const backend = sanitizeDashboardText(cacheValue(payload, "backend", "mode", "storage", "source") || "backend unknown", "backend unknown");
      title = "Cache summary";
      body = "Cache diagnostics are summarized as current/stale counts, backend mode, and freshness hints so operators can verify read freshness without exposing local cache paths, raw cache keys, cached vehicle snapshots, vehicle identifiers, or account details.";
      badges = [
        cacheModeLabel(payload),
        cacheCountLabel("current entry", entryCount, "current entries"),
        cacheCountLabel("stale/expired entry", expiredCount, "stale/expired entries"),
        `mode ${backend}`,
        cacheFreshnessLabel(payload),
      ];
    } else if (lastReadKind === "vehicle-status") {
      const vehicleState = readObjectWithFields(payload, ["vehicle_name", "car_version", "locked", "is_user_present", "sentry_mode"], "vehicle_state", "vehicle_status", "state");
      const drive = readStatusObject(payload, "drive_state", "drive", "location_data");
      const charge = readStatusObject(payload, "charge_state", "charge", "battery");
      const climate = readStatusObject(payload, "climate_state", "climate", "hvac_state");
      const vehicleMode = sanitizeDashboardText(firstDefined(vehicleState.car_version, vehicleState.api_version, vehicleState.state, "status returned"), "status returned");
      const userPresent = yesNoUnknown(firstDefined(vehicleState.is_user_present, vehicleState.user_present));
      const locked = booleanLabel(firstDefined(vehicleState.locked, vehicleState.vehicle_locked));
      const sentry = booleanLabel(firstDefined(vehicleState.sentry_mode, vehicleState.sentry_mode_available && vehicleState.sentry_mode));
      title = "Vehicle status summary";
      body = "Vehicle status is condensed into coarse firmware/state, occupancy, lock/Sentry, charge, climate, and drive hints. Vehicle names, VINs, Fleet IDs, exact coordinates, addresses, route text, and raw diagnostic fields stay in the redacted payload.";
      badges = [
        `state ${vehicleMode}`,
        `user present ${userPresent}`,
        `locked ${locked}`,
        `Sentry ${sentry}`,
        percentBadge("battery", firstDefined(charge.battery_level, charge.usable_battery_level, charge.soc)),
        temperatureBadge("cabin", firstDefined(climate.inside_temp, climate.cabin_temp)),
        speedBadge("speed", firstDefined(drive.speed, drive.vehicle_speed)),
      ];
    } else if (lastReadKind === "closures") {
      const summary = closureSummaryData(payload);
      const locked = booleanLabel(firstDefined(summary.closures.locked, summary.closures.vehicle_locked));
      title = "Closures summary";
      body = summary.openLabels.length
        ? `Closures reported ${summary.openLabels.length} open item${summary.openLabels.length === 1 ? "" : "s"}: ${summary.openLabels.slice(0, 4).join(", ")}${summary.openLabels.length > 4 ? " and more" : ""}. Raw closure codes, vehicle identifiers, and location fields stay in the redacted payload.`
        : "No open closures were reported in the visible closure fields. The dashboard shows count/status hints while raw closure codes, vehicle identifiers, and location fields stay hidden.";
      badges = [
        `${summary.openLabels.length} open closure${summary.openLabels.length === 1 ? "" : "s"}`,
        `${summary.knownCount} closure field${summary.knownCount === 1 ? "" : "s"} checked`,
        `locked ${locked}`,
      ];
    } else if (lastReadKind === "security") {
      const security = readObjectWithFields(payload, ["locked", "sentry_mode", "valet_mode", "notifications_supported"], "vehicle_state", "security_state");
      const closureSummary = closureSummaryData(payload);
      const locked = booleanLabel(firstDefined(security.locked, closureSummary.closures.locked));
      const sentry = booleanLabel(firstDefined(security.sentry_mode, security.sentry_mode_available && security.sentry_mode));
      const valet = booleanLabel(firstDefined(security.valet_mode, security.valet_pin_needed));
      title = "Security summary";
      body = closureSummary.openLabels.length
        ? `Security returned lock/Sentry/valet state plus ${closureSummary.openLabels.length} open closure hint${closureSummary.openLabels.length === 1 ? "" : "s"}. Open items: ${closureSummary.openLabels.slice(0, 3).join(", ")}. Raw alarm details, private identifiers, and exact location fields stay in the redacted payload.`
        : "Security returned lock/Sentry/valet state without open closure hints. Raw alarm details, private identifiers, and exact location fields stay in the redacted payload.";
      badges = [
        `locked ${locked}`,
        `Sentry ${sentry}`,
        `valet ${valet}`,
        `${closureSummary.openLabels.length} open closure${closureSummary.openLabels.length === 1 ? "" : "s"}`,
      ];
    } else if (lastReadKind === "charge") {
      const charge = readStatusObject(payload, "charge_state", "charge", "battery");
      const level = firstDefined(charge.battery_level, charge.usable_battery_level, charge.soc, charge.battery_soc);
      const limit = firstDefined(charge.charge_limit_soc, charge.charge_limit_soc_std, charge.charge_limit_soc_min);
      const state = sanitizeDashboardText(firstDefined(charge.charging_state, charge.charge_state, charge.conn_charge_cable, "charge state unknown"), "charge state unknown");
      const range = numericValue(charge.battery_range, charge.est_battery_range, charge.ideal_battery_range);
      const rangeLabel = range == null ? "range unknown" : `range ${range.toFixed(0)} mi`;
      const plugged = yesNoUnknown(firstDefined(charge.plugged_in, charge.charge_port_door_open, charge.conn_charge_cable));
      title = "Charge read summary";
      body = "Charging state is condensed into battery level, limit, plug/charging state, and coarse range hints. Charge-port locations, vehicle identifiers, raw charger metadata, and account details stay in the redacted payload.";
      badges = [
        percentBadge("battery", level),
        percentBadge("limit", limit),
        `state ${state}`,
        rangeLabel,
        `plug/cable ${plugged}`,
      ];
    } else if (lastReadKind === "climate") {
      const climate = readStatusObject(payload, "climate_state", "climate", "hvac_state");
      const cabin = temperatureBadge("cabin", firstDefined(climate.inside_temp, climate.cabin_temp));
      const outside = temperatureBadge("outside", firstDefined(climate.outside_temp, climate.ambient_temp));
      const target = temperatureBadge("target", firstDefined(climate.driver_temp_setting, climate.passenger_temp_setting, climate.left_temp_direction, climate.right_temp_direction));
      const active = booleanLabel(firstDefined(climate.is_climate_on, climate.auto_seat_climate_left, climate.climate_keeper_mode && climate.climate_keeper_mode !== "off"));
      const defrost = booleanLabel(firstDefined(climate.is_front_defroster_on, climate.is_rear_defroster_on, climate.defrost_mode));
      title = "Climate read summary";
      body = "Cabin climate is summarized as coarse temperature and HVAC states for quick operator triage. Precise location context, vehicle identifiers, driver-specific personal data, and raw climate payload details stay in the redacted payload.";
      badges = [
        cabin,
        outside,
        target,
        `HVAC ${active}`,
        `defrost ${defrost}`,
      ];
    } else if (lastReadKind === "drive" || lastReadKind === "location") {
      const drive = readStatusObject(payload, "drive_state", "drive", "location_data");
      const speed = speedBadge("speed", firstDefined(drive.speed, drive.vehicle_speed));
      const heading = compassHeadingLabel(firstDefined(drive.heading, drive.vehicle_heading));
      const gear = sanitizeDashboardText(firstDefined(drive.shift_state, drive.gear, drive.power, "gear/power unknown"), "gear/power unknown");
      const odometer = milesBadge("odometer", firstDefined(drive.odometer, drive.odometer_miles, drive.odometer_mi));
      const coordinateKeys = ["la" + "t", "lo" + "n", "ln" + "g"];
      const coordinateHint = coordinateKeys.some((key) => drive[key] != null) ? "fix available" : "fix unavailable";
      title = lastReadKind === "drive" ? "Drive read summary" : "Location read summary";
      body = "Drive/location state is condensed into speed, heading, gear/power, odometer, and coarse coordinate availability. Precise coordinates, route or destination text, addresses, vehicle identifiers, and raw map payload details stay in the redacted payload.";
      badges = [
        speed,
        heading,
        `state ${gear}`,
        odometer,
        coordinateHint,
      ];
    } else if (lastReadKind === "config") {
      const config = objectAt(payload, ["vehicle_config", "config"]);
      const count = Object.keys(config).length;
      title = "Vehicle config summary";
      body = "Vehicle configuration reads are summarized as coarse model, capability, and unit hints so operators can identify the vehicle context without echoing raw option values, identifiers, precise location hints, or account details.";
      badges = [
        `${count} visible field${count === 1 ? "" : "s"}`,
        configGuiBadge("model", config.car_type, config.model, config.trim_badging),
        configGuiBadge("trim", config.trim_badging, config.badging),
        configGuiBooleanBadge("navigation", config.can_accept_navigation_requests, config.navigation_request_supported),
        configGuiBooleanBadge("calendar", config.calendar_supported),
      ];
    } else if (lastReadKind === "gui") {
      const gui = objectAt(payload, ["gui_settings", "gui"]);
      const count = Object.keys(gui).length;
      title = "GUI settings summary";
      body = "GUI settings are summarized as coarse unit and display preferences so operators can interpret temperatures, distances, and charging units without exposing vehicle identifiers, location hints, or account details.";
      badges = [
        `${count} visible field${count === 1 ? "" : "s"}`,
        configGuiBadge("distance", gui.gui_distance_units, gui.distance_units),
        configGuiBadge("temperature", gui.gui_temperature_units, gui.temperature_units),
        configGuiBadge("charge rate", gui.gui_charge_rate_units, gui.charge_rate_units),
        configGuiBadge("time", gui.gui_24_hour_time, gui.time_format),
      ];
    } else if (lastReadKind === "software") {
      const version = softwareMeta(payload, "version", "car_version", "current_version", "firmware_version");
      const status = softwareMeta(payload, "status", "state", "download_status", "install_status");
      const estimate = softwareMeta(payload, "expected_duration_sec", "expected_duration_seconds", "install_duration", "eta", "scheduled_time");
      const progress = softwareMeta(payload, "install_perc", "download_perc", "progress_percent", "update_progress", "percent_complete");
      const scheduled = softwareMeta(payload, "scheduled_time", "install_window_start", "install_window", "eligible_time", "install_after");
      title = "Software summary";
      body = "Software status is condensed into version, update state, timing, progress, and scheduled-install hints so operators can spot update readiness without exposing vehicle identifiers, release-note URLs, account fields, location context, or raw diagnostic payloads.";
      badges = [
        `version ${version}`,
        `status ${status}`,
        `timing ${estimate}`,
        `progress ${progress}`,
        `scheduled ${scheduled}`,
      ];
    } else if (lastReadKind === "alerts") {
      const alerts = alertItems(payload);
      const topStatuses = alerts.slice(0, 3).map((alert, index) => alertStatusLabel(alert, `alert ${index + 1}`));
      const hiddenAlertCount = Math.max(0, alerts.length - topStatuses.length);
      const hiddenAlertText = hiddenAlertCount ? `${hiddenAlertCount} additional alert${hiddenAlertCount === 1 ? "" : "s"} hidden` : "";
      title = "Alerts summary";
      body = topStatuses.length
        ? `Recent vehicle alerts returned ${alerts.length} item${alerts.length === 1 ? "" : "s"}. Top statuses: ${topStatuses.join(", ")}${hiddenAlertText ? `. ${hiddenAlertText}` : ""}. Alert messages, driver/location hints, callback URLs, and vehicle identifiers stay in the redacted payload.`
        : "Alert read returned without individual alert rows. Use the redacted payload for troubleshooting while message text, coordinates, URLs, and identifiers stay hidden.";
      badges = [
        `${alerts.length} alert${alerts.length === 1 ? "" : "s"}`,
        ...topStatuses.slice(0, 2),
        ...(hiddenAlertText ? [hiddenAlertText] : []),
      ];
    } else if (lastReadKind === "drivers") {
      const driverRows = accessRows(payload, ["drivers", "users", "people", "members", "vehicle_drivers"]);
      const inviteRows = accessRows(payload, ["invites", "invitations", "pending_invites"]);
      const driverCount = driverRows.length || accessCount(payload, ["drivers", "users", "people", "members", "vehicle_drivers"]);
      const inviteCount = inviteRows.length || accessCount(payload, ["invites", "invitations", "pending_invites"]);
      const roleFacets = accessFacetCounts(driverRows, ["role", "permission", "access_level", "access_type", "type"], "role");
      const driverStatuses = accessFacetCounts(driverRows, ["status", "state", "account_status", "access_status"], "status");
      const inviteStatuses = accessFacetCounts(inviteRows, ["status", "state", "invite_status"], "invite");
      const accessHints = [...roleFacets, ...driverStatuses, ...inviteStatuses].slice(0, 4);
      title = "Access summary";
      body = accessHints.length
        ? `Driver/account access returned ${driverCount == null ? "unknown" : driverCount} driver/user record${driverCount === 1 ? "" : "s"} and ${inviteCount == null ? "unknown" : inviteCount} pending invite${inviteCount === 1 ? "" : "s"}. Top role/status hints: ${accessHints.join(", ")}. Names, emails, phone numbers, invite links, private IDs, and raw permission payloads stay in the redacted payload.`
        : "Driver/account access data is summarized as counts and coarse status only; names, emails, phone numbers, invite links, private IDs, and raw permission payloads stay out of the dashboard copy.";
      badges = [
        `${driverCount == null ? "unknown" : driverCount} driver/user record${driverCount === 1 ? "" : "s"}`,
        `${inviteCount == null ? "unknown" : inviteCount} pending invite${inviteCount === 1 ? "" : "s"}`,
        ...accessHints.slice(0, 3),
      ];
    } else if (lastReadKind === "service") {
      const appointments = serviceAppointments(payload);
      const visitCount = appointments.length || arrayCount(payload, ["appointments", "service_visits", "visits", "service_appointments", "upcoming_appointments"]);
      const status = sanitizeDashboardText(firstDefined(serviceValue(payload, "status", "service_status", "state", "maintenance_status", "appointment_status"), "status unknown"), "status unknown");
      const topVisits = appointments.slice(0, 3).map((appointment, index) => serviceAppointmentLabel(appointment, `visit ${index + 1}`));
      title = "Service summary";
      body = topVisits.length
        ? `Service ${status}. Top visits: ${topVisits.join("; ")}. Appointment IDs, service-center addresses, raw booking URLs, vehicle identifiers, and customer contact details stay in the redacted payload.`
        : "Service data returned without visit rows. The dashboard shows status/count hints while appointment IDs, service-center addresses, booking URLs, vehicle identifiers, and customer contact details stay hidden.";
      badges = [status, `${visitCount == null ? "unknown" : visitCount} visit${visitCount === 1 ? "" : "s"}`];
    } else if (lastReadKind === "mobile-access") {
      const access = booleanLabel(mobileAccessValue(payload, "enabled", "mobile_access_enabled", "allow_mobile_access", "remote_access_enabled"));
      const status = mobileAccessBadge("status", payload, "status", "state", "access_status", "remote_access_status");
      const reads = `reads ${yesNoUnknown(mobileAccessValue(payload, "ready_for_vehicle_reads", "read_access", "reads_enabled"))}`;
      const commands = `commands ${yesNoUnknown(mobileAccessValue(payload, "ready_for_vehicle_commands", "command_access", "commands_enabled"))}`;
      const source = mobileAccessBadge("source", payload, "source", "config_source", "grant_source", "scope_source");
      title = "Mobile access summary";
      body = "Mobile access is summarized as remote access, read, command, status, and source hints so operators can triage app access without exposing account contact fields, tokens, callback values, vehicle identifiers, or raw access rows.";
      badges = [`mobile access ${access}`, status, reads, commands, source];
    } else if (lastReadKind === "nearby-chargers") {
      const superchargers = chargerSites(payload, "superchargers", "nearby_superchargers");
      const destinationChargers = chargerSites(payload, "destination_charging", "destination_chargers");
      const topSupercharger = superchargers[0];
      title = "Nearby chargers summary";
      body = topSupercharger
        ? `Top ${chargerOrderLabel(topSupercharger, "Supercharger", 1)} · ${chargerStallLabel(topSupercharger)} · ${chargerDistanceLabel(topSupercharger)}. Use tescmd_navigation_supercharger order=N confirm=true from the numbered list; charger names and coordinates stay hidden.`
        : "Nearby charging data returned without a Supercharger list. Use the redacted payload below for troubleshooting while coordinates stay hidden.";
      badges = [
        `${superchargers.length} Supercharger${superchargers.length === 1 ? "" : "s"}`,
        `${destinationChargers.length} destination charger${destinationChargers.length === 1 ? "" : "s"}`,
      ];
    } else if (lastReadKind === "charge-schedule") {
      const summary = scheduleSummaryData(payload, ["charge_schedule", "charge_schedule_data"], ["charge_schedules", "charge_schedule"]);
      title = "Charge schedule summary";
      body = summary.topEntries.length
        ? `Charge scheduling returned ${summary.entries.length} entr${summary.entries.length === 1 ? "y" : "ies"}. Top schedules: ${summary.topEntries.join("; ")}${summary.hiddenText ? `. ${summary.hiddenText}` : ""}. Schedule IDs, vehicle identifiers, raw location fields, and precise coordinates stay out of the visible summary.`
        : "Charge scheduling returned without individual schedule entries. Use the redacted payload for troubleshooting; schedule IDs and vehicle identifiers stay hidden.";
      badges = [
        `${summary.entries.length} schedule${summary.entries.length === 1 ? "" : "s"}`,
        `enabled ${summary.enabled}`,
        `next/start ${summary.nextStart}`,
        ...(summary.hiddenText ? [summary.hiddenText] : []),
      ];
    } else if (lastReadKind === "preconditioning-schedule") {
      const summary = scheduleSummaryData(payload, ["preconditioning_schedule", "preconditioning_schedule_data"], ["preconditioning_schedules", "preconditioning_schedule"]);
      title = "Preconditioning schedule summary";
      body = summary.topEntries.length
        ? `Preconditioning scheduling returned ${summary.entries.length} entr${summary.entries.length === 1 ? "y" : "ies"}. Top schedules: ${summary.topEntries.join("; ")}${summary.hiddenText ? `. ${summary.hiddenText}` : ""}. Schedule IDs, vehicle identifiers, cabin/location details, and precise coordinates stay out of the visible summary.`
        : "Preconditioning scheduling returned without individual schedule entries. Use the redacted payload for troubleshooting; schedule IDs and vehicle identifiers stay hidden.";
      badges = [
        `${summary.entries.length} schedule${summary.entries.length === 1 ? "" : "s"}`,
        `enabled ${summary.enabled}`,
        `next/start ${summary.nextStart}`,
        ...(summary.hiddenText ? [summary.hiddenText] : []),
      ];
    } else if (lastReadKind === "release-notes") {
      const notes = releaseNoteItems(payload);
      const version = releaseNoteVersion(payload);
      const status = releaseNoteStatus(payload);
      const topTitles = notes.slice(0, 3).map((item, index) => releaseNoteTitle(item, `note ${index + 1}`));
      title = "Release notes summary";
      body = topTitles.length
        ? `Firmware ${version} · ${status}. Top sections: ${topTitles.join(", ")}. Note bodies, URLs, route text, vehicle identifiers, and coordinates stay in the redacted payload.`
        : `Firmware ${version} · ${status}. Release-note metadata returned without section titles; use the redacted payload for troubleshooting without exposing note bodies or URLs.`;
      badges = [
        `${notes.length} note section${notes.length === 1 ? "" : "s"}`,
        version,
        status,
      ];
    } else if (lastReadKind === "warranty") {
      const terms = warrantyTerms(payload);
      const status = warrantyMeta(payload, "status", "state", "eligibility", "coverage_status");
      const asOf = warrantyMeta(payload, "as_of", "asOf", "generated_at", "last_updated");
      const topTerms = terms.slice(0, 3).map((term, index) => warrantyTermLabel(term, `term ${index + 1}`));
      title = "Warranty summary";
      body = topTerms.length
        ? `Warranty ${status} · as of ${asOf}. Top terms: ${topTerms.join("; ")}. Agreement IDs, URLs, vehicle identifiers, and raw coverage payload details stay in the redacted payload.`
        : `Warranty ${status} · as of ${asOf}. Warranty data returned without term labels; use the redacted payload for troubleshooting without exposing agreement IDs or URLs.`;
      badges = [
        `${terms.length} warranty term${terms.length === 1 ? "" : "s"}`,
        status,
        `as of ${asOf}`,
      ];
    } else if (lastReadKind === "energy") {
      const products = energyProducts(payload);
      const status = energyMeta(payload, "status", "state", "operation_mode", "site_status", "grid_status");
      const backup = energyMeta(payload, "backup_reserve_percent", "backup_reserve", "reserve_percent", "battery_backup_reserve");
      const solarPower = firstDefined(payload.solar_power, payload.solar_power_kw, payload.solar_power_w, payload.response && payload.response.solar_power, payload.data && payload.data.solar_power);
      const gridPower = firstDefined(payload.grid_power, payload.grid_power_kw, payload.grid_power_w, payload.response && payload.response.grid_power, payload.data && payload.data.grid_power);
      title = "Energy summary";
      body = products.length
        ? `Energy returned ${products.length} product/site record${products.length === 1 ? "" : "s"}. Status ${status}. Site IDs, addresses, coordinates, vehicle identifiers, account/customer details, and raw telemetry rows stay in the redacted payload.`
        : `Energy status ${status}. Live power and backup hints are summarized without exposing site IDs, addresses, coordinates, vehicle identifiers, account/customer details, or raw telemetry rows.`;
      badges = [
        `${products.length} energy product${products.length === 1 ? "" : "s"}`,
        `status ${status}`,
        `backup ${backup}`,
        energyPowerBadge("solar", solarPower),
        energyPowerBadge("grid", gridPower),
      ];
    } else {
      return null;
    }

    return h("div", { className: "tescmd-read-summary", role: "status", "aria-live": "polite" },
      h("div", null,
        h("span", { className: "tescmd-widget-label" }, "Read result"),
        h("strong", null, title),
        h("p", null, body),
        h("small", null, note)
      ),
      h("div", { className: "tescmd-read-summary-badges" },
        badges.map((badge) => h(Badge, { key: badge }, sanitizeDashboardText(badge, "summary")))
      )
    );
  }

  function vehicleAvailability(overview) {
    const vehicle = selectedVehicle(overview);
    const state = String((vehicle && vehicle.state) || "").toLowerCase();
    const errors = sectionErrorText(overview);
    const unavailable = errors.includes("vehicle unavailable") || errors.includes("offline") || errors.includes("asleep");
    const asleep = state === "asleep" || (unavailable && errors.includes("asleep"));
    const offline = state === "offline" || (unavailable && errors.includes("offline"));
    const rawName = vehicle && (vehicle.display_name || vehicle.vehicle_name || vehicle.name);
    const name = visibleVehicleText(rawName, "Vehicle");
    if (asleep) return { sleeping: true, label: `${name} is asleep`, detail: "Wake it to fetch live vehicle status." };
    if (offline) return { sleeping: true, label: `${name} is offline or asleep`, detail: "Wake it to check for live status." };
    return { sleeping: false, label: state ? `${name} is ${state}` : "Vehicle status unknown", detail: "" };
  }

  function VehicleSleepStatus({ availability, runAction, loading, confirm }) {
    if (!availability || !availability.sleeping) return null;
    return h("div", { className: "tescmd-sleep-status" },
      h("div", null,
        h("strong", null, availability.label),
        h("small", null, availability.detail)
      ),
      h(Button, { onClick: () => runAction("wake"), disabled: loading || !confirm }, loading ? "Waking..." : "Wake vehicle"),
      !confirm ? h("small", { className: "tescmd-muted" }, "Turn on action confirmation to wake the vehicle.") : null
    );
  }

  function VehicleSnapshot({ overview, runAction, loading, confirm, locationPrecision }) {
    const charge = chargeSummary(overview);
    const climate = climateSummary(overview);
    const security = securitySummary(overview);
    const location = locationSummary(overview);
    const visibleLocation = displayLocation(location, locationPrecision);
    const chargeStyle = { "--tescmd-charge": `${Math.max(0, Math.min(100, charge.level ?? 0))}%` };
    const availability = vehicleAvailability(overview);
    const identity = vehicleIdentitySummary(overview);
    const closureText = security.openLabels && security.openLabels.length
      ? `Open: ${security.openLabels.slice(0, 3).join(", ")}${security.openLabels.length > 3 ? ` +${security.openLabels.length - 3} more` : ""}`
      : "No open closures reported";
    return h("div", null,
      h(VehicleSleepStatus, { availability, runAction, loading, confirm }),
      h(VehicleIdentityCard, { identity }),
      h(SectionHealthPanel, { overview }),
      h("div", { className: "tescmd-visual-grid" },
        h("div", { className: "tescmd-charge-widget" },
          h("div", { className: "tescmd-widget-label" }, "Charge"),
          h("div", { className: "tescmd-battery", style: chargeStyle }, h("span", null, charge.level == null ? "—" : `${Math.round(charge.level)}%`)),
          h("div", { className: "tescmd-metric-row" }, h("span", null, "State"), h("strong", null, charge.state || "unknown")),
          h("div", { className: "tescmd-metric-row" }, h("span", null, "Limit"), h("strong", null, charge.limit == null ? "—" : `${charge.limit}%`)),
          h("div", { className: "tescmd-metric-row" }, h("span", null, "Range"), h("strong", null, charge.range == null ? "—" : `${Math.round(charge.range)} mi`)),
          h("div", { className: "tescmd-metric-row" }, h("span", null, "Power"), h("strong", null, charge.power == null ? "—" : `${charge.power} kW`))
        ),
        h("div", { className: "tescmd-stack-widgets" },
          h("div", { className: "tescmd-mini-widget" }, h("span", null, "Climate"), h("strong", null, climate.on ? "On" : "Off"), h("small", null, `Inside ${climate.inside == null ? "—" : climate.inside.toFixed(1)}° · Outside ${climate.outside == null ? "—" : climate.outside.toFixed(1)}°`)),
          h("div", { className: "tescmd-mini-widget tescmd-security-widget" }, h("span", null, "Security"), h("strong", null, security.locked === true ? "Locked" : security.locked === false ? "Unlocked" : "Unknown"), h("small", null, `${security.openCount} open closure${security.openCount === 1 ? "" : "s"} · Sentry ${security.sentry ? "on" : "off/unknown"}`), h("em", null, closureText)),
          h("div", { className: "tescmd-mini-widget" }, h("span", null, "Location"), h("strong", null, visibleLocation.label), h("small", null, visibleLocation.note))
        ),
        h(LeafletMap, { visibleLocation })
      )
    );
  }

  function loadLeaflet() {
    if (window.L) return Promise.resolve(window.L);
    if (window.__tescmdLeafletPromise) return window.__tescmdLeafletPromise;
    window.__tescmdLeafletPromise = new Promise((resolve, reject) => {
      if (!document.querySelector('link[data-tescmd-leaflet="true"]')) {
        const link = document.createElement("link");
        link.rel = "stylesheet";
        link.href = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css";
        link.integrity = "sha256-p4NxAoJBhIINfQK5OfKX6W9OlU5Ee9M4HoH6zzqH4c=";
        link.crossOrigin = "";
        link.dataset.tescmdLeaflet = "true";
        document.head.appendChild(link);
      }
      const script = document.createElement("script");
      script.src = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js";
      script.integrity = "sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=";
      script.crossOrigin = "";
      script.onload = () => resolve(window.L);
      script.onerror = () => reject(new Error("Leaflet failed to load"));
      document.head.appendChild(script);
    });
    return window.__tescmdLeafletPromise;
  }

  function LeafletMap({ visibleLocation }) {
    const ref = hooks.useRef(null);
    const mapRef = hooks.useRef(null);
    const markerRef = hooks.useRef(null);
    const [mapStatus, setMapStatus] = hooks.useState("idle");
    const lat = visibleLocation && visibleLocation.lat;
    const lon = visibleLocation && visibleLocation.lon;
    const label = (visibleLocation && visibleLocation.label) || "No coordinates";
    const precise = Boolean(visibleLocation && visibleLocation.precise);

    hooks.useEffect(() => {
      if (lat == null || lon == null || !ref.current) {
        setMapStatus("idle");
        return undefined;
      }
      let cancelled = false;
      let resizeObserver = null;
      setMapStatus("loading");
      loadLeaflet().then((L) => {
        if (cancelled || !ref.current) return;
        if (!mapRef.current) {
          mapRef.current = L.map(ref.current, {
            zoomControl: false,
            attributionControl: true,
            scrollWheelZoom: false,
          }).setView([lat, lon], visibleLocation.zoom || 10);
          L.control.zoom({ position: "bottomright" }).addTo(mapRef.current);
          L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
            maxZoom: 19,
            attribution: "&copy; OpenStreetMap contributors",
          }).addTo(mapRef.current);
          const markerIcon = L.divIcon({
            className: "tescmd-map-marker",
            html: "<span></span>",
            iconSize: [22, 22],
            iconAnchor: [11, 11],
          });
          markerRef.current = L.marker([lat, lon], { icon: markerIcon }).addTo(mapRef.current);
        } else {
          mapRef.current.setView([lat, lon], visibleLocation.zoom || 10);
          markerRef.current.setLatLng([lat, lon]);
        }
        markerRef.current.bindPopup(visibleLocation.popup || "Approximate vehicle area");
        if (window.ResizeObserver && !resizeObserver) {
          resizeObserver = new ResizeObserver(() => mapRef.current && mapRef.current.invalidateSize());
          resizeObserver.observe(ref.current);
        }
        setMapStatus("ready");
        setTimeout(() => mapRef.current && mapRef.current.invalidateSize(), 40);
        setTimeout(() => mapRef.current && mapRef.current.invalidateSize(), 240);
        setTimeout(() => mapRef.current && mapRef.current.invalidateSize(), 900);
      }).catch(() => {
        if (!cancelled) setMapStatus("error");
      });
      return () => {
        cancelled = true;
        if (resizeObserver) resizeObserver.disconnect();
      };
    }, [lat, lon, precise, visibleLocation.zoom, visibleLocation.popup]);

    if (lat == null || lon == null) {
      return h("div", { className: "tescmd-map tescmd-map-empty" },
        h(EmptyState, {
          title: "No location fix yet",
          body: "The map stays blank until a vehicle location payload includes coordinates.",
          steps: ["Run Location for a read-only location check.", "If the vehicle is asleep, turn on wake + confirm before a wake-enabled read."],
          note: "Precise coordinates stay inside the dashboard payload and are not shown in slash summaries.",
        })
      );
    }
    return h("div", { className: "tescmd-map-shell" },
      h("div", { className: "tescmd-map-meta" }, h("strong", null, precise ? "Vehicle map" : "Approximate area"), h("span", null, label)),
      h("div", { ref, className: "tescmd-map" }),
      mapStatus === "error" ? h("div", { className: "tescmd-map-error", role: "status", "aria-live": "polite" },
        h(EmptyState, {
          title: "Map could not load",
          body: "The location read succeeded, but the dashboard map library did not load in this browser session.",
          steps: ["Refresh the dashboard or check browser network access to the map assets.", "The coordinates remain hidden here; use the redacted payload panel for troubleshooting detail."],
          note: precise ? "Precise map display stays opt-in and is not retried as a Tesla command." : "Approximate location text stays visible without exposing precise coordinates.",
        })
      ) : null,
      mapStatus === "loading" ? h("div", { className: "tescmd-map-loading", role: "status" }, "Loading map…") : null
    );
  }

  function commandCatalogText(value, fallback) {
    return sanitizeDashboardText(value, fallback || "command detail");
  }

  function commandParamSummary(command) {
    const params = command && command.parameters && typeof command.parameters === "object" ? command.parameters : {};
    const flags = command && command.sensitive_parameters && typeof command.sensitive_parameters === "object" ? command.sensitive_parameters : {};
    return Object.entries(params).map(([name, schema]) => {
      const bits = [commandCatalogText(name, "parameter")];
      if (schema && schema.type) bits.push(commandCatalogText(schema.type, "type"));
      if (Array.isArray(command.required) && command.required.includes(name)) bits.push("required");
      if (schema && schema.enum) bits.push(`one of ${schema.enum.map((item) => commandCatalogText(item, "value")).join("|")}`);
      if (schema && schema["x-sensitive"]) bits.push("sensitive");
      if (Array.isArray(flags[name]) && flags[name].length) bits.push(`privacy: ${flags[name].map((item) => commandCatalogText(item, "privacy flag")).join(", ")}`);
      return bits.join(" · ");
    });
  }

  function commandSafetyBadges(command) {
    const flags = command && command.sensitive_parameters && typeof command.sensitive_parameters === "object" ? command.sensitive_parameters : {};
    const flatFlags = new Set(Object.values(flags).flatMap((value) => Array.isArray(value) ? value : []));
    const badges = [];
    if (command && command.confirm_required) badges.push(["confirm", "tescmd-warn"]);
    else if (command && command.wake_capable) badges.push(["wake-aware", "tescmd-warn"]);
    else badges.push([commandCatalogText(command && command.kind ? command.kind : "read", "read"), "tescmd-ok"]);
    if (flatFlags.has("vehicle_identifier")) badges.push(["redact ID", "tescmd-warn"]);
    if (flatFlags.has("location_or_destination")) badges.push(["location", "tescmd-warn"]);
    if (flatFlags.has("secret_or_oauth_value") || flatFlags.has("schema_sensitive")) badges.push(["secret-safe", "tescmd-warn"]);
    return badges;
  }

  function commandSearchCorpus(command) {
    const params = command && command.parameters && typeof command.parameters === "object" ? Object.keys(command.parameters) : [];
    const flags = command && command.sensitive_parameters && typeof command.sensitive_parameters === "object" ? command.sensitive_parameters : {};
    const flatFlags = Object.values(flags).flatMap((value) => Array.isArray(value) ? value : []);
    const safetyNotes = Array.isArray(command && command.safety_notes) ? command.safety_notes : [];
    return [
      command && command.name,
      command && command.description,
      command && command.operation,
      command && command.category,
      command && command.kind,
      ...params,
      ...flatFlags,
      ...safetyNotes,
    ].filter(Boolean).join(" ").toLowerCase();
  }

  function commandMatchesSafetyFilter(command, safetyFilter) {
    if (!safetyFilter || safetyFilter === "all") return true;
    const flags = command && command.sensitive_parameters && typeof command.sensitive_parameters === "object" ? command.sensitive_parameters : {};
    const flatFlags = new Set(Object.values(flags).flatMap((value) => Array.isArray(value) ? value : []));
    if (safetyFilter === "confirm_required") return Boolean(command && command.confirm_required);
    if (safetyFilter === "wake_capable") return Boolean(command && command.wake_capable);
    if (safetyFilter === "secret_like") return flatFlags.has("secret_or_oauth_value") || flatFlags.has("schema_sensitive");
    return flatFlags.has(safetyFilter);
  }

  function commandPrivacySummary(catalog) {
    const summary = (catalog && catalog.privacy_summary) || {};
    const secretCount = (summary.secret_or_oauth_value || 0) + (summary.schema_sensitive || 0);
    return [
      ["confirm-gated", summary.confirm_required || 0, "tescmd-warn"],
      ["wake-capable", summary.wake_capable || 0, "tescmd-warn"],
      ["vehicle ID params", summary.vehicle_identifier || 0, "tescmd-warn"],
      ["location/destination params", summary.location_or_destination || 0, "tescmd-warn"],
      ["secret-like params", secretCount, "tescmd-warn"],
    ];
  }

  function activeCommandFilters(search, category, safetyFilter, safetyFilterLabels) {
    const filters = [];
    const query = String(search || "").trim();
    if (query) filters.push(`search: ${sanitizeDashboardText(query, "search")}`);
    if (category && category !== "all") filters.push(`category: ${commandCatalogText(category, "category")}`);
    if (safetyFilter && safetyFilter !== "all") filters.push(`safety: ${safetyFilterLabels[safetyFilter] || commandCatalogText(safetyFilter, "safety marker")}`);
    return filters;
  }

  function CommandCatalog({ catalog, search, setSearch, category, setCategory, safetyFilter, setSafetyFilter, loading, catalogError, retryCatalog }) {
    const catalogLoaded = Boolean(catalog && Array.isArray(catalog.commands));
    const commands = catalogLoaded ? catalog.commands : [];
    const categories = ["all", ...Object.keys((catalog && catalog.categories) || {}).sort()];
    const safetyFilters = ["all", ...((catalog && catalog.safety_filters) || []).filter((item) => item && item.count > 0).map((item) => item.value)];
    const safetyFilterLabels = Object.fromEntries(((catalog && catalog.safety_filters) || []).map((item) => [item.value, `${commandCatalogText(item.label, "Safety marker")} (${item.count || 0})`]));
    const queryText = String(search || "").trim().toLowerCase();
    const filtered = commands.filter((command) => {
      if (category && category !== "all" && command.category !== category) return false;
      if (!commandMatchesSafetyFilter(command, safetyFilter)) return false;
      if (!queryText) return true;
      return commandSearchCorpus(command).includes(queryText);
    });
    const privacySummary = commandPrivacySummary(catalog);
    const activeFilters = activeCommandFilters(search, category, safetyFilter, safetyFilterLabels);
    const resetFilters = () => {
      setSearch("");
      setCategory("all");
      setSafetyFilter("all");
    };
    return h(Card, { className: "tescmd-command-card" },
      h(CardHeader, null, h(CardTitle, null, "Commands")),
      h(CardContent, null,
        h("p", { className: "tescmd-muted" }, "Live catalog pulled from the plugin runtime tool specs. Change the native plugin surface and this list updates without a hand-maintained dashboard copy."),
        h("div", { className: "tescmd-command-privacy", role: "note", "aria-label": "Catalog privacy summary" },
          h("div", null,
            h("span", { className: "tescmd-widget-label" }, "Catalog privacy summary"),
            h("strong", null, "Safety markers across registered tools"),
            h("small", null, "Schema-sensitive parameters are grouped with secret-like counts so operators can scan the catalog without exposing raw tokens, vehicle IDs, destinations, or coordinates.")
          ),
          h("div", { className: "tescmd-command-privacy-grid" },
            privacySummary.map(([label, count, className]) => h("div", { key: label, className: "tescmd-command-privacy-stat" },
              h(Badge, { className }, count),
              h("span", null, label)
            ))
          )
        ),
        h("div", { className: "tescmd-command-toolbar" },
          h(TextInput, { label: "Search commands", value: search, setValue: setSearch, placeholder: "charge, auth, navigation…" }),
          h(Field, { label: "Category" }, h("select", { className: "tescmd-select", value: category, onChange: (event) => setCategory(event.target.value) },
            categories.map((item) => h("option", { key: item, value: item }, item === "all" ? "All categories" : `${item} (${(catalog.categories || {})[item] || 0})`))
          )),
          h(Field, { label: "Safety marker" }, h("select", { className: "tescmd-select", value: safetyFilter, onChange: (event) => setSafetyFilter(event.target.value) },
            safetyFilters.map((item) => h("option", { key: item, value: item }, item === "all" ? "All safety markers" : (safetyFilterLabels[item] || commandCatalogText(item, "Safety marker"))))
          )),
          h("div", { className: "tescmd-command-stat" }, h("span", null, "Total"), h("strong", null, catalog && catalog.count != null ? catalog.count : "—")),
          h("div", { className: "tescmd-command-stat" }, h("span", null, "Showing"), h("strong", null, loading ? "…" : filtered.length)),
          h(Button, { className: "tescmd-command-reset", onClick: resetFilters, disabled: activeFilters.length === 0 }, "Reset filters")
        ),
        activeFilters.length ? h("div", { className: "tescmd-command-active-filters", role: "status", "aria-live": "polite" },
          h("span", null, "Active filters"),
          activeFilters.map((filter) => h(Badge, { key: filter }, filter)),
          h("small", null, "Reset filters clears search, category, and safety marker without sending a Tesla command.")
        ) : null,
        h("div", { className: "tescmd-command-grid" },
          filtered.map((command) => {
            const params = commandParamSummary(command);
            const safetyBadges = commandSafetyBadges(command);
            const safetyNotes = Array.isArray(command.safety_notes) ? command.safety_notes : [];
            return h("article", { key: command.name, className: "tescmd-command-item" },
              h("div", { className: "tescmd-command-head" },
                h("code", null, commandCatalogText(command.name, "tescmd command")),
                h("div", { className: "tescmd-command-badges" },
                  safetyBadges.map(([label, className]) => h(Badge, { key: label, className }, commandCatalogText(label, "safety badge"))),
                  h(Badge, null, commandCatalogText(command.category, "uncategorized"))
                )
              ),
              h("p", null, commandCatalogText(command.description || command.operation, "No description available.")),
              safetyNotes.length ? h("ul", { className: "tescmd-command-safety" },
                safetyNotes.slice(0, 3).map((note) => h("li", { key: note }, commandCatalogText(note, "Safety note redacted.")))
              ) : null,
              h("div", { className: "tescmd-command-meta" },
                h("span", null, `operation: ${commandCatalogText(command.operation, "unknown")}`),
                command.command_name ? h("span", null, `tesla: ${commandCatalogText(command.command_name, "command")}`) : null
              ),
              params.length ? h("details", null,
                h("summary", null, `${params.length} parameter${params.length === 1 ? "" : "s"}`),
                h("ul", null, params.map((param) => h("li", { key: param }, param)))
              ) : h("small", { className: "tescmd-muted" }, "No parameters")
            );
          })
        ),
        !catalogLoaded && !catalogError ? h(EmptyState, {
          title: "Command catalog loading",
          body: "Hermes is fetching the live tescmd tool catalog from the plugin runtime.",
          steps: ["No Tesla vehicle command is sent while loading the catalog.", "Runtime metadata is sanitized before it appears in command names, safety notes, or parameter summaries."],
          note: "If this state persists, retry the catalog fetch or check the redacted payload/error panel.",
          action: retryCatalog ? h(Button, { onClick: retryCatalog, disabled: loading }, loading ? "Loading…" : "Retry catalog") : null,
        }) : null,
        catalogError ? h(EmptyState, {
          title: "Command catalog unavailable",
          body: catalogError,
          steps: ["Dashboard quick actions remain confirm-gated; this catalog is only a read-only operator reference.", "Retry after plugin/runtime setup is healthy."],
          note: "The error text is sanitized before rendering so tokens, vehicle identifiers, destinations, and coordinates stay hidden.",
          action: retryCatalog ? h(Button, { onClick: retryCatalog, disabled: loading }, loading ? "Loading…" : "Retry catalog") : null,
        }) : null,
        catalogLoaded && !filtered.length ? h(EmptyState, {
          title: "No commands match",
          body: "Try a different search term, category, or safety marker, or reset all command filters. The list is generated from the registered plugin tools, not maintained by dashboard copy.",
          note: "Resetting command filters only changes this dashboard view; it does not call Tesla or run a plugin command.",
          action: h(Button, { onClick: resetFilters }, "Reset command filters"),
        }) : null
      )
    );
  }

  function TeslaDashboard() {
    const [profile, setProfile] = hooks.useState("default");
    const [region, setRegion] = hooks.useState("");
    const [vin, setVin] = hooks.useState("");
    const [status, setStatus] = hooks.useState(null);
    const [vehicles, setVehicles] = hooks.useState([]);
    const [overview, setOverview] = hooks.useState(null);
    const [detail, setDetail] = hooks.useState(null);
    const [lastReadKind, setLastReadKind] = hooks.useState("");
    const [loading, setLoading] = hooks.useState(false);
    const [loadingMode, setLoadingMode] = hooks.useState("");
    const [error, setError] = hooks.useState("");
    const [confirm, setConfirm] = hooks.useState(false);
    const [lastActionStatus, setLastActionStatus] = hooks.useState("");
    const [wakeReads, setWakeReads] = hooks.useState(false);
    const [noCache, setNoCache] = hooks.useState(false);
    const [units, setUnits] = hooks.useState("");
    const [locationPrecision, setLocationPrecision] = hooks.useState("approximate");
    const [enabled, setEnabled] = hooks.useState(true);
    const [percent, setPercent] = hooks.useState("80");
    const [amps, setAmps] = hooks.useState("32");
    const [driverTemp, setDriverTemp] = hooks.useState("70");
    const [passengerTemp, setPassengerTemp] = hooks.useState("70");
    const [heaterLevel, setHeaterLevel] = hooks.useState("1");
    const [volume, setVolume] = hooks.useState("3");
    const [destination, setDestination] = hooks.useState("");
    const [lat, setLat] = hooks.useState("");
    const [lon, setLon] = hooks.useState("");
    const [placeIds, setPlaceIds] = hooks.useState("");
    const [activeTab, setActiveTab] = hooks.useState("overview");
    const [commandCatalog, setCommandCatalog] = hooks.useState(null);
    const [commandCatalogError, setCommandCatalogError] = hooks.useState("");
    const [commandCatalogLoading, setCommandCatalogLoading] = hooks.useState(false);
    const [commandSearch, setCommandSearch] = hooks.useState("");
    const [commandCategory, setCommandCategory] = hooks.useState("all");
    const [commandSafetyFilter, setCommandSafetyFilter] = hooks.useState("all");

    const query = (includeReadFlags) => {
      const params = new URLSearchParams();
      if (profile) params.set("profile", profile);
      if (region) params.set("region", region);
      if (vin) params.set("vin", vin);
      if (includeReadFlags) {
        if (wakeReads) params.set("wake", "true");
        if (confirm) params.set("confirm", "true");
        if (noCache) params.set("no_cache", "true");
        if (units) params.set("units", units);
      }
      return params.toString();
    };

    const overviewQuery = (overrideVin) => {
      const params = new URLSearchParams();
      const queryVin = overrideVin === undefined ? vin : overrideVin;
      if (profile) params.set("profile", profile);
      if (region) params.set("region", region);
      if (queryVin) params.set("vin", queryVin);
      if (noCache) params.set("no_cache", "true");
      if (units) params.set("units", units);
      return params.toString();
    };

    const refresh = hooks.useCallback(async (mode, overrideVin) => {
      setLoading(true);
      setLoadingMode(mode || (overview ? "refresh" : "initial"));
      setError("");
      try {
        const overviewPayload = await api(`/overview?${overviewQuery(overrideVin)}`);
        const statusPayload = overviewPayload.status || null;
        const vehiclePayload = overviewPayload.vehicles || {};
        setOverview(overviewPayload);
        setStatus(statusPayload);
        setVehicles(Array.isArray(vehiclePayload.vehicles) ? vehiclePayload.vehicles : []);
        setDetail(overviewPayload);
      } catch (err) {
        setError(dashboardErrorMessage(err));
      } finally {
        setLoading(false);
        setLoadingMode("");
      }
    }, [profile, region, vin, noCache, units, overview]);

    hooks.useEffect(() => { refresh("initial"); }, []);

    const loadCommandCatalog = hooks.useCallback(async () => {
      setCommandCatalogLoading(true);
      setCommandCatalogError("");
      try {
        const payload = await api("/commands");
        setCommandCatalog(payload);
      } catch (err) {
        setCommandCatalog(null);
        setCommandCatalogError(dashboardErrorMessage(err));
      } finally {
        setCommandCatalogLoading(false);
      }
    }, []);

    hooks.useEffect(() => {
      let cancelled = false;
      setCommandCatalogLoading(true);
      setCommandCatalogError("");
      api("/commands")
        .then((payload) => {
          if (!cancelled) setCommandCatalog(payload);
        })
        .catch((err) => {
          if (!cancelled) {
            setCommandCatalog(null);
            setCommandCatalogError(dashboardErrorMessage(err));
          }
        })
        .finally(() => {
          if (!cancelled) setCommandCatalogLoading(false);
        });
      return () => { cancelled = true; };
    }, []);

    async function runRead(kind) {
      setLoading(true);
      setLoadingMode("refresh");
      setError("");
      try {
        const payload = await api(`/read/${kind}?${query(true)}`);
        setDetail(payload);
        setLastReadKind(kind);
        if (["charge", "location", "drive", "climate", "closures", "security"].includes(kind)) {
          await refresh();
        }
      } catch (err) {
        setError(dashboardErrorMessage(err));
      } finally {
        setLoading(false);
        setLoadingMode("");
      }
    }

    function numeric(text) {
      if (text === "" || text === null || text === undefined) return null;
      const value = Number(text);
      return Number.isFinite(value) ? value : null;
    }

    function actionBody(action) {
      const body = { action, vin: vin || null, profile: profile || "default", region: region || null, confirm };
      if (action === "sentry") body.enabled = enabled;
      if (action === "charge-limit") body.percent = numeric(percent);
      if (action === "charge-amps") body.amps = numeric(amps);
      if (action === "set-temp") {
        body.driver_temp = numeric(driverTemp);
        body.passenger_temp = numeric(passengerTemp);
      }
      if (action === "seat-heat-driver" || action === "seat-heat-passenger" || action === "steering-heat-level") body.level = numeric(heaterLevel);
      if (action === "media-volume-set") body.volume = numeric(volume);
      if (action === "nav") body.destination = destination.trim();
      if (action === "nav-gps") {
        body.lat = numeric(lat);
        body.lon = numeric(lon);
      }
      if (action === "nav-waypoints") body.place_ids = placeIds.split(",").map((x) => x.trim()).filter(Boolean);
      return body;
    }

    function actionDisabledReason(action) {
      const controls = controlReadiness(percent, amps, driverTemp, passengerTemp, volume, heaterLevel);
      if (action === "charge-limit" && !controls.chargeLimitReady) return "Enter a charge limit from 1 to 100 before changing charging.";
      if (action === "charge-amps" && !controls.chargeAmpsReady) return "Enter charging amps from 1 to 80 before changing charging.";
      if (action === "set-temp" && !controls.temperatureReady) return "Enter driver and passenger temperatures from 50° to 90° before changing climate.";
      if (["seat-heat-driver", "seat-heat-passenger", "steering-heat-level"].includes(action) && !controls.heaterLevelReady) return "Enter a heater level from 0 to 3 before changing seat or steering heat.";
      if (action === "media-volume-set" && !controls.volumeReady) return "Enter a volume level from 0 to 11 before changing media volume.";
      if (action === "nav" && !destination.trim()) return "Enter a destination before sending navigation.";
      if (action === "nav-gps" && !routeReadiness("", lat, lon, "").gpsReady) return "Enter latitude from -90 to 90 and longitude from -180 to 180 before sending GPS navigation.";
      if (action === "nav-waypoints" && !placeIds.split(",").map((x) => x.trim()).filter(Boolean).length) return "Enter at least one place ID before sending waypoints.";
      return "";
    }

    function clearNavigationFields(action) {
      if (action === "nav") setDestination("");
      if (action === "nav-gps") {
        setLat("");
        setLon("");
      }
      if (action === "nav-waypoints") setPlaceIds("");
    }

    function clearAllNavigationFields() {
      setDestination("");
      setLat("");
      setLon("");
      setPlaceIds("");
    }

    function dashboardActionStatus(payload, action, navigationAction) {
      const response = payload && payload.response && typeof payload.response === "object" ? payload.response : {};
      const rawMessage = firstDefined(
        payload && payload.message,
        response.message,
        typeof response.result === "string" ? response.result : undefined,
        typeof (payload && payload.result) === "string" ? payload.result : undefined,
        payload && payload.error
      );
      const actionLabel = sanitizeDashboardText(String(action || "Tesla action").replace(/-/g, " "), "Tesla action");
      const fallback = payload && payload.ok === false
        ? `Tesla returned a problem for ${actionLabel}.`
        : `Tesla accepted the ${actionLabel} command.`;
      const message = sanitizeDashboardText(rawMessage, fallback);
      const suffix = navigationAction
        ? " Route fields were cleared; physical actions are locked again."
        : " Physical actions are locked again.";
      return `${message}${suffix}`;
    }

    async function setDefaultVehicle(nextVin) {
      setLoading(true);
      setLoadingMode("refresh");
      setError("");
      setLastActionStatus("");
      try {
        const payload = await api("/default-vehicle", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ profile: profile || "default", vin: nextVin || null }),
        });
        setDetail(payload);
        setLastActionStatus(sanitizeDashboardText(payload.message, "Default Tesla vehicle updated."));
        setVin("");
        await refresh("refresh", "");
      } catch (err) {
        setError(dashboardErrorMessage(err));
      } finally {
        setLoading(false);
        setLoadingMode("");
      }
    }

    async function runAction(action) {
      const navigationAction = action === "nav" || action === "nav-gps" || action === "nav-waypoints";
      const disabledReason = actionDisabledReason(action);
      if (disabledReason) {
        setConfirm(false);
        setLastActionStatus(`${disabledReason} Physical actions are locked again.`);
        return;
      }

      setLoading(true);
      setLoadingMode("refresh");
      setError("");
      setLastActionStatus("");
      try {
        const payload = await api("/quick-action", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(actionBody(action)),
        });
        setDetail(payload);
        setLastReadKind("");
        setConfirm(false);
        if (navigationAction) clearNavigationFields(action);
        setLastActionStatus(dashboardActionStatus(payload, action, navigationAction));
        await refresh();
      } catch (err) {
        setError(dashboardErrorMessage(err));
        if (navigationAction) clearNavigationFields(action);
        setLastActionStatus(navigationAction
          ? `Attempted ${action}; route fields were cleared and confirmation is locked off after the request.`
          : `Attempted ${action}; confirmation is still locked off after the request.`);
        setConfirm(false);
      } finally {
        setLoading(false);
        setLoadingMode("");
      }
    }

    return h("div", { className: "tescmd-page" },
      h("section", { className: "tescmd-hero" },
        h("div", null,
          h("p", { className: "tescmd-kicker" }, "Hermes Tesla Command Center"),
          h("h1", null, "Tesla command center"),
          h("p", { className: "tescmd-muted" }, "Compact setup guidance, visual vehicle state, live location, and confirm-gated Tesla quick actions from the native tescmd plugin.")
        ),
        h("div", { className: "tescmd-hero-actions" },
          h(Badge, { className: confirm ? "tescmd-warn" : "tescmd-ok" }, confirm ? "actions armed" : "read-only"),
          h(Button, { onClick: () => refresh("refresh"), disabled: loading }, loading ? (loadingMode === "initial" ? "Loading..." : "Updating...") : "Refresh overview")
        )
      ),
      h(BusyBanner, { loading, mode: loadingMode }),
      h("nav", { className: "tescmd-tabs", "aria-label": "Tesla dashboard tabs" },
        [["overview", "Overview"], ["commands", "Commands"]].map(([key, label]) =>
          h(Button, { key, className: activeTab === key ? "tescmd-tab-active" : "", onClick: () => setActiveTab(key) }, label)
        )
      ),
      activeTab === "commands" ? h(CommandCatalog, {
        catalog: commandCatalog,
        search: commandSearch,
        setSearch: setCommandSearch,
        category: commandCategory,
        setCategory: setCommandCategory,
        safetyFilter: commandSafetyFilter,
        setSafetyFilter: setCommandSafetyFilter,
        loading: commandCatalogLoading,
        catalogError: commandCatalogError,
        retryCatalog: loadCommandCatalog,
      }) : [
        overview && overview.onboarding ? h(OnboardingCard, { key: "onboarding", onboarding: overview.onboarding }) : null,
        h(Card, { key: "overview", className: "tescmd-overview-card" },
          h(CardHeader, null, h(CardTitle, null, "Vehicle overview")),
          h(CardContent, null, overview ? h(VehicleSnapshot, { overview, runAction, loading, confirm, locationPrecision }) : h(EmptyState, {
            title: "No vehicle overview loaded",
            body: "Start with a read-only refresh to populate charge, climate, security, and map widgets.",
            steps: ["Check profile, region, and vehicle override if the configured default is not the target vehicle.", "Use no-cache when you need fresh Fleet API data.", "Only enable wake + confirm when you intentionally want to wake a sleeping vehicle."],
            note: "Refreshing the overview does not arm quick actions or run physical Tesla side effects.",
            action: h(Button, { onClick: () => refresh("refresh"), disabled: loading }, loading ? "Loading..." : "Refresh overview"),
          }))
        ),
        h(Card, { key: "options", className: "tescmd-controls-card" },
          h(CardHeader, null, h(CardTitle, null, "Options")),
          h(CardContent, null,
            h("div", { className: "tescmd-controls" },
              h(TextInput, { label: "Profile", value: profile, setValue: setProfile, placeholder: "default" }),
              h(Field, { label: "Region" }, h("select", { className: "tescmd-select", value: region, onChange: (event) => setRegion(event.target.value) },
                h("option", { value: "" }, "Configured"), h("option", { value: "na" }, "NA"), h("option", { value: "eu" }, "EU"), h("option", { value: "cn" }, "CN")
              )),
              h(VehiclePicker, { vehicles, vin, setVin, setDefaultVehicle, loading }),
              h(TargetContextPanel, { targetContext: overview && overview.target_context }),
              h(ReadContextPanel, { readContext: overview && overview.read_context }),
              h(Field, { label: "Read options" },
                h("label", { className: "tescmd-inline" }, h("input", { type: "checkbox", checked: wakeReads, onChange: (event) => setWakeReads(event.target.checked) }), " wake"),
                h("label", { className: "tescmd-inline" }, h("input", { type: "checkbox", checked: noCache, onChange: (event) => setNoCache(event.target.checked) }), " no cache")
              ),
              h(Field, { label: "Units" }, h("select", { className: "tescmd-select", value: units, onChange: (event) => setUnits(event.target.value) },
                h("option", { value: "" }, "Configured"), h("option", { value: "metric" }, "Metric"), h("option", { value: "us" }, "US")
              )),
              h(Field, { label: "Location display" },
                h("select", { className: "tescmd-select", value: locationPrecision, onChange: (event) => setLocationPrecision(event.target.value) },
                  h("option", { value: "approximate" }, "Approximate area"), h("option", { value: "precise" }, "Precise coordinates")
                ),
                h("small", { className: "tescmd-muted" }, "Approximate mode rounds visible map text and marker position; raw payload stays redacted below.")
              )
            ),
            h(ReadSafetyPanel, { wakeReads, confirm }),
            status ? h(Readiness, { status }) : null,
            status ? h(ScopeReadinessPanel, { status }) : null
          )
        ),
        h("div", { key: "workbench", className: "tescmd-workbench" },
          h(Card, null,
            h(CardHeader, null, h(CardTitle, null, "Reads")),
            h(CardContent, null,
              h("p", { className: "tescmd-muted" }, "Wake-enabled reads require both the wake checkbox and confirm below; otherwise they fail closed."),
              READ_GROUPS.map(([title, reads]) => h(ReadGroup, { key: title, title, reads, runRead, loading }))
            )
          ),
          h(Card, null,
            h(CardHeader, null, h(CardTitle, null, "Guarded quick actions")),
            h(CardContent, null,
              h(ActionSafetyPanel, { confirm, loading, lastActionStatus }),
              h("label", { className: "tescmd-confirm" }, h("input", { type: "checkbox", checked: confirm, onChange: (event) => setConfirm(event.target.checked) }), h("span", null, "I confirm this physical Tesla side effect")),
              h("div", { className: "tescmd-controls" },
                h(Field, { label: "Sentry" }, h("select", { className: "tescmd-select", value: enabled ? "true" : "false", onChange: (event) => setEnabled(event.target.value === "true") }, h("option", { value: "true" }, "Enable"), h("option", { value: "false" }, "Disable"))),
                h(TextInput, { label: "Charge limit %", value: percent, setValue: setPercent, type: "number", min: "1", max: "100", step: "1", inputMode: "numeric", helpText: "Allowed range 1–100%; the value is never echoed in status copy until a confirmed action runs." }),
                h(TextInput, { label: "Charge amps", value: amps, setValue: setAmps, type: "number", min: "1", max: "80", step: "1", inputMode: "numeric", helpText: "Allowed range 1–80 amps; invalid values keep the charging button disabled." }),
                h(TextInput, { label: "Driver temp", value: driverTemp, setValue: setDriverTemp, type: "number", min: "50", max: "90", step: "0.5", inputMode: "decimal", helpText: "Cabin temperature guardrail: 50°–90°." }),
                h(TextInput, { label: "Passenger temp", value: passengerTemp, setValue: setPassengerTemp, type: "number", min: "50", max: "90", step: "0.5", inputMode: "decimal", helpText: "Cabin temperature guardrail: 50°–90°." }),
                h(TextInput, { label: "Heater level", value: heaterLevel, setValue: setHeaterLevel, type: "number", min: "0", max: "3", step: "1", inputMode: "numeric", helpText: "Seat and steering heat guardrail: 0 off, 1–3 warming levels; invalid values keep heater buttons disabled." }),
                h(TextInput, { label: "Volume", value: volume, setValue: setVolume, type: "number", min: "0", max: "11", step: "1", inputMode: "numeric", helpText: "Allowed volume range 0–11; invalid values keep media changes disabled." })
              ),
              h("div", { className: "tescmd-controls" },
                h(TextInput, { label: "Destination", value: destination, setValue: setDestination, placeholder: "address or place" }),
                h(TextInput, { label: "Latitude", value: lat, setValue: setLat, type: "number", min: "-90", max: "90", step: "0.000001", inputMode: "decimal", helpText: "Latitude must be from -90 to 90; precise coordinates are cleared after attempts." }),
                h(TextInput, { label: "Longitude", value: lon, setValue: setLon, type: "number", min: "-180", max: "180", step: "0.000001", inputMode: "decimal", helpText: "Longitude must be from -180 to 180; precise coordinates are never echoed in guidance." }),
                h(TextInput, { label: "Place IDs", value: placeIds, setValue: setPlaceIds, placeholder: "id1,id2" })
              ),
              h(NavigationGuardPanel, { destination, lat, lon, placeIds, clearRouteFields: clearAllNavigationFields }),
              h(ActionRequirementsPanel, { confirm, destination, lat, lon, placeIds, percent, amps, driverTemp, passengerTemp, volume, heaterLevel }),
              ACTION_GROUPS.map(([title, actions]) => h(ActionGroup, { key: title, title, actions, runAction, loading, confirm, actionDisabledReason })),
              h("p", { className: "tescmd-muted" }, "Higher-risk flows like remote-start-drive, speed limit PINs, valet/PIN-to-drive, erase-user-data, and raw API calls remain tool-only with explicit confirm=true.")
            )
          ),
          error ? h(Card, { className: "tescmd-error-card" }, h(CardContent, null, h("p", { className: "tescmd-error" }, error))) : null,
          h(Card, { className: "tescmd-payload-card" },
            h(CardHeader, null, h(CardTitle, null, "Redacted last payload")),
            h(CardContent, null,
              h(PayloadPrivacyToolbar, { hasPayload: Boolean(detail), clearPayload: () => { setDetail(null); setLastReadKind(""); } }),
              h("p", { className: "tescmd-muted" }, "Debug view hides full vehicle identifiers, tokens, driver contact details, navigation destinations, and precise coordinates."),
              h(DashboardReadSummary, { detail, lastReadKind }),
              detail ? h(JsonBlock, { data: detail }) : h(EmptyState, {
                title: "No payload selected",
                body: "Run a read or a confirm-gated quick action to inspect the latest redacted plugin response here.",
                steps: ["Reads are safe by default and only wake the vehicle when wake + confirm are both enabled.", "Quick actions stay disabled until you check the physical side-effect confirmation."],
                note: "Sensitive IDs and raw coordinates should stay out of human-facing slash summaries.",
              })
            )
          )
        )
      ]
    );
  }

  function HeaderWidget() {
    return h("span", { className: "tescmd-header-pill", title: "Tesla dashboard plugin installed" }, "Tesla");
  }

  window.__HERMES_PLUGINS__.register("hermes-tescmd-plugin", TeslaDashboard);
  window.__HERMES_PLUGINS__.registerSlot("hermes-tescmd-plugin", "header-right", HeaderWidget);
})();
