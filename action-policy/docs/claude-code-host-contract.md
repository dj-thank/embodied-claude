# Claude Code host contract 調査

確認日: 2026-08-09

Sanpoloid の中央 action gate を Claude Code host に接続するため、Anthropic の一次資料で
現在の契約を確認した。

## 確認できた契約

- `PreToolUse` は Claude が tool input を組み立てた後、tool call の実行前に発火し、MCP
  tool name にも matcher を適用できる。
- command hook は stdin で JSON を受け取り、exit 0 の stdout JSON を structured decision
  として返せる。
- `PreToolUse` の `hookSpecificOutput.permissionDecision` は `allow`、`ask`、`deny`、
  `defer` を取る。`ask` は user confirmation、`deny` は call の阻止、`allow` は通常の
  permission prompt の省略を表す。
- 複数 hook の decision precedence は `deny > defer > ask > allow`。
- command hook の exit 2 は `PreToolUse` call を block する。一方、exit 1、command の
  起動失敗、timeout など通常の hook error は原則 non-blocking であり、normal permission
  flow へ進む。このため hook 単体を hard security boundary と主張できない。
- `--mcp-config` は指定 JSON から MCP server を読み、`--strict-mcp-config` はそれ以外の
  MCP configuration を無視する。
- `--setting-sources project` は読み込む settings source を project に限定できる。
- scripted invocation では `--bare` が推奨されているが、`--bare` は project hook を含む
  auto-discovery を無効にする。現在の gate 構成とは両立しないため採用しない。
- `--mcp-config` の不正 entry は skip されても run が clean exit し得る。live acceptance
  では stream JSON の `system/init.mcp_servers` と `mcp_server_errors` を検査する必要がある。

## 今回の設計への反映

- `.claude/settings.json` は `mcp__.*` を一つの `PreToolUse` adapter へ集約する。
- Bash / PowerShell wrapper は policy path、`uv`、gate process、decision shape の failure
  を exit 2 に変換し、Claude Code に tool call を block させる。PowerShell adapter は
  redirected stdin、native process pipe、stdout を UTF-8 に固定する。
- interactive outward action は `ask`、autonomous outward action は exact tool allowlist が
  なければ `deny` とする。
- `autonomous-action.sh` は readable な explicit MCP config を必須とし、
  `--strict-mcp-config` を付ける。
- autonomous invocation は outward MCP tool を `--allowedTools` で事前許可しない。hook
  process が失敗したとき、script 固有の preapproval だけで action が続く経路を作らない。
- current host に Claude CLI がないため、`system/init` による server 接続確認、host
  timeout、wrapper 自体の起動不能を含む real Claude hook E2E は未検証のまま分離する。
- Installer は `action-policy` を先に同期し、既存 user hooks を保持しながら Sanpoloid の
  5 server prefix だけを対象にする handler を `~/.claude/settings.json` へ追加した後で、
  global MCP config を公開する。再実行は installer 所有 handler だけを置換する。
- Local user settings を読まない cloud session、手動 global MCP config、disabled hook、
  host timeout、wrapper 自体の起動不能は引き続き別の acceptance boundary である。

## 一次資料

- [Claude Code hooks reference](https://code.claude.com/docs/en/hooks)
- [Claude Code CLI reference](https://code.claude.com/docs/en/cli-usage)
- [Run Claude Code programmatically](https://code.claude.com/docs/en/headless)
