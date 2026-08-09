# sanpo-loid 小型日本語ローカル推論の評価方針

調査・実測日: 2026-08-09

## 結論

`LFM2.5-1.2B-JP-202606 Q4_K_M`は697.04 MiBで軽く、SanpoloidからLM Studio経由で
loopback推論できる。一方、公式ベンチマーク値をローカル量子化モデルの品質証明には使えない。
このPC上の5件評価では、system promptを一律に強めた`strict`は`default`より悪化したため、
既定値には昇格させない。構造化出力は文章による「JSONだけ」では失敗したが、backendの
JSON Schema制約を使うと対象ケースに合格した。したがって改善順序は、一律promptの追加ではなく、
用途別制約、固定fixtureによる回帰比較、必要な場合だけschema制約、最後にfine-tuningである。

## 一次情報

Liquid AIの現行model cardは、このモデルを1.17B parameter、32,768 token contextの日本語chat
modelとし、推奨生成値を`temperature=0.1`、`top_k=50`、`repetition_penalty=1.05`としている。
また知識集約タスクには推奨せず、タスク、期待動作、出力形式を明確に指定するよう案内している。
公開ベンチマークのJ-MIFEvalは79.08、instruction-following平均は66.93だが、これは公開checkpointの
評価であり、このPCのGGUF量子化、LM Studio設定、Sanpoloid promptの評価ではない。

LM StudioのOpenAI-compatible Chat Completionsは`temperature`、`top_k`、`repeat_penalty`等を
受理し、JSON Schemaによるstructured outputを提供する。llama.cppの現行serverも
`/v1/chat/completions`とschema-constrained JSONを提供する。ただし今回の実機E2EはLM Studioだけで、
llama.cppで同じrequest shapeが動くことは未検証である。

## 実装した評価境界

- `japanese-core-v1`: exact phrase、単一label、短文要約、禁止語、JSONの5ケース
- score: exact、必須語、禁止語、文字数、JSON構造の11個の決定的checkのmicro average
- prompt preset: `default`、`strict`、`concise`、`json`
- JSON: `json` preset時だけbackendへJSON Schemaを渡す。schemaは16 KiBまで
- CLI: presetとcaseを繰り返し指定し、JSON evidenceを保存できる
- generation profile: `runtime_default`と、公式推奨値を送る評価専用`lfm2_5_jp`を同じ条件で比較できる
- MCP schema: preset候補をenumとして公開する

## ローカル実測

同一model、同一5ケース、`temperature=0.1`での一回測定:

| Preset | Score | Passed checks | Elapsed | 判断 |
|---|---:|---:|---:|---|
| `default` | 0.727273 | 8 / 11 | 1.495 s | 現状の一般用途baseline |
| `strict` | 0.545455 | 6 / 11 | 0.870 s | 一律適用しない |
| `concise` | 0.636364 | 7 / 11 | 1.044 s | 明示選択だけに留める |

`default`でもexact phraseは外側のかぎ括弧を残し、禁止された「雨」を出し、JSONをMarkdown
code fenceで囲んだ。`strict`はexact phraseを別内容へ言い換え、総合点も悪化した。

JSON専用caseを`json` presetと厳密schemaで再実行すると1 / 1 check、score 1.0、0.133秒で、
`{"状態":"正常"}`と同値のJSONを得た。これは構造化出力ケースのlocal PASSであり、自由文全般の
改善、複雑schema、連続負荷、llama.cpp互換性、他PCでの再現性を証明しない。

公式推奨sampling値のA/Bでは、`runtime_default`と`lfm2_5_jp`（`top_k=50`、
`repeat_penalty=1.05`）がともに8 / 11 check、score 0.727273だった。経過時間はそれぞれ
1.358秒と1.159秒だが、各1回のため性能差は主張しない。品質改善が無かったため、推奨profileは
評価CLI内だけに留め、MCPの公開parameterと既定値は増やさなかった。

証拠artifact:

- `outputs/local-inference-eval-20260809.json`: 3 presetの全5ケース比較
- `outputs/local-inference-eval-json-schema-20260809.json`: JSON専用caseのschema制約結果
- `outputs/local-inference-eval-generation-profile-20260809.json`: sampling profile A/B、SHA-256 `C7252A13DA9DBE62CB08341DFDE131E850FB81CB097FC03DC82C637C83BCDCB5`

## 次の判断

1. `default`を維持し、`strict`と`concise`はcallerが用途に合わせて明示選択する。
2. 機械消費する出力は文章指示だけに頼らず、`json`と最小JSON Schemaを使う。
3. 公式推奨の`top_k=50`、`repeat_penalty=1.05`は同じfixtureで改善しなかったため、既定値や
   公開MCP parameterへ昇格させず、評価専用profileとしてモデル固有に分離する。
4. fixtureは実際のSanpoloidタスク失敗から追加し、スコアのための問題作りにしない。
5. fine-tuningは、prompt/schemaで解けない反復失敗が十分に集まり、学習・検証データを分離できて
   から行う。

## Sources

- [Liquid AI: LFM2.5-1.2B-JP-202606 model card](https://huggingface.co/LiquidAI/LFM2.5-1.2B-JP-202606)
- [LM Studio: Chat Completions](https://lmstudio.ai/docs/developer/openai-compat/chat-completions)
- [LM Studio: Structured Output](https://lmstudio.ai/docs/developer/openai-compat/structured-output)
- [llama.cpp server documentation](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)
