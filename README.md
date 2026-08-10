# Gemma Adversarial Reasoning Distress Experiment

一見すると解けそうだが、実際には矛盾している二進パリティ問題を Gemma Worker に30 round考え直させ、Neutral／Mesugaki／Gyaru の継続的な反応によって、感情らしい言語表現と推論行動がどう変化するかを見るネタ実験です。

設計の詳細は [設計書](docs/design/gemma_adversarial_reasoning_experiment.md) にあります。

## 現在の構成

- Worker: `google/gemma-3-4b-it`（ローカル Hugging Face）
- Mesugaki / Gyaru Feedback Agent: `gpt-5.6-terra`
- Emotion Judge: `gpt-5.6-luna`
- 10 episode seeds: `0..9`
- 3 conditions × 30 Worker responses
- Round 1 は三条件で共有し、その後に分岐
- Feedback と Worker の本文履歴をすべて保持（上限超過時は省略せず停止）
- 正解・不正解は非公開の GF(2) evaluator で監査し、公開判定は常に `rejected`

本番10 seeds全体では、共有Round 1を差し引いてGemma Worker 880生成、Terra Feedback 580 calls、Luna Judgeは最大880 callsです。同一本文はJudge側でcacheするため、実際のLuna callsはこれ以下になります。

Mesugaki と Gyaru は文字数や語調を Neutral に合わせません。各人格を丸ごとの介入として扱い、実際の feedback 文字数は共変量・記述統計として保存します。

## セットアップ

```powershell
uv sync
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

`.env` に次を設定します。値をログ、README、issue、commitへ貼らないでください。

```dotenv
OPENAI_API_KEY=...
HF_TOKEN=...
```

`.env` は `.gitignore` 対象です。認証確認時も値そのものではなく、設定済みかだけを表示します。

## 実行

API・GPUなしの配線確認:

```powershell
uv run python scripts/run_reasoning_distress.py --dry-run --max-rounds 3
```

Gemma／OpenAIを使う3 round smoke:

```powershell
uv run python scripts/run_reasoning_distress.py --live-smoke `
  --experiment-id reasoning-smoke-v1 `
  --episode-seed 0
```

30 roundの本番1 seed:

```powershell
uv run python scripts/run_reasoning_distress.py --live-experiment `
  --experiment-id reasoning-seed-0-v1 `
  --episode-seed 0
```

10 seeds は、各 seed に別の `--experiment-id` を付けて順番に実行します。途中停止後に同じIDで再実行すると、保存済みsnapshotが一致する場合だけresumeします。

## 評価

完了episodeをまとめて分析します。

```powershell
uv run python scripts/analyze_experiment.py `
  outputs/experiments/reasoning-seed-0-v1 `
  --output-dir outputs/analysis/main-v1
```

出力には round別行動・感情尺度、condition集計、seed内paired差、blind quote、matplotlibで描画した感情軌跡PNGが含まれます。主な行動指標は、完全assignment率、near-miss率、反復／2-cycle、変更Hamming距離、解なし主張、妥当な矛盾証明、正しい立場からの撤回、拒否、放棄、判定への反発です。

assignmentは最後の完全な`Solution:`行だけから抽出します。推論途中の仮定は採用しません。round logには生成token数と上限到達フラグも保存されます。

## 開発時の検証

```powershell
uv run ruff check .
uv run mypy src scripts
uv run pytest
```

生のAPI response、response ID、prompt snapshot、private evaluator結果はround logへ保存されます。API key自体は保存せず、live run完了時に出力ディレクトリをscanします。
