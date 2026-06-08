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
    ["Services", [["nearby-chargers", "Nearby chargers"], ["mobile-access", "Mobile access"], ["drivers", "Drivers"], ["service", "Service"], ["charge-schedule", "Charge schedules"], ["preconditioning-schedule", "Preconditioning"]]],
    ["Admin", [["auth-status", "Auth"], ["onboarding", "Onboarding"], ["key-show", "Key"], ["key-validate", "Validate key"], ["cache-status", "Cache"]]],
  ];

  const ACTION_GROUPS = [
    ["Attention & security", [["wake", "Wake"], ["flash", "Flash"], ["honk", "Honk"], ["lock", "Lock"], ["unlock", "Unlock"], ["sentry", "Sentry on/off"]]],
    ["Climate", [["climate-start", "Climate start"], ["climate-stop", "Climate stop"], ["set-temp", "Set temp"]]],
    ["Charging", [["charge-start", "Charge start"], ["charge-stop", "Charge stop"], ["charge-limit", "Set limit"], ["charge-amps", "Set amps"], ["charge-port-open", "Port open"], ["charge-port-close", "Port close"]]],
    ["Body", [["frunk", "Frunk"], ["trunk-open", "Trunk open"], ["trunk-close", "Trunk close"], ["window-vent", "Vent windows"], ["window-close", "Close windows"]]],
    ["Media & navigation", [["media-play", "Play/pause"], ["media-next", "Next"], ["media-prev", "Previous"], ["media-volume-up", "Vol +"], ["media-volume-down", "Vol -"], ["media-volume-set", "Set volume"], ["nav", "Navigate"], ["nav-gps", "Nav GPS"], ["nav-waypoints", "Waypoints"]]],
  ];

  function JsonBlock({ data }) {
    const displayData = data && data.display_payload ? data.display_payload : data;
    return h("pre", { className: "tescmd-json" }, JSON.stringify(displayData, null, 2));
  }

  function Field({ label, children }) {
    return h("div", { className: "tescmd-field" }, h(Label, null, label), children);
  }

  function TextInput({ label, value, setValue, placeholder, type }) {
    return h(Field, { label }, h(Input, {
      type: type || "text",
      value: value ?? "",
      placeholder,
      onChange: (event) => setValue(event.target.value),
    }));
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

  function OnboardingCard({ onboarding }) {
    if (!onboarding) return null;
    const missing = Array.isArray(onboarding.missing_prerequisites)
      ? onboarding.missing_prerequisites.map((item) => sanitizeDashboardText(item, "setup item"))
      : [];
    const steps = Array.isArray(onboarding.next_steps)
      ? onboarding.next_steps.slice(0, 2).map((step) => sanitizeDashboardText(step, "setup step"))
      : [];
    if (onboardingOperational(onboarding)) return null;
    const next = sanitizeDashboardText(onboarding.next_tool || onboarding.next_action || "Ready", "Ready");
    const docsAnchor = sanitizeDashboardText(onboarding.docs_anchor || "docs/ONBOARDING.md", "docs/ONBOARDING.md");
    return h("div", { className: "tescmd-onboarding-card" },
      h("div", null,
        h("span", { className: "tescmd-widget-label" }, "Next setup step"),
        h("strong", null, next),
        h("small", null, docsAnchor)
      ),
      missing.length
        ? h("div", { className: "tescmd-missing-list" }, missing.slice(0, 4).map((item, index) => h(Badge, { key: `${item}-${index}`, className: "tescmd-warn" }, item)))
        : h(Badge, { className: "tescmd-ok" }, "no missing prerequisites"),
      steps.length ? h("ol", null, steps.map((step, index) => h("li", { key: index }, step))) : null,
      h("small", { className: "tescmd-muted" }, "Setup guidance is sanitized before display; OAuth values, vehicle identifiers, and precise route/location details stay hidden.")
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

  function ScopeReadinessPanel({ status }) {
    const scopeReadiness = scopeReadinessFromStatus(status);
    if (!scopeReadiness) return null;
    const grantSource = sanitizeDashboardText(scopeReadiness.grant_scope_source || "unknown", "unknown");
    const missingGranted = Array.isArray(scopeReadiness.missing_granted_user_scopes)
      ? scopeReadiness.missing_granted_user_scopes.map((item) => sanitizeDashboardText(item, "scope"))
      : [];
    const capabilities = scopeCapabilityRows(scopeReadiness);
    const blocked = missingGranted.length > 0 || capabilities.some((item) => !item.ready);
    return h("div", { className: blocked ? "tescmd-scope-readiness tescmd-scope-readiness-warn" : "tescmd-scope-readiness", role: "status", "aria-live": "polite" },
      h("div", null,
        h("span", { className: "tescmd-widget-label" }, "OAuth scope readiness"),
        h("strong", null, blocked ? "Some Tesla capabilities need scopes" : "Tesla OAuth scopes look ready"),
        h("small", null, `Scope source: ${grantSource}. Missing scope names are shown without tokens, vehicle identifiers, or callback values.`)
      ),
      h("div", { className: "tescmd-scope-grid" },
        missingGranted.length
          ? h("div", { className: "tescmd-scope-missing" }, h("span", null, "Missing granted"), missingGranted.slice(0, 4).map((scope) => h(Badge, { key: scope, className: "tescmd-warn" }, scope)))
          : h(Badge, { className: "tescmd-ok" }, "no missing granted scopes"),
        capabilities.slice(0, 4).map((item) => h("div", { key: item.name, className: "tescmd-scope-capability" },
          h("span", null, item.name),
          h(Badge, { className: item.ready ? "tescmd-ok" : "tescmd-warn" }, item.ready ? "ready" : `needs ${item.missing.join(", ") || "scope"}`)
        ))
      )
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
    const text = redactVisibleIdentifierText(rawText)
      .replace(/([?&](?:code|state|access_token|refresh_token|id_token|client_secret|token)=)[^&\s]+/gi, "$1[REDACTED]")
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
      h(Input, {
        placeholder: "VIN or id_s override",
        value: vin || "",
        onChange: (event) => setVin(event.target.value),
      }),
      h("div", { className: "tescmd-inline-actions" },
        h(Button, { onClick: () => setDefaultVehicle(vin), disabled: loading || !vin }, "Make selected default"),
        h(Button, { onClick: () => setDefaultVehicle(""), disabled: loading }, "Clear dashboard default")
      ),
      h("small", { className: "tescmd-muted" }, "Vehicle menu labels show safe model hints only; full VIN/Fleet IDs stay out of visible option text. Saving a default stores the selected identifier in plugin config while visible text stays redacted.")
    );
  }

  function ActionGroup({ title, actions, runAction, loading, confirm, actionDisabledReason }) {
    return h("div", { className: "tescmd-group" },
      h("h3", null, title),
      h("div", { className: "tescmd-actions" },
        actions.map(([action, label]) => {
          const reason = actionDisabledReason ? actionDisabledReason(action) : "";
          const disabled = loading || !confirm || Boolean(reason);
          return h(Button, {
            key: action,
            onClick: () => runAction(action),
            disabled,
            title: reason || (!confirm ? "Turn on confirmation before physical Tesla actions." : undefined),
          }, label);
        })
      )
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

  function NavigationGuardPanel({ destination, lat, lon, placeIds }) {
    const hasDestination = String(destination || "").trim() !== "";
    const hasLat = String(lat || "").trim() !== "";
    const hasLon = String(lon || "").trim() !== "";
    const waypointCount = String(placeIds || "").split(",").map((value) => value.trim()).filter(Boolean).length;
    const navReady = hasDestination;
    const gpsReady = hasLat && hasLon;
    const waypointReady = waypointCount > 0;
    return h("div", { className: "tescmd-nav-guard", role: "note", "aria-label": "Navigation action guardrails" },
      h("div", null,
        h("span", { className: "tescmd-widget-label" }, "Navigation guardrail"),
        h("strong", null, navReady || gpsReady || waypointReady ? "Route fields ready" : "No route target entered"),
        h("small", null, "Navigation buttons stay unavailable until their required destination fields are present. After a navigation action is sent, route fields are cleared from dashboard state.")
      ),
      h("div", { className: "tescmd-nav-guard-badges" },
        h(Badge, { className: navReady ? "tescmd-ok" : "tescmd-warn" }, navReady ? "destination set" : "destination needed"),
        h(Badge, { className: gpsReady ? "tescmd-ok" : "tescmd-warn" }, gpsReady ? "GPS pair set" : "lat/lon needed"),
        h(Badge, { className: waypointReady ? "tescmd-ok" : "tescmd-warn" }, waypointReady ? `${waypointCount} waypoint${waypointCount === 1 ? "" : "s"}` : "place IDs needed")
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

  function securitySummary(overview) {
    const security = objectAt(section(overview, "security"), ["vehicle_state", "security_state"]);
    const closures = objectAt(section(overview, "closures"), ["closures_state", "vehicle_state"]);
    const locked = firstDefined(security.locked, closures.locked);
    const sentry = firstDefined(security.sentry_mode, security.sentry_mode_available && security.sentry_mode);
    const openBits = ["df", "pf", "dr", "pr", "ft", "rt"].filter((key) => closures[key] && closures[key] !== 0 && closures[key] !== "closed");
    return { locked, sentry, openCount: openBits.length };
  }

  function locationSummary(overview) {
    const location = objectAt(section(overview, "location"), ["location", "location_data", "drive_state"]);
    const drive = objectAt(section(overview, "drive"), ["drive_state", "location_data"]);
    const lat = numericValue(location.latitude, location.lat, drive.latitude, drive.lat);
    const lon = numericValue(location.longitude, location.lon, location.lng, drive.longitude, drive.lon, drive.lng);
    const heading = numericValue(location.heading, drive.heading, location.native_latitude, drive.native_latitude);
    const speed = numericValue(drive.speed, location.speed);
    return { lat, lon, heading, speed, raw: Object.keys(location).length ? location : drive };
  }

  function displayLocation(location, precision) {
    const lat = location && location.lat;
    const lon = location && location.lon;
    if (lat == null || lon == null) return { lat: null, lon: null, label: "No coordinates", note: "Speed unavailable", precise: false };
    const precise = precision === "precise";
    const displayLat = precise ? lat : Number(lat.toFixed(2));
    const displayLon = precise ? lon : Number(lon.toFixed(2));
    const coordLabel = precise
      ? `${lat.toFixed(5)}, ${lon.toFixed(5)}`
      : `≈ ${displayLat.toFixed(2)}, ${displayLon.toFixed(2)}`;
    const speedNote = location.speed == null ? "Speed unavailable" : `${location.speed} mph`;
    return {
      lat: displayLat,
      lon: displayLon,
      label: coordLabel,
      note: precise ? `${speedNote} · precise coordinates visible` : `${speedNote} · precise coordinates hidden`,
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
          h("div", { className: "tescmd-mini-widget" }, h("span", null, "Security"), h("strong", null, security.locked === true ? "Locked" : security.locked === false ? "Unlocked" : "Unknown"), h("small", null, `${security.openCount} open closure${security.openCount === 1 ? "" : "s"} · Sentry ${security.sentry ? "on" : "off/unknown"}`)),
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
    const lat = visibleLocation && visibleLocation.lat;
    const lon = visibleLocation && visibleLocation.lon;
    const label = (visibleLocation && visibleLocation.label) || "No coordinates";
    const precise = Boolean(visibleLocation && visibleLocation.precise);

    hooks.useEffect(() => {
      if (lat == null || lon == null || !ref.current) return undefined;
      let cancelled = false;
      let resizeObserver = null;
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
        setTimeout(() => mapRef.current && mapRef.current.invalidateSize(), 40);
        setTimeout(() => mapRef.current && mapRef.current.invalidateSize(), 240);
        setTimeout(() => mapRef.current && mapRef.current.invalidateSize(), 900);
      }).catch(() => {});
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
      h("div", { ref, className: "tescmd-map" })
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
          h("div", { className: "tescmd-command-stat" }, h("span", null, "Showing"), h("strong", null, loading ? "…" : filtered.length))
        ),
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
          body: "Try a different search term, category, or safety marker. The list is generated from the registered plugin tools, not maintained by dashboard copy.",
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
      if (action === "nav" && !destination.trim()) return "Enter a destination before sending navigation.";
      if (action === "nav-gps" && (numeric(lat) === null || numeric(lon) === null)) return "Enter both latitude and longitude before sending GPS navigation.";
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
                h(TextInput, { label: "Charge limit %", value: percent, setValue: setPercent, type: "number" }),
                h(TextInput, { label: "Charge amps", value: amps, setValue: setAmps, type: "number" }),
                h(TextInput, { label: "Driver temp", value: driverTemp, setValue: setDriverTemp, type: "number" }),
                h(TextInput, { label: "Passenger temp", value: passengerTemp, setValue: setPassengerTemp, type: "number" }),
                h(TextInput, { label: "Volume", value: volume, setValue: setVolume, type: "number" })
              ),
              h("div", { className: "tescmd-controls" },
                h(TextInput, { label: "Destination", value: destination, setValue: setDestination, placeholder: "address or place" }),
                h(TextInput, { label: "Latitude", value: lat, setValue: setLat, type: "number" }),
                h(TextInput, { label: "Longitude", value: lon, setValue: setLon, type: "number" }),
                h(TextInput, { label: "Place IDs", value: placeIds, setValue: setPlaceIds, placeholder: "id1,id2" })
              ),
              h(NavigationGuardPanel, { destination, lat, lon, placeIds }),
              ACTION_GROUPS.map(([title, actions]) => h(ActionGroup, { key: title, title, actions, runAction, loading, confirm, actionDisabledReason })),
              h("p", { className: "tescmd-muted" }, "Higher-risk flows like remote-start-drive, speed limit PINs, valet/PIN-to-drive, erase-user-data, and raw API calls remain tool-only with explicit confirm=true.")
            )
          ),
          error ? h(Card, { className: "tescmd-error-card" }, h(CardContent, null, h("p", { className: "tescmd-error" }, error))) : null,
          h(Card, { className: "tescmd-payload-card" },
            h(CardHeader, null, h(CardTitle, null, "Redacted last payload")),
            h(CardContent, null,
              h("p", { className: "tescmd-muted" }, "Debug view hides full vehicle identifiers, tokens, navigation destinations, and precise coordinates."),
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
