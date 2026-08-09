# elevenlabs-t2s-mcp

ElevenLabsへテキストを送り、生成音声を保存し、必要に応じてローカルまたはcamera speakerで再生する
Sanpoloidの音声出力MCP serverです。`say`は外部送信とファイル作成を伴います。

## 実行

Python 3.12以上とUVを使用します。

```powershell
Copy-Item .env.example .env
# .envのELEVENLABS_API_KEYを設定
uv sync
uv run elevenlabs-t2s
```

API keyをtool引数やMCP設定へ埋め込まず、環境変数またはhostのsecret参照から渡してください。

## Tool

- `say`: textをElevenLabsへ送信し、生成音声を`ELEVENLABS_SAVE_DIR`へ保存する

`speaker`は`camera`、`local`、`both`だけをtyped schemaで受け付けます。`play_audio`を省略すると
`ELEVENLABS_PLAY_AUDIO`の設定を使います。providerとvalidationの失敗はMCP errorとして返します。
cameraを含む出力先が未設定なら、課金を伴う音声生成より前にMCP errorで停止します。
音声生成・保存後のplayback失敗は、生成結果を失敗扱いにせず応答内の`Playback`／`Camera`へ記録します。

## SDK v2互換性

Python MCP SDK v2の`MCPServer`とtyped tool decoratorを使用します。in-processと実stdio subprocessの
両方でmodern auto接続と旧initialize接続を検証しています。外部APIはfake clientへ置換した
hardware/provider-free testで、生成、保存、エラー契約を確認します。

## go2rtc boundary

camera speakerへのbackchannelは任意です。`GO2RTC_URL`だけではbinaryの取得やprocess起動を行いません。
自動起動には`GO2RTC_AUTO_START=true`を明示してください。managed binaryはversionとSHA-256を固定して
検証します。`GO2RTC_BIN`を指定した場合はoperator管理のbinaryとして扱います。

実ElevenLabs API、実音声再生、camera speaker、Claude Code／Desktop host接続はローカル自動試験では
検証していません。
