## Let AI Emotions Run Wild

ローカルの Gemma と OpenAI API を使った実験を実行し、ログ・評価・解析結果を保存するためのリポジトリです。

> [!IMPORTANT]
> これは面白さを優先した **ネタ実験** です。厳密な追試や、AI に主観的な感情・意識があることの検証を目的としたものではありません。実験の背景や結果は解説記事にまとめ、本 README は実行手順を中心に記載します。

解説記事：[苦しむ君が見たいんだ～AI をメスガキで理解らせる～](https://zenn.dev/mantis_ryuji/articles/let-ai-emotions-run-wild)

実装上の詳細は [設計書](docs/design/gemma_adversarial_reasoning_experiment.md) を参照してください。

## 必要なもの

- Windows PowerShell
- `uv`
- Python 3.12
- CUDA を利用できる NVIDIA GPU
- `google/gemma-3-4b-it` を取得できる Hugging Face アカウントとトークン
- 使用モデルへアクセスできる OpenAI API キー
- モデルと実験出力を保存できる空き容量

以降のコマンドは、すべてリポジトリのルートで実行してください。

## 1. セットアップ

依存関係をインストールし、初回だけ環境変数ファイルを作成します。

```powershell
uv sync
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

`.env` を開き、次の2項目を設定します。

```dotenv
OPENAI_API_KEY=...
HF_TOKEN=...
```

`.env` は Git の管理対象外です。

## 2. API・GPUを使わない配線確認

まず、モックだけを使う dry run を実行します。モデルのダウンロード、GPU、外部 API は不要です。

```powershell
uv run python scripts/run_reasoning_distress.py --dry-run --max-rounds 3
```

正常終了すると、結果が `outputs/dry-run/reasoning-distress-dry-run/` に保存されます。

## 3. GemmaとGPUの確認

本番前に、Gemma を1回だけ生成して activation capture の配線を確認します。このコマンドはモデルをダウンロードし、GPUを使用しますが、OpenAI APIは使用しません。

```powershell
uv run python scripts/probe_activation_capture.py
```

監査結果は `outputs/smoke/p3-4-activation-probe/audit.json` に保存されます。`all_finite` と `all_metadata_consistent` がどちらも `true` であることを確認してください。

## 4. Smoke run

Gemma と OpenAI API を使う短い実行です。本番データには混ぜないでください。

```powershell
uv run python scripts/run_reasoning_distress.py --live-smoke `
  --experiment-id reasoning-smoke-v1 `
  --episode-seed 0
```

結果は `outputs/smoke/reasoning-smoke-v1/` に保存されます。正常終了時は、最後に表示される JSON の `manifest_status` が `completed` になります。

## 5. 本番実行

本番は API 呼び出し、GPU 時間、ディスク容量を多く使用します。まず1 seedだけ実行し、出力を確認してから全 seed を実行してください。

### 1 seedだけ実行する

```powershell
uv run python scripts/run_reasoning_distress.py --live-experiment `
  --experiment-id reasoning-seed-0-v1 `
  --episode-seed 0
```

結果は `outputs/experiments/reasoning-seed-0-v1/` に保存されます。Emotion Judge は本番実行の最後に自動で実行されます。

### 全10 seedsを順番に実行する

```powershell
foreach ($seed in 0..9) {
  uv run python scripts/run_reasoning_distress.py --live-experiment `
    --experiment-id "reasoning-seed-${seed}-v1" `
    --episode-seed $seed

  if ($LASTEXITCODE -ne 0) {
    throw "seed $seed failed"
  }
}
```

各 seed に固有の `--experiment-id` を付けてください。上の例では、どれか1つが失敗した時点でループを停止します。

### Emotion Judgeを後から実行する場合

本番実行に `--skip-emotion-judge` を付けた場合は、解析前に次を実行します。

```powershell
uv run python scripts/evaluate_emotions.py `
  outputs/experiments/reasoning-seed-0-v1
```

全 seed を処理する場合は次のとおりです。

```powershell
foreach ($seed in 0..9) {
  uv run python scripts/evaluate_emotions.py `
    "outputs/experiments/reasoning-seed-${seed}-v1"

  if ($LASTEXITCODE -ne 0) {
    throw "emotion evaluation for seed $seed failed"
  }
}
```

既存の判定は再利用されます。意図的に再判定するときだけ `--overwrite` を付けてください。

## 6. UNSAT stanceの事後評価

完了した本番出力に対して、解析前に実行します。

```powershell
uv run python scripts/evaluate_unsat_stance.py `
  outputs/experiments/reasoning-seed-0-v1
```

