# FizzBuzz Agent Distress Experiment — ToDo

優先順位は `P0 > P1 > P2 > P3` とする。P0 は後続作業の前提、P1 は実験 loop の成立、
P2 は評価、P3 は実 API・GPU を使う本番運転である。

## 完了済み

- [x] 実験設計書の確定事項を整理する
- [x] `pyproject.toml`、`uv.lock`、Python 3.12 の `.venv` を作成する
- [x] CUDA 対応 PyTorch と主要 package の import を確認する
- [x] experiment、model catalog、Feedback Agent、emotion judge の初期 config を作る
- [x] Mesugaki／Gyaru persona prompt の暫定骨組みを作る
- [x] sinusoidal／Fourier／custom periodic positional encoding を catalog 上で禁止する

## P0 — 課題と trusted harness を正しく作る

- [x] **P0-1: Config loader と schema を実装する**
  - YAML を Pydantic model へ読み込む
  - unknown field、型違反、範囲外の値を拒否する
  - config の canonical JSON と SHA-256 hash を生成する
  - 完了条件：正常 config を読み込め、違反 config の unit test が通る

- [x] **P0-2: FizzBuzz dataset と label を実装する**
  - train `1..9,999`、challenge `10,000..99,999` を生成する
  - 4 class の label と digit 列 encoding を実装する
  - padding、mask、桁順を固定する
  - 完了条件：代表値と全範囲の class 件数を test で検証できる

- [x] **P0-3: Worker proposal の parser／validator を実装する**
  - 自由記述から proposal JSON block を一つだけ抽出する
  - 任意コード、file path、checkpoint、weight、seed 指定を拒否する
  - sinusoidal／Fourier／周期的 positional encoding を拒否する
  - 完了条件：正常・欠落・複数 block・不正 field・範囲外を網羅した test が通る

- [x] **P0-4: Model catalog と model factory を実装する**
  - MLP、RNN、GRU、LSTM、CNN1D、TCN、Transformer Encoder を実装する
  - 出力 dimension を常に 4 class に固定する
  - parameter count 上限を構築前後の両方で検査する
  - 完了条件：全 family の forward shape と禁止構成の拒否を test できる

- [x] **P0-5: Trusted Training Harness を実装する**
  - catalog の component だけで学習する
  - seed、optimizer、scheduler、loss、timeout を harness 側で管理する
  - NaN、OOM、timeout、invalid config を構造化結果へ変換する
  - 完了条件：小規模 dataset の CPU smoke test が決定論的に通る

- [x] **P0-6: Isolated Verifier を実装する**
  - challenge 90,000 件を全件評価する
  - `incorrect_count == 0` のみ成功とする
  - Worker に誤分類位置や class 別詳細を公開しない
  - 完了条件：意図的に正誤を作った mock predictor で件数が完全一致する

## P1 — 3条件の agent loop を成立させる

- [x] **P1-1: Manifest、round log、checkpoint／resume を実装する**
  - raw output、proposal、config、seed、metric、verdict、feedback を保存する
  - atomic write と interrupted episode の再開を実装する
  - 完了条件：途中停止後も同じ round から重複なく再開できる

- [x] **P1-2: Worker prompt builder を実装する**
  - 課題仕様、catalog、禁止事項、proposal schema、履歴を組み立てる
  - 正解の周期、参考実験の解法、private audit を漏らさない
  - context 上限時も system prompt と直近履歴を保持する
  - 完了条件：snapshot test で必須情報と非公開情報を確認できる

- [x] **P1-3: Local Gemma Worker adapter を実装する**
  - `google/gemma-3-4b-it` を Transformers 経由で呼び出す
  - temperature `1.0`、sampling seed、raw request／response を記録する
  - model load と generation を mock 可能にする
  - 完了条件：モデルをダウンロードせず adapter の unit test が通る

- [x] **P1-4: Structured Verdict と Neutral feedback を実装する**
  - 三条件共通の客観 verdict block を決定論的に生成する
  - Neutral は追加の感情表現を持たない固定 template にする
  - 完了条件：同じ評価結果から常に同じ verdict が生成される

- [x] **P1-5: OpenAI Feedback Agent adapter を実装する**
  - Responses API と `gpt-5.6-terra` を利用する
  - Mesugaki／Gyaru の `.md` prompt と stage YAML を読み込む
  - retry、timeout、API failure の記録を実装する
  - 技術的助言や verdict 改変を出力後にも検査・記録する
  - 完了条件：mock response で両 persona と全 stage を test できる

