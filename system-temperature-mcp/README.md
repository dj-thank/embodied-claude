# Sanpoloid Body Signal MCP

PCの温度センサーと日本時間をread-onlyで返すMCP serverです。温度toolには、text fallbackと
network-freeなMCP App dashboardがあります。

## 開発実行

```powershell
uv run system-temperature-mcp
uv run --extra dev pytest -q
```

## MCPB pilot

`manifest.json`はMCPB manifest v0.4のUV runtimeを使用します。bundleはPython環境やdependencyを
同梱せず、host側のUVが`pyproject.toml`と`uv.lock`から隔離環境を作ります。

```powershell
npx --yes @anthropic-ai/mcpb@2.1.2 validate .
npx --yes @anthropic-ai/mcpb@2.1.2 pack . `
  ..\outputs\sanpoloid-body-signal-0.1.0.mcpb
```

`mcpb_entrypoint.py`はbundle rootからpackage entry pointを安定して呼ぶための薄いadapterです。
`.mcpbignore`はtests、venv、cache、build outputを除外し、再現性のため`uv.lock`は残します。

現在の`.mcpb`はunsigned pilotです。MCPB CLIのvalidate/packと、展開後のUV環境から
modern/legacy MCP client、2 tools、MCP App resourceを検証済みです。Claude Desktopのinstall UI、
署名trust、別PC、通常ユーザー権限、offline初回installは未検証です。

## Icon

`assets/body-signal-icon.svg`が決定的な編集原本、`assets/body-signal-512.png`がmanifestから参照される
配布assetです。dashboardと同じnavy、cyan、blue、greenを使い、操作ボタンや警告に見えない
read-only body signalを表現しています。
