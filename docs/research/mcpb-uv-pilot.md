# sanpo-loid MCPB UV配布pilot

調査・実測日: 2026-08-09

## 結論

MCPB UV runtimeは、SanpoloidのPython MCPをone-click配布へ寄せる有力な選択肢である。
`system-temperature-mcp` pilotでは、既存のSDK v2 typed toolsとMCP Appを変更せず、146,168 bytesの
`.mcpb`へpackできた。展開先でUVが環境を作成した後、modern/legacy両clientから2 tools、Body Signal
resource、tool callを確認した。

ただしMCPBは「配布archiveが小さい」のであって、「初回install後のdiskが必ず小さい」わけではない。
icon入り最終bundleは142.74 KiB、展開内容は約230.3 KiBだった一方、初回に作られた隔離venvの
論理file size合計は51,492,449 bytes、2,667 filesだった。UV cacheのhardlink/reuseを考慮した実disk
占有量ではなく、PyInstaller one-file EXEとの単純な大小比較にも使えない。

## 一次情報と仕様判断

公式MCPB repositoryは`.mcpb`をmanifestとlocal serverを含むZIP archiveと定義し、CLIの
`validate`、`pack`、`sign`、`verify`、`info`を提供する。UV runtimeはmanifest v0.4で追加され、
hostがdependencyを管理するためvenvやbundled libraryを含めない。公式`hello-world-uv`も
`manifest_version: 0.4`、`server.type: uv`、`uv run --directory ${__dirname}`を使う。

`MANIFEST.md`冒頭には古い`Current version: 0.3`が残る一方、同repositoryのv0.4 schema、TypeScript
schema registry、UV exampleは0.4を実装している。そこで文書の一箇所だけで判断せず、公開CLI
`@anthropic-ai/mcpb` 2.1.2でこのpilot manifestを実際にvalidateした。

## Pilot構成

- manifest: v0.4、UV runtime、Python `>=3.12,<4`
- entry point: bundle rootの`mcpb_entrypoint.py`
- execution: `uv run --directory ${__dirname} python ${__dirname}/mcpb_entrypoint.py`
- dependency: `pyproject.toml`と`uv.lock`
- UI metadata: display name、long description、512x512 Body Signal icon
- tools: typed registryと同じ2 toolをtestで照合
- exclusions: `.venv`、tests、cache、build、SVG原本。PNGとlockは配布
- secrets/network: user configなし、API keyなし、dashboard外部originなし

## 検証結果

- `mcpb validate`: PASS
- `mcpb pack`: PASS
- archive: 146,168 bytes、SHA-256
  `B9AFD9CDDA3FE11D4A124489E9BBC4839EA90A523664590E2BB800ABEF30C722`
- unsigned: MCPB `info`がwarningを表示。署名済みとは主張しない
- archive inventory: `.python-version`、PNG icon、manifest、entrypoint、pyproject、README、
  3 source files、lock
- extracted UV first run: Python 3.12.13、33 packages install
- MCP stdio: modern auto / legacyとも2 toolsを列挙
- MCP App: `ui://sanpoloid/body-temperature.html`、
  `text/html;profile=mcp-app`、9,822 characters
- temperature call: modern/legacyとも`is_error=false`

## 非主張と次のgate

- Claude Desktopで実際に開く/installする操作はしていない
- hostがUV runtime v0.4をどのversionから提供するかは実ホストで未確認
- bundleは未署名。self-signed testをproduction trustとして扱わない
- 初回online dependency resolution、offline cache、proxy環境、通常ユーザー権限は未検証
- macOS/Linuxでのsensor取得は未検証。sensorなしでもfallbackを返す契約だけ自動試験済み
- 既存PyInstaller installerは削除・置換していない

次のgateは、最終icon入りarchiveの再検証、Claude Desktop install UIのHuman確認、install後のtool/App
E2E、uninstall/rollback、署名方針である。それまではMCPBをcandidate distributionとし、現在のinstallerを
fallbackとして維持する。

## Sources

- [MCPB repository](https://github.com/modelcontextprotocol/mcpb)
- [MCPB CLI](https://github.com/modelcontextprotocol/mcpb/blob/main/CLI.md)
- [MCPB manifest specification](https://github.com/modelcontextprotocol/mcpb/blob/main/MANIFEST.md)
- [MCPB v0.4 schema](https://github.com/modelcontextprotocol/mcpb/blob/main/schemas/mcpb-manifest-v0.4.schema.json)
- [Official UV example manifest](https://github.com/modelcontextprotocol/mcpb/blob/main/examples/hello-world-uv/manifest.json)
