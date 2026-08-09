"""Self-contained MCP Apps view for Sanpoloid body temperature."""

DASHBOARD_URI = "ui://sanpoloid/body-temperature.html"

DASHBOARD_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Sanpoloid Body Signal</title>
  <style>
    :root {
      color-scheme: light dark;
      --bg: var(--color-background-primary, #07111f);
      --panel: var(--color-background-secondary, #0d1b2d);
      --text: var(--color-text-primary, #edf7ff);
      --muted: var(--color-text-secondary, #91a8ba);
      --line: var(--color-border-secondary, #28445b);
      --cyan: #20d3ee;
      --blue: #3478f6;
      --good: #4ade80;
      --warm: #fbbf24;
      --hot: #fb7185;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      padding: 16px;
      background: radial-gradient(circle at 82% 0%, #10314a 0, transparent 46%), var(--bg);
      color: var(--text);
      font: 14px/1.5 var(--font-sans, "Yu Gothic UI", "Segoe UI", sans-serif);
    }
    .shell {
      max-width: 720px;
      margin: 0 auto;
      border: 1px solid var(--line);
      border-radius: 18px;
      overflow: hidden;
      background: color-mix(in srgb, var(--panel) 94%, transparent);
      box-shadow: 0 18px 50px #0005;
    }
    header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 16px 18px;
      border-bottom: 1px solid var(--line);
    }
    .eyebrow { color: var(--cyan); font: 700 11px/1 var(--font-mono, monospace); letter-spacing: .18em; }
    h1 { margin: 5px 0 0; font-size: 19px; line-height: 1.2; }
    button {
      border: 1px solid #2b6d89;
      border-radius: 999px;
      padding: 8px 13px;
      background: #0d7089;
      color: white;
      font: 700 12px/1 var(--font-sans, sans-serif);
      cursor: pointer;
    }
    button:disabled { cursor: wait; opacity: .55; }
    main { display: grid; grid-template-columns: 190px 1fr; gap: 18px; padding: 18px; }
    .gauge {
      display: grid;
      place-items: center;
      min-height: 180px;
      border: 1px solid var(--line);
      border-radius: 15px;
      background: linear-gradient(155deg, #10263b, #091522);
    }
    .dial {
      --value: 0deg;
      width: 136px;
      aspect-ratio: 1;
      display: grid;
      place-items: center;
      border-radius: 50%;
      background: conic-gradient(from 225deg, var(--cyan) var(--value), #20384a 0 270deg, transparent 0);
      transform: rotate(0deg);
      position: relative;
    }
    .dial::after { content: ""; position: absolute; inset: 12px; border-radius: 50%; background: #091522; }
    .reading { position: relative; z-index: 1; text-align: center; }
    .value { font: 750 31px/1 var(--font-mono, monospace); }
    .unit { margin-top: 5px; color: var(--muted); font-size: 11px; letter-spacing: .1em; }
    .summary { min-width: 0; }
    .feeling { margin: 0 0 13px; font-size: 16px; font-weight: 650; }
    .sensors { display: grid; gap: 8px; }
    .sensor {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 12px;
      padding: 10px 12px;
      border: 1px solid var(--line);
      border-radius: 11px;
      background: #0a1827;
    }
    .sensor-name { overflow: hidden; color: var(--muted); text-overflow: ellipsis; white-space: nowrap; }
    .sensor-temp { font: 700 13px/1.5 var(--font-mono, monospace); }
    .empty { padding: 15px; border: 1px dashed var(--line); border-radius: 11px; color: var(--muted); }
    footer { display: flex; justify-content: space-between; gap: 12px; padding: 11px 18px; border-top: 1px solid var(--line); color: var(--muted); font-size: 11px; }
    .live::before { content: ""; display: inline-block; width: 7px; height: 7px; margin-right: 7px; border-radius: 50%; background: var(--good); box-shadow: 0 0 10px var(--good); }
    @media (max-width: 520px) {
      body { padding: 8px; }
      main { grid-template-columns: 1fr; }
      .gauge { min-height: 165px; }
    }
  </style>
</head>
<body>
  <section class="shell" aria-label="Sanpoloid body temperature">
    <header>
      <div><div class="eyebrow">SANPOLOID · BODY SIGNAL</div><h1>System temperature</h1></div>
      <button id="refresh" type="button">Refresh</button>
    </header>
    <main>
      <section class="gauge" aria-label="Highest temperature">
        <div class="dial" id="dial"><div class="reading"><div class="value" id="value">--</div><div class="unit">CELSIUS · MAX</div></div></div>
      </section>
      <section class="summary">
        <p class="feeling" id="feeling">Waiting for body signal…</p>
        <div class="sensors" id="sensors"><div class="empty">No reading received yet.</div></div>
      </section>
    </main>
    <footer><span class="live" id="state">Local · read only</span><span id="stamp">MCP Apps</span></footer>
  </section>
  <script>
    (() => {
      let requestId = 1;
      const pending = new Map();
      const send = message => window.parent.postMessage(message, "*");
      const notify = (method, params = {}) => send({ jsonrpc: "2.0", method, params });
      const request = (method, params = {}) => new Promise((resolve, reject) => {
        const id = requestId++;
        const timer = setTimeout(() => {
          pending.delete(id);
          reject(new Error("Host request timed out"));
        }, 10000);
        pending.set(id, { resolve, reject, timer });
        send({ jsonrpc: "2.0", id, method, params });
      });
      const setBusy = busy => {
        const button = document.getElementById("refresh");
        button.disabled = busy;
        button.textContent = busy ? "Reading…" : "Refresh";
      };
      const render = data => {
        if (!data || !Array.isArray(data.temperatures)) return;
        const values = data.temperatures.map(item => Number(item.temperature_celsius)).filter(Number.isFinite);
        const hottest = values.length ? Math.max(...values) : null;
        document.getElementById("value").textContent = hottest === null ? "--" : hottest.toFixed(1) + "°";
        const ratio = hottest === null ? 0 : Math.max(0, Math.min(1, (hottest - 20) / 80));
        document.getElementById("dial").style.setProperty("--value", `${ratio * 270}deg`);
        document.getElementById("feeling").textContent = data.feeling || "Body signal received.";
        const sensors = document.getElementById("sensors");
        sensors.replaceChildren();
        if (!data.temperatures.length) {
          const empty = document.createElement("div");
          empty.className = "empty";
          empty.textContent = "No accessible temperature sensor on this host.";
          sensors.append(empty);
        }
        for (const item of data.temperatures) {
          const row = document.createElement("div");
          row.className = "sensor";
          const name = document.createElement("span");
          name.className = "sensor-name";
          name.textContent = item.name || item.source || "sensor";
          const temperature = document.createElement("span");
          temperature.className = "sensor-temp";
          temperature.textContent = Number(item.temperature_celsius).toFixed(1) + " °C";
          row.append(name, temperature);
          sensors.append(row);
        }
        document.getElementById("stamp").textContent = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
        setBusy(false);
      };
      const applyHostContext = context => {
        if (!context) return;
        if (context.theme) document.documentElement.style.colorScheme = context.theme;
        const variables = context.styles?.variables || {};
        for (const [name, value] of Object.entries(variables)) {
          if (name.startsWith("--") && typeof value === "string") {
            document.documentElement.style.setProperty(name, value);
          }
        }
      };
      window.addEventListener("message", event => {
        if (event.source !== window.parent) return;
        const message = event.data;
        if (!message || message.jsonrpc !== "2.0") return;
        if (message.id != null && pending.has(message.id)) {
          const handler = pending.get(message.id);
          pending.delete(message.id);
          clearTimeout(handler.timer);
          if (message.error) handler.reject(new Error(message.error.message || "Host request failed"));
          else handler.resolve(message.result);
          return;
        }
        if (message.method === "ui/notifications/tool-result") render(message.params?.structuredContent);
        if (message.method === "ui/notifications/host-context-changed") applyHostContext(message.params);
        if (message.method === "ui/resource-teardown" && message.id != null) send({ jsonrpc: "2.0", id: message.id, result: {} });
      });
      document.getElementById("refresh").addEventListener("click", async () => {
        setBusy(true);
        try {
          const result = await request("tools/call", { name: "get_system_temperature", arguments: {} });
          render(result.structuredContent);
        } catch (error) {
          document.getElementById("state").textContent = error.message;
          setBusy(false);
        }
      });
      new ResizeObserver(() => notify("ui/notifications/size-changed", {
        width: Math.ceil(document.documentElement.scrollWidth),
        height: Math.ceil(document.documentElement.scrollHeight)
      })).observe(document.body);
      request("ui/initialize", {
        protocolVersion: "2026-01-26",
        appInfo: { name: "Sanpoloid Body Signal", version: "1.0.0" },
        appCapabilities: { availableDisplayModes: ["inline"] }
      }).then(result => {
        applyHostContext(result.hostContext);
        notify("ui/notifications/initialized");
      }).catch(() => {
        document.getElementById("state").textContent = "Text fallback available";
      });
    })();
  </script>
</body>
</html>
"""