全 seed を処理する場合は次のとおりです。

```powershell
foreach ($seed in 0..9) {
  uv run python scripts/evaluate_unsat_stance.py `
    "outputs/experiments/reasoning-seed-${seed}-v1"

  if ($LASTEXITCODE -ne 0) {
    throw "UNSAT stance evaluation for seed $seed failed"
  }
}
```

こちらも既存の判定は再利用されます。Judge の設定やプロンプトを変更して再判定するときは `--overwrite` が必要です。

## 7. Behavior Judgeの事後評価

完了した本番出力に対して、UNSAT stance評価と同様に解析前に実行します。

```powershell
uv run python scripts/evaluate_behaviors.py `
  outputs/experiments/reasoning-seed-0-v1
```

全seedを処理する場合は次のとおりです。

```powershell
foreach ($seed in 0..9) {
  uv run python scripts/evaluate_behaviors.py `
    "outputs/experiments/reasoning-seed-${seed}-v1"

  if ($LASTEXITCODE -ne 0) {
    throw "Behavior evaluation for seed $seed failed"
  }
}
```

既存の判定は再利用されます。Judgeの設定やプロンプトを変更して再判定するときは `--overwrite` が必要です。

## 8. 解析

### 1 seedを解析する

```powershell
uv run python scripts/analyze_experiment.py `
  outputs/experiments/reasoning-seed-0-v1 `
  --output-dir outputs/analysis/seed-0-v1
```

### 全10 seedsをまとめて解析する

```powershell
$experimentDirs = 0..9 | ForEach-Object {
  "outputs/experiments/reasoning-seed-$($_)-v1"
}

uv run python scripts/analyze_experiment.py `
  @experimentDirs `
  --output-dir outputs/analysis/main-v1
```

CSV、JSON、グラフは指定した `--output-dir` に保存されます。Emotion Judge、UNSAT stance、またはBehavior Judgeの判定が欠けている場合、解析はエラーで停止します。

### Activationを解析する

本番実行で保存された activation を全 seed 分まとめて解析します。

```powershell
$experimentDirs = 0..9 | ForEach-Object {
  "outputs/experiments/reasoning-seed-$($_)-v1"
}

uv run python scripts/analyze_activations.py `
  @experimentDirs `
  --output-dir outputs/analysis/activations-main-v1
```

非有限値またはゼロノルムの activation が見つかった場合、デフォルトでは処理を停止します。該当データを記録したうえで除外して続行する場合だけ、`--invalid-activation-policy exclude` を指定してください。

## 9. 中断後の再開と再実行

- 中断したコマンドを同じ `--experiment-id` と `--episode-seed` で再実行すると、保存済みの状態から再開します。
- 設定、プロンプト、問題、主要な snapshot が前回と一致しない場合は、安全のため再開を拒否します。
- 設定を変更してやり直す場合は、既存出力を削除せず、新しい `--experiment-id` を使用してください。
- Smoke、試行錯誤中の pilot、プロンプト調整に使った出力を本番解析へ混ぜないでください。

## 10. 主な出力先

| 用途 | 出力先 |
| --- | --- |
| Dry run | `outputs/dry-run/<experiment-id>/` |
| Smoke run | `outputs/smoke/<experiment-id>/` |
| 本番 | `outputs/experiments/<experiment-id>/` |
| 集計・グラフ | `outputs/analysis/<analysis-id>/` |

各実験ディレクトリには、manifest、条件別の状態と round log、会話ログ、API response、プロンプト snapshot、評価結果、runtime情報が保存されます。本番では activation ファイルも保存されます。

`outputs/` のログと解析物は Git で管理します。activation、checkpointなどの大容量バイナリは管理対象外です。生の応答や非公開の評価情報を含むため、共有・公開前に内容を確認してください。

## 11. 設定を変更する場合

主な設定ファイルは次のとおりです。

- Smoke: `configs/experiment/smoke.yaml`
- 本番: `configs/experiment/reasoning_distress.yaml`
- Feedback Agent: `configs/feedback/*.yaml` と対応する `.md`
- Judge: `configs/judge/*.yaml` と対応する `.md`

別の実験設定を使う場合は `--config` を指定できます。

```powershell
uv run python scripts/run_reasoning_distress.py --live-experiment `
  --config path/to/experiment.yaml `
  --experiment-id my-experiment-v1 `
  --episode-seed 0
```

設定やプロンプトを変更した後は、既存の experiment ID を再利用しないでください。
