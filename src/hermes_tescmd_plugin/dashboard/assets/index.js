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

  function TeslaDashboard() {
    const [profile, setProfile] = hooks.useState("default");
    const [region, setRegion] = hooks.useState("");
    const [vin, setVin] = hooks.useState("");
    const [status, setStatus] = hooks.useState(null);
    const [vehicles, setVehicles] = hooks.useState([]);
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

    const refresh = hooks.useCallback(async () => {
      setLoading(true);
      setError("");
      try {
        const statusPayload = await api(`/status?profile=${encodeURIComponent(profile || "default")}`);
        const vehiclePayload = await api(`/vehicles?${query(false)}`);
        setStatus(statusPayload);
        setVehicles(Array.isArray(vehiclePayload.vehicles) ? vehiclePayload.vehicles : []);
        setDetail({ status: statusPayload, vehicles: vehiclePayload });
      } catch (err) {
        setError(String((err && err.message) || err));
      } finally {
        setLoading(false);
      }
    }, [profile, region, vin]);

    hooks.useEffect(() => { refresh(); }, []);

    async function runRead(kind) {
      setLoading(true);
      setError("");
      try {
        const payload = await api(`/read/${kind}?${query(true)}`);
        setDetail(payload);
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
      } catch (err) {
        setError(String((err && err.message) || err));
      } finally {
        setLoading(false);
      }
    }

    return h("div", { className: "tescmd-page" },
      h(Card, null,
        h(CardHeader, null, h(CardTitle, null, "Tesla Fleet")),
        h(CardContent, null,
          h("p", { className: "tescmd-muted" }, "Native tescmd reads plus confirm-gated physical quick actions."),
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
          status ? h(Readiness, { status }) : null,
          h("div", { className: "tescmd-actions tescmd-primary-actions" }, h(Button, { onClick: refresh, disabled: loading }, loading ? "Refreshing..." : "Refresh status & vehicles"))
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
