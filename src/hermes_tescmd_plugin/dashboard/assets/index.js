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

  function JsonBlock({ data }) {
    return h("pre", { className: "tescmd-json" }, JSON.stringify(data, null, 2));
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
    return h("div", { className: "tescmd-field" },
      h(Label, null, "Vehicle"),
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

    const query = () => {
      const params = new URLSearchParams();
      if (profile) params.set("profile", profile);
      if (region) params.set("region", region);
      if (vin) params.set("vin", vin);
      return params.toString();
    };

    const refresh = hooks.useCallback(async () => {
      setLoading(true);
      setError("");
      try {
        const statusPayload = await api(`/status?profile=${encodeURIComponent(profile || "default")}`);
        const vehiclePayload = await api(`/vehicles?${query()}`);
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
        const payload = await api(`/read/${kind}?${query()}`);
        setDetail(payload);
      } catch (err) {
        setError(String((err && err.message) || err));
      } finally {
        setLoading(false);
      }
    }

    async function runAction(action) {
      setLoading(true);
      setError("");
      try {
        const payload = await api("/quick-action", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action, vin: vin || null, profile: profile || "default", region: region || null, confirm }),
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
        h(CardHeader, null,
          h(CardTitle, null, "Tesla Fleet")
        ),
        h(CardContent, null,
          h("p", { className: "tescmd-muted" }, "Native hermes-tescmd-plugin reads plus confirm-gated physical quick actions."),
          h("div", { className: "tescmd-controls" },
            h("div", { className: "tescmd-field" },
              h(Label, null, "Profile"),
              h(Input, { value: profile, onChange: (event) => setProfile(event.target.value), placeholder: "default" })
            ),
            h("div", { className: "tescmd-field" },
              h(Label, null, "Region"),
              h("select", { className: "tescmd-select", value: region, onChange: (event) => setRegion(event.target.value) },
                h("option", { value: "" }, "Configured"),
                h("option", { value: "na" }, "NA"),
                h("option", { value: "eu" }, "EU"),
                h("option", { value: "cn" }, "CN")
              )
            ),
            h(VehiclePicker, { vehicles, vin, setVin })
          ),
          status ? h(Readiness, { status }) : null,
          h("div", { className: "tescmd-actions" },
            h(Button, { onClick: refresh, disabled: loading }, loading ? "Refreshing..." : "Refresh"),
            h(Button, { onClick: () => runRead("vehicle-status"), disabled: loading }, "Vehicle"),
            h(Button, { onClick: () => runRead("charge"), disabled: loading }, "Charge"),
            h(Button, { onClick: () => runRead("climate"), disabled: loading }, "Climate"),
            h(Button, { onClick: () => runRead("location"), disabled: loading }, "Location")
          )
        )
      ),
      h(Card, null,
        h(CardHeader, null, h(CardTitle, null, "Guarded quick actions")),
        h(CardContent, null,
          h("label", { className: "tescmd-confirm" },
            h("input", { type: "checkbox", checked: confirm, onChange: (event) => setConfirm(event.target.checked) }),
            h("span", null, "I confirm this physical Tesla side effect")
          ),
          h("div", { className: "tescmd-actions" },
            ["wake", "flash", "honk", "lock", "climate-start", "climate-stop", "charge-port-open", "charge-port-close"].map((action) =>
              h(Button, { key: action, onClick: () => runAction(action), disabled: loading || !confirm }, action)
            )
          ),
          h("p", { className: "tescmd-muted" }, "Unlock, remote start, and other higher-risk actions are intentionally not exposed as dashboard quick buttons; use dedicated tools with explicit confirm=true when needed.")
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
