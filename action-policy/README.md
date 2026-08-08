# Embodied Action Policy

Claude Code の `PreToolUse` seam で、embodied MCP tool を中央分類して実行前に
判定する host-side module です。各 MCP server の実装に依存せず、project の
`.claude/settings.json` から全 `mcp__.*` call に適用されます。

## 判定

| action class | interactive | autonomous |
| --- | --- | --- |
| read-only / local bookkeeping / local ephemeral | allow | allow |
| sensor observation / physical motion / speech / persistent write | ask | deny by default |
| destructive | ask | always deny |
| unknown MCP tool | ask | deny |

`read-only` は user content、physical state、external channel を変更しない分類です。
memory search / recall のうち access count や activation metadata を更新するものは、隠れた
local write を明示するため `local_bookkeeping` に分離しています。

Interactive の `ask` は Claude Code の確認 UI に exact tool call を渡します。
decision reason は canonical JSON input の SHA-256 prefix を含み、payload 本文や
credential は含めません。

Autonomous mode では、operator が exact tool name を明示したものだけを許可できます。

```bash
export EMBODIED_ACTION_MODE=autonomous
export EMBODIED_AUTONOMOUS_ALLOW="mcp__wifi-cam__see,mcp__memory__remember"
```

`mcp__memory__forget` など destructive class は allowlist に書いても拒否されます。
未設定・未知 mode・未知 tool・不正 JSON input は fail closed です。

`autonomous-action.sh` は `autonomous-mcp.json` を `--mcp-config` と
`--strict-mcp-config` で固定し、project settings だけを選択してこの hook を読み込みます。
外向き tool を `--allowedTools` では事前許可しないため、gate 障害時にスクリプト自身の
allowlist だけで外向き call が通る経路は持ちません。

## 検証

```bash
cd action-policy
uv sync
uv run --extra dev pytest -q
uv run --extra dev ruff check .
```

## 境界

- これは host confirmation / exact-tool allowlist です。quiet hours、presence、privacy
  zone、rate limit、同時実行 lock、consent ledger はまだ実装していません。
- Wrapper は project path、`uv`、gate process、decision shape の失敗を blocking exit 2 に
  変換します。hook を無効化した host、project settings を読まない起動、wrapper 自体の
  起動失敗、host timeout まで安全を証明するものではありません。
- `.claude/settings.json` は project scope です。installer が `~/.claude.json` に登録した
  MCP server を repository 外の session から使う経路には、この hook は適用されません。
- Autonomous allowlist は tool name を承認しますが、input constraint までは定義しません。
- 将来の phone-side runtime は同じ分類と verdict interface を native host adapter から
  呼び出す必要があります。
