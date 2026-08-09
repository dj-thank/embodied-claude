# local-inference-mcp

Sanpoloidから、同じPC上のLM Studioまたはllama.cppへテキスト推論を委譲する
loopback-only MCP serverです。OpenAI-compatibleな`/v1/models`と
`/v1/chat/completions`だけを使い、外部provider SDKを追加しません。

## 安全上の境界

- endpointは`localhost`またはloopback IPだけを受理する
- OSのHTTP proxyを使わず、redirectを追わない
- server起動、model download/load/unloadを行わない
- promptとsystem promptの合計は既定16,000文字、出力は最大4,096 token
- 応答本文は2 MiBで打ち切る
- このhelperを呼ばれたlocal model自身はSanpoloidのMCP toolを呼べない

promptはこのpackageからloopback外へ送信されません。ただし、推論runtime自身の
logging、保存、model behaviorはLM Studioまたはllama.cpp側の設定に従います。

## セットアップ

LM Studio:

```powershell
lms server start --bind 127.0.0.1 --port 1234
lms load <model-key> --identifier sanpoloid-local --context-length 4096
$env:SANPOLOID_LOCAL_LLM_MODEL = "sanpoloid-local"
uv run local-inference-mcp
```

llama.cpp:

```powershell
llama-server -m C:\path\to\model.gguf --host 127.0.0.1 --port 8080
$env:SANPOLOID_LOCAL_LLM_BASE_URL = "http://127.0.0.1:8080/v1"
$env:SANPOLOID_LOCAL_LLM_MODEL = "your-model-id"
uv run local-inference-mcp
```

## 環境変数

| Name | Default | Purpose |
|---|---|---|
| `SANPOLOID_LOCAL_LLM_BASE_URL` | `http://127.0.0.1:1234/v1` | loopback endpoint |
| `SANPOLOID_LOCAL_LLM_MODEL` | unset | model ID。未指定時は公開modelが1件の場合だけ自動選択 |
| `SANPOLOID_LOCAL_LLM_API_TOKEN` | unset | local serverでtoken認証を有効にした場合だけ指定 |
| `SANPOLOID_LOCAL_LLM_TIMEOUT_SECONDS` | `30` | request timeout |
| `SANPOLOID_LOCAL_LLM_MAX_PROMPT_CHARS` | `16000` | system+user prompt上限 |

## Tools

- `get_local_inference_status`: endpointとmodel一覧を確認する。serverやmodelは起動しない
- `ask_local_model`: boundedな非streaming text completionを実行する

`ask_local_model`の`preset`は`default`、`strict`、`concise`、`json`から選択する。
プリセットはモデル自体を変更せず、用途別のsystem instructionを加える。`json`はLM Studioと
llama.cppのJSON Schema制約を要求し、任意の`json_schema`（最大16 KiB）も渡せる。schemaを
使わない場合でもJSON objectを要求する。実runtimeの対応状況はバージョンごとに確認すること。

## 日本語コア評価

モデルやprompt変更前後を同じ条件で比べるため、5件の小型fixtureを同梱する。採点はexact、
必須語、禁止語、文字数、JSON構造の決定的な検査だけで行い、別LLMをjudgeに使わない。

```powershell
$env:SANPOLOID_LOCAL_LLM_MODEL = "sanpoloid-local"
uv run local-inference-eval --preset default --preset strict --temperature 0.1
uv run local-inference-eval --preset json --case json_only --temperature 0.1 `
  --output ..\outputs\local-inference-eval.json
```

`--preset`と`--case`は繰り返し指定できる。スコアはfixtureへの適合率であり、一般的な日本語能力、
安全性、長文品質、実運用品質を表すものではない。用途別プリセットは対応するケースだけで評価する。
