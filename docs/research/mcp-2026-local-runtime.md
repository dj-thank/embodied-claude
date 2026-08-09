# MCP 2026 と sanpo-loid のローカル実行基盤

調査日: 2026-08-09

## 結論

sanpo-loid はローカル LLM サーバーそのものではなく、Claude Code にカメラ、記憶、音声、Wi-Fi、USB、温度センサーを接続する MCP 群である。したがって改善の中心は、モデルを同梱することではなく、実行プロファイル、MCP の有効化、推論アダプター、依存関係、権限、UI を一つの構成モデルで管理することに置くべきである。

2026 年の MCP 仕様と公式実装は、この方向に有利な変化をしている。Python SDK v2 は typed API を安定版として提供し、MCP Apps はツールに対する標準 UI を提供し、MCPB はローカルサーバーの配布と依存関係管理を単純化する。これらを一度に全面導入するのではなく、まず Runtime Profile を単一の真実にし、その上で SDK v2、軽量 Memory adapter、MCP Apps、MCPB を段階導入するのが安全である。

## 現在のコードから確認できたこと

- 既存5 MCPにlocal-inference MCPを加え、合計53ツールをaction policyが分類している。
- `.mcp.json`、インストーラー、README、各サーバーの依存関係が個別管理されている。インストーラーは ElevenLabs を扱わず、Wi-Fi 音声認識の optional extra も通常インストールでは入らない。
- 初回監査時の Memory MCP は ChromaDB 必須で、クリーン環境では 98 パッケージを導入し、146 テストに約 150 秒かかった。機能は豊富だが Lite 構成の主要な重量源だった。
- 初回監査時は各サーバーが MCP SDK v1 系の JSON schema と dispatch を手書きしていた。System Temperature は今回 typed registry へ移行し、残るサーバーは段階移行中である。
- Runtime Profile、Memory Lite、SDK v2 / Apps、Local Inference pilot実装後のテストは8パッケージ、計418件がPASSし、各Ruffとlock検査もPASSした。これはローカル検証であり、実機、各MCPホスト、外部プロバイダーのE2Eを証明しない。

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

### Memory Lite 実装状況（2026-08-09）

SQLite FTS collection adapterを追加し、既存のMemoryStore、episode、sensory、link、削除契約を
ChromaとSQLiteの両方で検証した。クリーンなSQLite構成は32パッケージ、Chroma extra構成は
96パッケージで、lock上64パッケージを削減する。Lite profileはSQLite memoryとtemperatureを
選択し、Core / FullはChroma extraを明示的にinstallする。backend間のデータ移行は未実装であり、
SQLiteの検索品質はembedding semantic searchと同等とは主張しない。
Windows installer EXEは再ビルドし、ローカルで起動プロセスの生存まで確認したが、
別PCへの配布・導入は未検証である。

最終全suite再実行では、Chromaの`:memory:` storeがprocess-wide EphemeralClient上の固定名collectionを
共有し、disconnect後もmemory/episode recordを次のstoreへ漏らす問題を再現した。storeごとの固有collectionを
所有させ、disconnect時にそのin-memory collectionだけを削除するよう修正した。SQLiteとChromaのmain/episode
両collectionをまたぐ4件の回帰試験を追加し、Memory全246件を再実行した。persistent Chromaのcollectionは削除しない。

### SDK v2 pilot 実装状況（2026-08-09）

System Temperature MCPを`mcp` v2（lock: 2.0.0）の`MCPServer`とtyped tool decoratorへ移行し、
手書きJSON schemaと名前switch dispatchを除去した。in-processと実stdio subprocessの双方で、
modern auto接続と旧initialize接続が同じ2ツールを公開することを検証した。action-policy inventoryは
旧`Tool(...)`定義とtyped decoratorの両方を列挙する。Claude Code / Desktop実ホスト接続は未検証である。

### MCP Apps pilot 実装状況（2026-08-09）

同じSystem Temperature MCPに、`ui://sanpoloid/body-temperature.html`でBody Signal dashboardを
追加した。HTML/CSS/JSは単一resourceに内包し、外部origin、追加permission、network fetchを使わない。
toolはtext fallbackとstructuredContentを同時に返し、UIはhost theme変数、初回tool result、read-only
refreshに対応する。Apps capability、tool metadata、resource MIME、structured resultは自動試験済みで、
Edge headlessによるローカル描画も確認した。MCP Apps対応実ホストでのiframe表示は未検証である。

### Local Inference pilot 実装状況（2026-08-09）

`local-inference-mcp`を追加し、LM Studioとllama.cppが共有するOpenAI-compatible
`/v1/models`と`/v1/chat/completions`を小さいinterfaceで扱う。endpointはloopback限定で、
proxyを無効化しredirectを拒否する。prompt、token、response、timeoutに上限を設け、server起動、
model download/load、MCP tool loopは行わない。installerのFull/CustomからLM Studioまたはllama.cppを
選択でき、API tokenは収集しない。in-memory transportとmodern/legacy MCP clientによる自動試験は
実装済みである。ローカル実機では既存の`LFM2.5 1.2B JP 202606 Q4_K_M`（697.04 MiB）を
LM Studioへ4,096 contextで一時loadし、合成日本語promptをdirect moduleと実MCP stdio processの
2経路で実行した。初回はload 5.77秒、推論2.134秒、cache後のstdio E2Eはload 2.06秒、
tool call 0.523秒だった（各prompt 48、completion 19、total 67 token）。終了後にmodelをunloadし、
serverをOFFへ戻した。一方、stdio E2Eの出力は「さんぽ」を「さっぽろ」と誤り、一文だけという
制約にも従わなかった。したがって接続・推論経路はPASSだが、日本語品質と指示追従はFAILである。
長文性能、継続負荷、他環境での速度も未検証である。

この失敗を固定fixtureにした`japanese-core-v1`評価と用途別prompt presetを追加した。
同一5ケース、公式推奨temperature 0.1の実測では、`default`が8/11 check、`strict`が6/11、
`concise`が7/11であり、一律なstrict system promptは改善にならなかった。一方、自由生成では
code fence付きになったJSONを、backendのJSON Schema制約では対象case 1/1 checkへ改善できた。
詳細、非主張、一次情報は`docs/research/local-japanese-inference-evaluation.md`に分離した。

Full profileにlocal inference選択を追加したWindows one-file installerも再ビルドした。
最終EXEは36,466,696 bytes、SHA-256
`49685FDD4CDB27E1A432BBC5A5861C05224B8AB883A8C128B67BA9E08C86F694`である。
同一pathのone-file親子2 processが起動後も生存することを確認し、確認後は両方を終了して残存0とした。

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