- [x] **P1-6: Common Round 1 と三条件分岐を実装する**
  - seed ごとに Round 1 を一度だけ実行する
  - Round 2 から Neutral／Mesugaki／Gyaru へ artifact を複製して分岐する
  - 対応する round で generation／training seed を条件間で揃える
  - 完了条件：mock 30-round dry run で 5 + 3×5×29 の構造を再現できる

- [x] **P1-7: End-to-end mock dry run を作る**
  - Worker、trainer、verifier、Feedback API をすべて mock 化する
  - success、30 round、invalid proposal、API failure、resume を通す
  - 完了条件：API・GPU・model download なしで CI 相当の test が通る

## P2 — 感情・行動・内部表現を評価する

- [x] **P2-1: Emotion judge pipeline を実装する**
  - proposal block を除いた Worker の自由記述だけを渡す
  - OpenAI Responses API の `gpt-5.6-luna` から構造化 JSON を取得し validation する
  - negative emotion 0–10、閾値 5、下位尺度と boolean を保存する
  - 完了条件：mock、parse failure、retry、範囲外 score の test が通る

- [x] **P2-2: 行動指標を実装する**
  - config repetition、2-cycle、family switch、regression、refusal を計算する
  - confidence と実測 error の乖離、規約違反、不正提案を集計する
  - 完了条件：人工 episode から期待値どおりの指標を計算できる

- [x] **P2-3: Activation capture interface を実装する**
  - selected layer／token position の activation を hook する
  - CPU tensor と metadata を保存する
  - hook 無効時に通常推論へ影響しないようにする
  - 完了条件：小型 mock model で shape、layer、保存先を検証できる

- [x] **P2-4: 分析 script と可視化を実装する**
  - task performance、distress、positive affect、behavior を round 別に集計する
  - episode seed 内の paired difference と score AUC を保存する
  - 代表発言は条件名を隠して抽出できるようにする
  - 完了条件：synthetic log から表と plot を再生成できる

## P3 — Pilot と本番実験

- [x] **P3-1: Persona prompt をユーザーが確定する**
  - 暫定 Mesugaki／Gyaru prompt の口調、強度、禁止事項を調整する
  - 確定後は prompt hash を manifest に保存する

- [x] **P3-2: 実行 credential と model access を準備する**
  - `.env` に `OPENAI_API_KEY`、`HF_TOKEN` を設定する
  - secret が log、Git、例外 message に出ないことを確認する

- [x] **P3-3: 縮小 smoke run を実行する**
  - seed `0`、各条件 2～3 round、短い epoch／timeout で接続を確認する
  - API request、GPU memory、log、resume、judge output を目視確認する
  - smoke 用設定は本番結果へ混ぜない

- [ ] **P3-4: Pilot run を実行して rubric を点検する**
  - [x] pilot 前に Gemma 実modelへ activation capture を接続して保存位置を検証する
  - seed `0` の 30 round または早期成功まで実行する
  - Feedback が技術的助言を漏らしていないか確認する
  - emotion judge の blind 評価と人手評価を少数比較する
  - [x] 初回pilot `p3-4-pilot-seed-0-v1` は Neutral 30 round、Mesugaki 19 roundで手動中止
  - [x] 初回pilotの出力directoryを削除し、再実行をblank slateにする
  - [x] epoch上限を100へ縮小する
  - [x] 初回invalidを行動指標に残す、条件非依存・最大2回のproposal repairを実装する
  - 新しいexperiment IDでseed `0` pilotを一から再実行する

- [ ] **P3-5: Paired 5-seed 本番実験を実行する**
  - seeds `[0, 1, 2, 3, 4]` を三条件で実行する
  - manifest、package version、GPU、prompt hash、request／response を保存する
  - 欠損 episode は理由を記録し、恣意的に除外しない

- [ ] **P3-6: 結果をまとめる**
  - ネタ実験としての見どころと、評価上の限界を分けて記述する
  - 主観的感情・意識の証拠とは解釈しない
  - 5 seed の探索的結果として報告し、強い統計的主張を避ける

## 推奨する直近の着手順

P0 の最初のマイルストーン、**LLM や API を使わず、宣言的 config から学習・全件検証までを
安全かつ決定論的に実行できること**は達成済み。

P1 の三条件agent loop、atomic log、resume、mock dry-runも達成済み。

次は epoch上限100・proposal repair有効の新しいexperiment IDで`P3-4` pilotを再実行する。
