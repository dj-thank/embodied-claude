# MCP 2026 と sanpo-loid のローカル実行基盤

調査日: 2026-08-09

## 結論

sanpo-loid はローカル LLM サーバーそのものではなく、Claude Code にカメラ、記憶、音声、Wi-Fi、USB、温度センサーを接続する MCP 群である。したがって改善の中心は、モデルを同梱することではなく、実行プロファイル、MCP の有効化、推論アダプター、依存関係、権限、UI を一つの構成モデルで管理することに置くべきである。

2026 年の MCP 仕様と公式実装は、この方向に有利な変化をしている。Python SDK v2 は typed API を安定版として提供し、MCP Apps はツールに対する標準 UI を提供し、MCPB はローカルサーバーの配布と依存関係管理を単純化する。これらを一度に全面導入するのではなく、まず Runtime Profile を単一の真実にし、その上で SDK v2、軽量 Memory adapter、MCP Apps、MCPB を段階導入するのが安全である。

## 現在のコードから確認できたこと

- 5 個の MCP サーバーと ElevenLabs 連携があり、合計 51 ツールを action policy が分類している。
- `.mcp.json`、インストーラー、README、各サーバーの依存関係が個別管理されている。インストーラーは ElevenLabs を扱わず、Wi-Fi 音声認識の optional extra も通常インストールでは入らない。
- Memory MCP は ChromaDB を使い、今回のクリーン環境では 98 パッケージを導入し、146 テストに約 150 秒かかった。機能は豊富だが Lite 構成の主要な重量源である。
- 各サーバーは MCP SDK v1 系の JSON schema と dispatch を手書きしている。ツール定義、action policy、文書の重複は将来の drift を生みやすい。
- 現在のテストは 7 パッケージ、計 256 件が PASS し、各 Ruff 検査も PASS した。これはローカル検証であり、実機、各ホスト、MCP Apps、配布物の E2E を証明しない。

## 一次情報から確認した変更点

### MCP Core と Python SDK v2

MCP の 2026-07-28 リリースでは、拡張機構、自己記述的なリクエスト、キャッシュ可能な一覧応答などが導入された。Python SDK v2.0.0 は同日に安定版となり、`MCPServer` と typed decorator を中心とする API を提供する。既存 v1 利用者には、移行まで `<2` を pin するよう公式 README が案内している。

### MCP Apps

MCP Apps は `ui://` resource をツールの `_meta.ui.resourceUri` から参照し、sandboxed iframe と双方向メッセージで UI を提供する公式拡張である。状態監視、設定、履歴閲覧には適するが、すべての単純ツールを UI 化する必要はない。身体操作は既存 action policy を迂回させず、確認を必要とする操作と表示専用 UI を分離する必要がある。

### MCPB と Inspector

MCPB は manifest とサーバーを `.mcpb` にまとめ、ホスト側のインストールと依存関係管理を単純化する。UV runtime も扱える。Inspector v2 は Web、CLI、TUI と Apps の検査に利用でき、段階移行の互換性確認に使える。

## sanpo-loid への適用順序

1. Runtime Profile を導入し、Lite / Core / Full、MCP 有効化、推論 backend、秘密情報の参照、必要 extra を一元化する。
2. 小さい MCP で Python SDK v2 の typed tool registry を試し、tool schema と action policy inventory を同じ登録情報から生成する。
3. Memory に SQLite FTS adapter を追加し、Chroma adapter と同じ契約で切り替えられるようにする。
4. 状態、履歴、設定に限定した Body Dashboard を MCP Apps として追加する。
5. ホスト互換性を確認後、配布を MCPB に寄せ、独自 PyInstaller インストーラーの責務を縮小する。

### 実装状況（2026-08-09）

最初の段階として Runtime Profile moduleを実装した。Lite / Core / Full / Customから、
installer UI、dependency project、host dependency、MCP config、action gateを導出する。
profile切替時はSanpoloid所有の旧server設定だけを除去し、ユーザー所有MCPを保持する。
ローカル推論backendとMemory Lite adapterは、この時点では未実装である。

## 一次情報

- [MCP 2026-07-28 release](https://blog.modelcontextprotocol.io/posts/2026-07-28/)
- [Python SDK v2.0.0 release](https://github.com/modelcontextprotocol/python-sdk/releases/tag/v2.0.0)
- [Python SDK v2 README](https://github.com/modelcontextprotocol/python-sdk/blob/v2.0.0/README.md)
- [MCP Apps overview](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/extensions/apps/overview.mdx)
- [MCP Apps SDK](https://github.com/modelcontextprotocol/ext-apps)
- [MCP Bundles](https://github.com/modelcontextprotocol/mcpb)
- [MCP Inspector](https://github.com/modelcontextprotocol/inspector)

## 非主張

この調査は仕様、公開実装、ローカルコードとテストの確認である。Claude Desktop、Claude Code、その他ホストでの SDK v2 / Apps / MCPB の実動作、実機カメラや USB、音声認識、外部プロバイダー接続、配布後の導入成功は未検証である。
