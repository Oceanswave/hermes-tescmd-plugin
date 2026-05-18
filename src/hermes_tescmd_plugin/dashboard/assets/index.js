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
    ["Admin", [["auth-status", "Auth"], ["key-show", "Key"], ["key-validate", "Validate key"], ["cache-status", "Cache"]]],
  ];

  const ACTION_GROUPS = [
    ["Attention & security", [["wake", "Wake"], ["flash", "Flash"], ["honk", "Honk"], ["lock", "Lock"], ["unlock", "Unlock"], ["sentry", "Sentry on/off"]]],
    ["Climate", [["climate-start", "Climate start"], ["climate-stop", "Climate stop"], ["set-temp", "Set temp"]]],
    ["Charging", [["charge-start", "Charge start"], ["charge-stop", "Charge stop"], ["charge-limit", "Set limit"], ["charge-amps", "Set amps"], ["charge-port-open", "Port open"], ["charge-port-close", "Port close"]]],
    ["Body", [["frunk", "Frunk"], ["trunk-open", "Trunk open"], ["trunk-close", "Trunk close"], ["window-vent", "Vent windows"], ["window-close", "Close windows"]]],
    ["Media & navigation", [["media-play", "Play/pause"], ["media-next", "Next"], ["media-prev", "Previous"], ["media-volume-up", "Vol +"], ["media-volume-down", "Vol -"], ["media-volume-set", "Set volume"], ["nav", "Navigate"], ["nav-gps", "Nav GPS"], ["nav-waypoints", "Waypoints"]]],
  ];

  function JsonBlock({ data }) {
    return h("pre", { className: "tescmd-json" }, JSON.stringify(data, null, 2));
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

  function readinessRows(status) {
    const bootstrap = (status && status.bootstrap) || {};
    return [
      ["App", bootstrap.app_configured],
      ["Auth", bootstrap.authenticated],
      ["Reads", bootstrap.ready_for_vehicle_reads],
      ["Commands", bootstrap.ready_for_vehicle_commands],
      ["Signed", bootstrap.ready_for_signed_commands],
      ["Key hosted", bootstrap.key_hosting_ready],
    ];
  }

  function Readiness({ status }) {
    return h("div", { className: "tescmd-readiness" },
      readinessRows(status).map(([label, value]) =>
        h("div", { key: label, className: "tescmd-readiness-item" },
          h("span", null, label),
          h(Badge, { className: value ? "tescmd-ok" : "tescmd-warn" }, value ? "ready" : "missing")
        )
      )
    );
  }

  function VehiclePicker({ vehicles, vin, setVin }) {
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
          const name = vehicle.display_name || vehicle.vehicle_name || vehicle.name || `Vehicle ${index + 1}`;
          const state = vehicle.state || "unknown";
          return h("option", { key: `${id}-${index}`, value: id }, `${name} — ${state}`);
        })
      ),
      h(Input, {
        placeholder: "VIN or id_s override",
        value: vin || "",
        onChange: (event) => setVin(event.target.value),
      })
    );
  }

  function ActionGroup({ title, actions, runAction, loading, confirm }) {
    return h("div", { className: "tescmd-group" },
      h("h3", null, title),
      h("div", { className: "tescmd-actions" },
        actions.map(([action, label]) => h(Button, { key: action, onClick: () => runAction(action), disabled: loading || !confirm }, label))
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

  function VehicleSnapshot({ overview }) {
    const charge = chargeSummary(overview);
    const climate = climateSummary(overview);
    const security = securitySummary(overview);
    const location = locationSummary(overview);
    const chargeStyle = { "--tescmd-charge": `${Math.max(0, Math.min(100, charge.level ?? 0))}%` };
    return h("div", { className: "tescmd-visual-grid" },
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
        h("div", { className: "tescmd-mini-widget" }, h("span", null, "Location"), h("strong", null, location.lat == null || location.lon == null ? "No coordinates" : `${location.lat.toFixed(4)}, ${location.lon.toFixed(4)}`), h("small", null, location.speed == null ? "Speed unavailable" : `${location.speed} mph`))
      ),
      h(LeafletMap, { location })
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

  function LeafletMap({ location }) {
    const ref = hooks.useRef(null);
    const mapRef = hooks.useRef(null);
    const markerRef = hooks.useRef(null);
    const lat = location && location.lat;
    const lon = location && location.lon;

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
          }).setView([lat, lon], 14);
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
          mapRef.current.setView([lat, lon], mapRef.current.getZoom() || 14);
          markerRef.current.setLatLng([lat, lon]);
        }
        markerRef.current.bindPopup("Vehicle location");
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
    }, [lat, lon]);

    if (lat == null || lon == null) {
      return h("div", { className: "tescmd-map tescmd-map-empty" },
        h("div", null, "No vehicle coordinates yet"),
        h("small", null, "Run Location or Refresh overview after vehicle data is available.")
      );
    }
    return h("div", { className: "tescmd-map-shell" },
      h("div", { className: "tescmd-map-meta" }, h("strong", null, "Vehicle map"), h("span", null, `${lat.toFixed(5)}, ${lon.toFixed(5)}`)),
      h("div", { ref, className: "tescmd-map" })
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
    const [error, setError] = hooks.useState("");
    const [confirm, setConfirm] = hooks.useState(false);
    const [wakeReads, setWakeReads] = hooks.useState(false);
    const [noCache, setNoCache] = hooks.useState(false);
    const [units, setUnits] = hooks.useState("");
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

    const overviewQuery = () => {
      const params = new URLSearchParams();
      if (profile) params.set("profile", profile);
      if (region) params.set("region", region);
      if (vin) params.set("vin", vin);
      if (noCache) params.set("no_cache", "true");
      if (units) params.set("units", units);
      return params.toString();
    };

    const refresh = hooks.useCallback(async () => {
      setLoading(true);
      setError("");
      try {
        const overviewPayload = await api(`/overview?${overviewQuery()}`);
        const statusPayload = overviewPayload.status || null;
        const vehiclePayload = overviewPayload.vehicles || {};
        setOverview(overviewPayload);
        setStatus(statusPayload);
        setVehicles(Array.isArray(vehiclePayload.vehicles) ? vehiclePayload.vehicles : []);
        setDetail(overviewPayload);
      } catch (err) {
        setError(String((err && err.message) || err));
      } finally {
        setLoading(false);
      }
    }, [profile, region, vin, noCache, units]);

    hooks.useEffect(() => { refresh(); }, []);

    async function runRead(kind) {
      setLoading(true);
      setError("");
      try {
        const payload = await api(`/read/${kind}?${query(true)}`);
        setDetail(payload);
        if (["charge", "location", "drive", "climate", "closures", "security"].includes(kind)) {
          await refresh();
        }
      } catch (err) {
        setError(String((err && err.message) || err));
      } finally {
        setLoading(false);
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
      if (action === "nav") body.destination = destination;
      if (action === "nav-gps") {
        body.lat = numeric(lat);
        body.lon = numeric(lon);
      }
      if (action === "nav-waypoints") body.place_ids = placeIds.split(",").map((x) => x.trim()).filter(Boolean);
      return body;
    }

    async function runAction(action) {
      setLoading(true);
      setError("");
      try {
        const payload = await api("/quick-action", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(actionBody(action)),
        });
        setDetail(payload);
        await refresh();
      } catch (err) {
        setError(String((err && err.message) || err));
      } finally {
        setLoading(false);
      }
    }

    return h("div", { className: "tescmd-page" },
      h("section", { className: "tescmd-hero" },
        h("div", null,
          h("p", { className: "tescmd-kicker" }, "Hermes Tesla Command Center"),
          h("h1", null, "seaQuest at a glance"),
          h("p", { className: "tescmd-muted" }, "Visual vehicle state, live location, and confirm-gated Tesla quick actions from the native tescmd plugin.")
        ),
        h("div", { className: "tescmd-hero-actions" }, h(Button, { onClick: refresh, disabled: loading }, loading ? "Refreshing..." : "Refresh overview"))
      ),
      h(Card, { className: "tescmd-overview-card" },
        h(CardHeader, null, h(CardTitle, null, "Vehicle overview")),
        h(CardContent, null, overview ? h(VehicleSnapshot, { overview }) : h("p", { className: "tescmd-muted" }, "Refresh to load charge, climate, security, and map widgets."))
      ),
      h(Card, { className: "tescmd-controls-card" },
        h(CardHeader, null, h(CardTitle, null, "Options")),
        h(CardContent, null,
          h("div", { className: "tescmd-controls" },
            h(TextInput, { label: "Profile", value: profile, setValue: setProfile, placeholder: "default" }),
            h(Field, { label: "Region" }, h("select", { className: "tescmd-select", value: region, onChange: (event) => setRegion(event.target.value) },
              h("option", { value: "" }, "Configured"), h("option", { value: "na" }, "NA"), h("option", { value: "eu" }, "EU"), h("option", { value: "cn" }, "CN")
            )),
            h(VehiclePicker, { vehicles, vin, setVin }),
            h(Field, { label: "Read options" },
              h("label", { className: "tescmd-inline" }, h("input", { type: "checkbox", checked: wakeReads, onChange: (event) => setWakeReads(event.target.checked) }), " wake"),
              h("label", { className: "tescmd-inline" }, h("input", { type: "checkbox", checked: noCache, onChange: (event) => setNoCache(event.target.checked) }), " no cache")
            ),
            h(Field, { label: "Units" }, h("select", { className: "tescmd-select", value: units, onChange: (event) => setUnits(event.target.value) },
              h("option", { value: "" }, "Configured"), h("option", { value: "metric" }, "Metric"), h("option", { value: "imperial" }, "Imperial")
            ))
          ),
          status ? h(Readiness, { status }) : null
        )
      ),
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
          ACTION_GROUPS.map(([title, actions]) => h(ActionGroup, { key: title, title, actions, runAction, loading, confirm })),
          h("p", { className: "tescmd-muted" }, "Higher-risk flows like remote-start-drive, speed limit PINs, valet/PIN-to-drive, erase-user-data, and raw API calls remain tool-only with explicit confirm=true.")
        )
      ),
      error ? h(Card, { className: "tescmd-error-card" }, h(CardContent, null, h("p", { className: "tescmd-error" }, error))) : null,
      h(Card, null,
        h(CardHeader, null, h(CardTitle, null, "Last payload")),
        h(CardContent, null, detail ? h(JsonBlock, { data: detail }) : h("p", { className: "tescmd-muted" }, "No payload yet."))
      )
    );
  }

  function HeaderWidget() {
    return h("span", { className: "tescmd-header-pill", title: "Tesla dashboard plugin installed" }, "Tesla");
  }

  window.__HERMES_PLUGINS__.register("hermes-tescmd-plugin", TeslaDashboard);
  window.__HERMES_PLUGINS__.registerSlot("hermes-tescmd-plugin", "header-right", HeaderWidget);
})();
