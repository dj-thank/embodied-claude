# usb-webcam-mcp

USB webcamをSanpoloidのread-onlyな視覚として公開するMCP serverです。

## 実行

Python 3.12以上とUVを使用します。

```powershell
uv sync
uv run usb-webcam-mcp
```

## Tools

- `list_cameras`: camera indexと現在の解像度を列挙する。画像は取得・返却しない
- `see`: 指定cameraから1枚のJPEGを取得する

`see`の`camera_index`は0以上、`width`と`height`は1〜7,680 pixelにtyped schemaで制限する。
camera I/Oはevent loop外のworker threadで実行し、失敗はMCP errorとして返す。

## SDK v2互換性

Python MCP SDK v2の`MCPServer`とtyped tool decoratorを使用する。in-processと実stdio subprocessの
両方でmodern auto接続と旧initialize接続を検証している。action-policy inventoryも同じdecoratorから
2 toolを列挙する。

WindowsではOpenCV backendをDirectShowへ固定する。このPCのcontent-free camera scanでは、
10 indexの直接走査が既定backend 12.167秒からDirectShow 1.422秒へ短縮し、MCP process起動を含む
`list_cameras`は約3.2秒だった。数値はこのPCの一回測定であり、他PCでの性能保証ではない。

## Privacy boundary

自動試験はfake JPEGを使う。実機確認では`list_cameras`だけを呼び、index 0、640x480を検出した。
実際の周辺画像は取得、保存、表示していない。`see`を呼ぶとcamera画像がMCP clientへ返るため、callerは
利用者の意図と周辺環境を確認すること。
