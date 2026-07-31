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
persona prompt は暫定骨組みなので、本番実行前に内容を確定してください。

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
