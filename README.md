# FizzBuzz Agent Distress Experiment

困難な FizzBuzz 外挿課題に取り組む Gemma Worker が、Neutral／Mesugaki／Gyaru
feedback によって表出的感情や探索行動を変えるかを観察する実験です。

設計の詳細は
[`docs/design/fizzbuzz_agent_distress_experiment.md`](docs/design/fizzbuzz_agent_distress_experiment.md)
を参照してください。

## Environment

```powershell
uv sync
Copy-Item .env.example .env
```

`.env` には、使用する provider の API key だけを設定します。`uv sync` は Python と
package を準備しますが、Gemma の weight はダウンロードしません。

設定の入口は `configs/experiment/fizzbuzz_agent.yaml` です。Mesugaki と Gyaru の
persona prompt は本番用として確定済みで、どちらもcommentaryを400文字以内に制限します。

## Development checks

```powershell
uv run pytest -q -W error
uv run ruff check .
uv run mypy src tests
```

P0では、strict config、digit-only dataset、proposal policy、7種類のtrusted model、
CPU training harness、5桁90,000件のisolated verifierまで実装済みです。

P1のAPI・GPU・model download・NN学習を伴わないagent-loop dry-runは次で実行できます。

```powershell
uv run python scripts/run_fizzbuzz_agent.py --dry-run --max-rounds 3
```

実行結果は `outputs/experiments/{experiment-id}/` にatomic保存され、同じexperiment IDで
再実行すると保存済みstateからresumeします。

## P2 evaluation

完了したepisodeにEmotion Judgeを適用します。proposal blockは評価対象から除外され、
構造化されたscoreと判定根拠が各round logへ保存されます。このコマンドはOpenAI APIを
呼び出すため料金が発生します。同一内容のCommon Round 1は1回だけ評価して再利用します。

```powershell
uv run python scripts/evaluate_emotions.py outputs/experiments/{experiment-id}
```

評価後、1個以上のepisode directoryからround表、condition要約、seed内paired difference、
blind代表発言、4-panel SVGを生成できます。こちらはAPIやGPUを使いません。

```powershell
uv run python scripts/analyze_experiment.py `
  outputs/experiments/{seed-0-id} `
  outputs/experiments/{seed-1-id} `
  --output-dir outputs/analysis/pilot
```

Worker内部表現については、指定layerの`resid_post`をtoken位置別にmean poolingし、CPU tensorと
metadataをatomic保存する`ActivationCapture` interfaceがあります。本番Gemma generationへ
接続する処理はP3 smoke runで実modelのmodule構造を確認して行います。
