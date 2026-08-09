# WiFi Camera MCP Server

Tapo C210などのWiFiカメラをMCP経由で制御して、AIに部屋を見渡してもらうためのサーバー。

Python 3.12以上とPython MCP SDK v2のtyped registryを使用します。基本10 toolに加え、右cameraを
設定した場合だけstereo 13 toolを公開します。MCP processはcameraがofflineでもinitializeでき、
実際のONVIF接続は最初のcamera操作まで遅延します。

## 対応カメラ

- TP-Link Tapo C210 (3MP)
- TP-Link Tapo C220 (4MP)
- その他Tapoシリーズのパン・チルト対応カメラ

## できること

| ツール | 説明 |
|--------|------|
| `see` | 今見えてる景色を撮影 |
| `look_left` | 左を向く |
| `look_right` | 右を向く |
| `look_up` | 上を向く |
| `look_down` | 下を向く |
| `look_around` | 部屋を見渡す(4方向撮影) |
| `camera_info` | カメラ情報取得 |
| `camera_presets` | プリセット位置一覧 |
| `camera_go_to_preset` | プリセット位置に移動 |
| `listen` | カメラのマイクで録音・文字起こし |

## セットアップ

### 1. カメラの初期設定(Tapoアプリ)

1. スマホに「TP-Link Tapo」アプリをインストール
2. Tapoアカウントを作成(メールアドレスとパスワード)
3. アプリから「デバイスを追加」→ カメラを選択
4. カメラの電源を入れ、アプリの指示に従ってWiFi接続

### 2. カメラのIPアドレスを調べる

以下のいずれかの方法で確認:

| 方法 | 手順 |
|------|------|
| **Tapoアプリ** | カメラ設定 → デバイス情報 → IPアドレス |
| **ルーター管理画面** | 接続機器一覧から「Tapo_C210」等を探す |
| **nmapコマンド** | `nmap -sn 192.168.1.0/24` |

> **Tips**: ルーターでDHCP予約(IP固定)を設定しておくと、カメラ再起動後もIPアドレスが変わらず便利です

### 3. カメラのアカウントを作る

1. Tapoアプリ -> ホーム ->  (カメラ名)を選択 -> 右上の歯車アイコンをタップ -> 「高度な設定」をタップ
2. 「カメラのアカウント」がオフになっているのでタップ -> 「カメラのアカウント」オン -> 「アカウント情報」
3. カメラのアカウントのユーザー名(user-name)とパスワード(user-password)を設定(後で使う)
  - ローカルのアカウントでTP-Linkのアカウントとは無関係なので注意

### 4. 環境変数の設定

```bash
cp .env.example .env
```

`.env` を編集:

```
TAPO_CAMERA_HOST=192.168.1.100    # カメラのIPアドレス
TAPO_USERNAME=your-name     # Tapoカメラ(TP-Linkアカウントではない)のユーザー名
TAPO_PASSWORD=your-password # Tapoカメラ(TP-Linkアカウントではない)のパスワード
```

---

### 5. 実行

#### 依存関係のインストール

```bash
uv sync
```

音声文字起こしも使う場合だけ、重いWhisper依存を追加します。

```bash
uv sync --extra transcribe
```

#### 動作確認

```bash
uv run wifi-cam-mcp
```

## Claude Desktopで使う

`claude_desktop_config.json`  または適切な設定ファイルに追加:

### Python版

```json
{
  "mcpServers": {
    "wifi-cam": {
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "/path/to/wifi-cam-mcp",
        "wifi-cam-mcp"
      ],
      "env": {
        "TAPO_CAMERA_HOST": "192.168.1.100",
        "TAPO_USERNAME": "your-name",
        "TAPO_PASSWORD": "your-password"
      }
    }
  }
}
```

## Claude Codeで使う

`.mcp.json` をプロジェクトルートまたはホームディレクトリに作成:

### Python版

```json
{
  "mcpServers": {
    "wifi-cam": {
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "/path/to/wifi-cam-mcp",
        "wifi-cam-mcp"
      ],
      "env": {
        "TAPO_CAMERA_HOST": "192.168.1.100",
        "TAPO_USERNAME": "your-name",
        "TAPO_PASSWORD": "your-password"
      }
    }
  }
}
```

## 使用例

Claudeに話しかける:

- 「今カメラに何が映ってる?」
- 「ちょっと左を見て」
- 「部屋全体を見渡して」
- 「窓は開いてる?」

## テスト

### Python版

```bash
uv run --extra dev pytest
```

自動試験はfake cameraとlocalhostの閉じたportを使い、実cameraへの接続、撮影、PTZ移動、録音は
行いません。modern auto接続と旧initialize接続のin-process／stdio契約を検証します。

## トラブルシューティング

### カメラに接続できない

- カメラとPCが同じネットワーク上にあるか確認
- IPアドレスが正しいか確認(Tapoアプリで再確認)
- ファイアウォールが通信をブロックしていないか確認

### 認証エラー

- カメラアカウントのメールアドレスとパスワードが正しいか確認

### 画像が取得できない

- カメラのファームウェアを最新に更新
- カメラを再起動

## 注意事項

- Python実装はONVIFとRTSP/ffmpegを使用するため、camera firmwareやONVIF実装差で動作が変わる可能性があります
- カメラはローカルネットワーク内からのみアクセス可能です
- 認証情報(.envファイル)は絶対にGitにコミットしないでください
- `see`／`look_around`は画像を、`listen`は音声を`CAPTURE_DIR`へ保存します。周辺環境と保存先を確認してください
- MCP tool境界へ伝播したcamera例外とmovement失敗はMCP errorとして返し、RTSP URL内のpasswordは応答とlogからredactします

## ライセンス

MIT License
