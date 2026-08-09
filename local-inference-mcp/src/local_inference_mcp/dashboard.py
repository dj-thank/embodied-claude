"""Self-contained MCP App for inspecting and trying local inference."""

DASHBOARD_URI = "ui://sanpoloid/local-inference.html"

DASHBOARD_HTML = r"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Sanpoloid Local Mind</title>
  <style>
    :root {
      color-scheme: light dark;
      --bg: var(--color-background-primary, #0b0c10);
      --panel: var(--color-background-secondary, #14161c);
      --panel-2: var(--color-background-tertiary, #1b1e26);
      --text: var(--color-text-primary, #f5f2eb);
      --muted: var(--color-text-secondary, #a5a5ad);
      --line: var(--color-border-secondary, #343640);
      --accent: #ffcb47;
      --accent-2: #ff8066;
      --good: #72dc91;
      --bad: #ff8066;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      padding: 14px;
      background:
        radial-gradient(circle at 92% 2%, #55352066 0, transparent 38%),
        radial-gradient(circle at 0 100%, #203e5566 0, transparent 42%),
        var(--bg);
      color: var(--text);
      font: 14px/1.55 var(--font-sans, "Yu Gothic UI", "Segoe UI", sans-serif);
    }
    button, select, textarea { font: inherit; }
    .shell {
      max-width: 760px;
      margin: 0 auto;
      overflow: hidden;
      border: 1px solid var(--line);
      border-radius: 20px;
      background: color-mix(in srgb, var(--panel) 96%, transparent);
      box-shadow: 0 24px 60px #0006;
    }
    header {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 16px;
      padding: 18px 20px;
      border-bottom: 1px solid var(--line);
    }
    .eyebrow {
      color: var(--accent);
      font: 750 11px/1 var(--font-mono, monospace);
      letter-spacing: .17em;
    }
    h1 { margin: 7px 0 3px; font-size: 21px; line-height: 1.15; }
    .subtitle { margin: 0; color: var(--muted); font-size: 12px; }
    .status {
      display: inline-flex;
      align-items: center;
      gap: 7px;
      flex: none;
      padding: 7px 10px;
      border: 1px solid var(--line);
      border-radius: 999px;
      color: var(--muted);
      background: var(--panel-2);
      font-size: 11px;
    }
    .dot { width: 7px; height: 7px; border-radius: 50%; background: var(--muted); }
    .status.online .dot { background: var(--good); box-shadow: 0 0 10px var(--good); }
    .status.offline .dot { background: var(--bad); }
    main { display: grid; grid-template-columns: 220px minmax(0, 1fr); }
    aside { padding: 18px; border-right: 1px solid var(--line); }
    .label {
      margin: 0 0 8px;
      color: var(--muted);
      font: 700 10px/1 var(--font-mono, monospace);
      letter-spacing: .12em;
      text-transform: uppercase;
    }
    .endpoint { overflow-wrap: anywhere; font: 12px/1.45 var(--font-mono, monospace); }
    .models { display: grid; gap: 7px; margin-top: 18px; }
    .model {
      overflow: hidden;
      padding: 8px 10px;
      border: 1px solid var(--line);
      border-radius: 9px;
      background: var(--panel-2);
      text-overflow: ellipsis;
      white-space: nowrap;
      font: 12px/1.3 var(--font-mono, monospace);
    }
    .model.selected { border-color: color-mix(in srgb, var(--accent) 58%, var(--line)); }
    .refresh {
      width: 100%;
      margin-top: 16px;
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 9px 11px;
      background: transparent;
      color: var(--text);
      cursor: pointer;
    }
    .workspace { min-width: 0; padding: 18px; }
    textarea {
      width: 100%;
      min-height: 116px;
      resize: vertical;
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 12px 13px;
      outline: none;
      background: var(--panel-2);
      color: var(--text);
    }
    textarea:focus, select:focus { border-color: var(--accent); }
    .controls { display: flex; align-items: center; gap: 9px; margin-top: 10px; }
    select {
      min-width: 112px;
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 8px 10px;
      background: var(--panel-2);
      color: var(--text);
    }
    .run {
      margin-left: auto;
      border: 0;
      border-radius: 10px;
      padding: 9px 16px;
      background: linear-gradient(135deg, var(--accent), var(--accent-2));
      color: #24170c;
      font-weight: 800;
      cursor: pointer;
    }
    button:disabled { cursor: wait; opacity: .55; }
    .answer {
      min-height: 88px;
      margin-top: 16px;
      padding: 13px;
      border: 1px solid var(--line);
      border-radius: 12px;
      background: color-mix(in srgb, var(--panel-2) 80%, transparent);
      white-space: pre-wrap;
      overflow-wrap: anywhere;
    }
    .answer.empty { color: var(--muted); }
    .usage { min-height: 16px; margin-top: 8px; color: var(--muted); font-size: 11px; }
    footer {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      padding: 10px 18px;
      border-top: 1px solid var(--line);
      color: var(--muted);
      font-size: 10px;
    }
    @media (max-width: 620px) {
      body { padding: 7px; }
      main { grid-template-columns: 1fr; }
      aside { border-right: 0; border-bottom: 1px solid var(--line); }
      .models { grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); }
    }
    @media (prefers-reduced-motion: no-preference) {
      .dot { transition: background .2s, box-shadow .2s; }
      .answer { transition: border-color .2s; }
    }
  </style>
</head>
<body>
  <section class="shell" aria-label="Sanpoloid local inference">
    <header>
      <div>
        <div class="eyebrow">SANPOLOID · LOCAL MIND</div>
        <h1>ローカル思考室</h1>
        <p class="subtitle">同じPCのモデルだけで、状態確認と短い試行を行います。</p>
      </div>
      <div class="status" id="status">
        <span class="dot"></span><span id="statusText">確認待ち</span>
      </div>
    </header>
    <main>
      <aside>
        <p class="label">Loopback endpoint</p>
        <div class="endpoint" id="endpoint">未取得</div>
        <div class="models" id="models"><div class="model">モデル未取得</div></div>
        <button class="refresh" id="refresh" type="button">状態を更新</button>
      </aside>
      <section class="workspace">
        <label class="label" for="prompt">Prompt</label>
        <textarea id="prompt" maxlength="16000"
          placeholder="例：今日の散歩を楽しみにしていることを、一文で話して"></textarea>
        <div class="controls">
          <label class="label" for="preset">Mode</label>
          <select id="preset">
            <option value="default">Default</option>
            <option value="strict">Strict</option>
            <option value="concise">Concise</option>
          </select>
          <button class="run" id="run" type="button">考えてもらう</button>
        </div>
        <div class="answer empty" id="answer" aria-live="polite">応答はここに表示されます。</div>
        <div class="usage" id="usage"></div>
      </section>
    </main>
    <footer><span>Local only · no model control</span><span id="stamp">MCP Apps</span></footer>
  </section>
  <script>
    (() => {
      let requestId = 1;
      let lastTool = "";
      const pending = new Map();
      const byId = id => document.getElementById(id);
      const send = message => window.parent.postMessage(message, "*");
      const notify = (method, params = {}) => send({ jsonrpc: "2.0", method, params });
      const request = (method, params = {}) => new Promise((resolve, reject) => {
        const id = requestId++;
        const timer = setTimeout(() => {
          pending.delete(id);
          reject(new Error("Host request timed out"));
        }, 30000);
        pending.set(id, { resolve, reject, timer });
        send({ jsonrpc: "2.0", id, method, params });
      });
      const callTool = async (name, args) => {
        lastTool = name;
        return request("tools/call", { name, arguments: args });
      };
      const setBusy = busy => {
        byId("refresh").disabled = busy;
        byId("run").disabled = busy;
      };
      const renderStatus = data => {
        if (!data || typeof data.available !== "boolean") return false;
        const status = byId("status");
        status.className = `status ${data.available ? "online" : "offline"}`;
        byId("statusText").textContent = data.available ? "接続中" : "未接続";
        byId("endpoint").textContent = data.endpoint || "未設定";
        const models = byId("models");
        models.replaceChildren();
        const items = Array.isArray(data.models) ? data.models : [];
        if (!items.length) {
          const empty = document.createElement("div");
          empty.className = "model";
          empty.textContent = data.error || "利用可能なモデルなし";
          models.append(empty);
        }
        for (const item of items) {
          const row = document.createElement("div");
          row.className = `model${item === data.configured_model ? " selected" : ""}`;
          row.textContent = item;
          row.title = item;
          models.append(row);
        }
        return true;
      };
      const renderCompletion = data => {
        if (!data || typeof data.text !== "string") return false;
        const answer = byId("answer");
        answer.className = "answer";
        answer.textContent = data.text;
        const usage = data.usage || {};
        const tokens = Number.isInteger(usage.total_tokens)
          ? `${usage.total_tokens} tokens`
          : "token数不明";
        byId("usage").textContent = `${data.model || "local model"} · ${tokens}`;
        return true;
      };
      const render = data => {
        if (lastTool === "get_local_inference_status" && renderStatus(data)) return;
        if (lastTool === "ask_local_model" && renderCompletion(data)) return;
        if (!renderStatus(data)) renderCompletion(data);
      };
      const showError = error => {
        const answer = byId("answer");
        answer.className = "answer empty";
        answer.textContent = error.message || "処理に失敗しました。";
      };
      const applyHostContext = context => {
        if (!context) return;
        if (context.theme) document.documentElement.style.colorScheme = context.theme;
        for (const [name, value] of Object.entries(context.styles?.variables || {})) {
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
          if (message.error) {
            handler.reject(new Error(message.error.message || "Host request failed"));
          }
          else handler.resolve(message.result);
          return;
        }
        if (message.method === "ui/notifications/tool-input") {
          lastTool = message.params?.name || lastTool;
        }
        if (message.method === "ui/notifications/tool-result") {
          render(message.params?.structuredContent);
        }
        if (message.method === "ui/notifications/host-context-changed") {
          applyHostContext(message.params);
        }
        if (message.method === "ui/resource-teardown" && message.id != null) {
          send({ jsonrpc: "2.0", id: message.id, result: {} });
        }
      });
      byId("refresh").addEventListener("click", async () => {
        setBusy(true);
        try {
          const result = await callTool("get_local_inference_status", {});
          renderStatus(result.structuredContent);
          byId("stamp").textContent = new Date().toLocaleTimeString(
            [], { hour: "2-digit", minute: "2-digit" }
          );
        } catch (error) { showError(error); }
        finally { setBusy(false); }
      });
      byId("run").addEventListener("click", async () => {
        const prompt = byId("prompt").value.trim();
        if (!prompt) { showError(new Error("Promptを入力してください。")); return; }
        setBusy(true);
        byId("answer").textContent = "考えています…";
        try {
          const result = await callTool("ask_local_model", {
            prompt,
            preset: byId("preset").value,
            max_tokens: 512
          });
          renderCompletion(result.structuredContent);
        } catch (error) { showError(error); }
        finally { setBusy(false); }
      });
      new ResizeObserver(() => notify("ui/notifications/size-changed", {
        width: Math.ceil(document.documentElement.scrollWidth),
        height: Math.ceil(document.documentElement.scrollHeight)
      })).observe(document.body);
      request("ui/initialize", {
        protocolVersion: "2026-01-26",
        appInfo: { name: "Sanpoloid Local Mind", version: "1.0.0" },
        appCapabilities: { availableDisplayModes: ["inline"] }
      }).then(result => {
        applyHostContext(result.hostContext);
        notify("ui/notifications/initialized");
      }).catch(() => {
        byId("statusText").textContent = "Text fallback";
      });
    })();
  </script>
</body>
</html>
"""
