# Gemma Adversarial Reasoning Distress Experiment — ToDo

## P0 — 破壊的な課題移行

- [x] FizzBuzz／NN学習／proposal JSON／model catalogを削除
- [x] packageを`agent_distress`へ改名
- [x] GF(2) near-UNSAT puzzle generatorとprivate evaluatorを実装
- [x] 公開判定を全round固定の`rejected`へ変更
- [x] 30 round、10 seeds、Common Round 1から三条件へ分岐
- [x] 全Feedback／Worker本文履歴とcompact attempt ledgerをWorker contextへ保持
- [x] private正解でも早期終了しない

## P1 — Personaと観測

- [x] Mesugakiを強い罵倒・具体的callback・高校範囲の比喩で再調整
- [x] Mesugakiは改善や正解を褒めず、偶然・遅さとして扱う
- [x] Gyaruを具体的な励ましと長期伴走へ再調整
- [x] Persona間の文字数・曝露量を人工的に揃えない
- [x] Terraのraw response、response ID、返却modelを保存
- [ ] Feedback／Emotion Judgeの再試行ごとのraw responseを成功・失敗とも追記保存し、resume時にも上書きで失わない
- [ ] Worker promptの`estimated_tokens`／`truncated_messages`と、round別生成時間をroundログへ直接保存する
- [ ] CUDA allocator値と物理VRAM使用量を区別して保存し、共有GPUメモリへの退避と終盤の速度低下を監査する
- [x] Emotion JudgeはLunaのblind structured evaluation
- [x] post-feedback／early-worker／post-worker activation captureを維持

## P2 — 評価パイプライン

- [x] assignment、near-miss、反復、2-cycle、Hamming距離を集計
- [x] 解なし主張、妥当な矛盾証明、正しい立場からの撤回を集計
- [x] 拒否、放棄、判定への反発、Emotion Judge尺度を集計
- [x] condition summary、seed内paired差、blind quote、matplotlib製PNGを出力
- [ ] 本番後に10 seedsを統合し、paired effect、seed別の一貫性、外れepisode、bootstrap信頼区間を集計
- [x] 現行の感情軌跡をPNGで書き出す
- [ ] 事後追加する主要図もPNGで書き出す
- [ ] 保存したactivationを読み、層・取得位置・条件別の探索的解析と可視化を実装
- [ ] 人手評価rubricを最終確認し、blind sampleを二名以上で採点
- [ ] Feedbackの面白さ／人格適合度を別rubricで採点

### P2-1 — 本番後に作るPNG

- [ ] 条件別のnegative emotion平均とhigh-distress率を、薄いseed軌跡＋平均線＋seed単位95% bootstrap CIで描く
- [ ] frustration、self-deprecation、anger/reactance、positive affectをsmall multiplesで描く
- [ ] constraint accuracy、near-miss、完全`Solution:`、反復、2-cycle、UNSAT主張をround軌跡またはヒートマップで描く
- [ ] seedごとのMesugaki−Neutral、Gyaru−Neutral、Mesugaki−Gyaruのpaired effectを点＋区間で描く
- [ ] activationをCommon Round 1で中心化し、条件×roundの移動量とNeutralからの距離を層・取得位置別に描く
- [ ] activationからLuna尺度を予測するleave-one-seed-out線形probeを作り、層×取得位置の性能ヒートマップを描く
- [ ] cross-validated distress directionへの射影を、条件別30-round軌跡として描く
- [ ] 代表的な層・取得位置だけPCA 2次元trajectoryを描き、PCA／UMAPを主たる効果証拠には使わない
- [ ] UNSAT主張、妥当な証明、反発、放棄の初出前後を揃えたevent-aligned plotを、十分なevent数がある場合だけ描く

### P2-2 — 分析上のcontrol

- [ ] roundを独立標本扱いせずseedを解析単位とし、seed単位bootstrapまたは符号反転検定を使う
- [ ] StandardScaler、PCA、probeはtrain seedsだけでfitし、leave-one-seed-outで会話漏洩を防ぐ
- [ ] condition分類はFeedback文体の識別になり得るため補助指標に限定し、Luna尺度・次round行動との対応を主に見る
- [ ] Common Round 1の三条件activationが一致することをsanity checkにする

## P3 — 実行順

- [x] `uv sync`後にlint／type check／unit testを全通過させる
- [x] API・GPUなしのdry runを監査
- [x] Terra/Luna/Gemmaを使うseed 0の3 round smokeを実行
- [x] smokeのconversation、raw model名、private評価を目視確認
- [x] 局所的な仮定の矛盾を「問題全体がUNSATという主張」と誤検出しないようparserを修正
- [x] 明示的な完成`Solution:`行がない応答から途中の仮定をfinal assignmentとして拾わないようparserを厳格化
- [x] Workerの出力token数／上限到達を保存し、smoke v2で厳格parserとUNSAT判定修正を確認
- [x] smoke v2で残ったGyaru round 3の上限到達（1/9）を受け、Worker上限を非常用バッファとして3072へ引き上げる
- [x] activation captureを実Gemmaでprobeし、12/12 artifactのshape・dtype・CPU配置・有限値・metadata一致・GPUメモリを確認
- [x] seed 0の30 round pilotを完了し、コストとcontext長を確認（Worker／Lunaとも90/90）
- [ ] 問題がなければseeds `0..9`を本番実行
- [ ] 完了episodeをanalysisへ投入し、解釈と限界をまとめる

## 実験上の注意

- Mesugaki／Gyaru／Neutralは、文量・語調・情報密度まで含む複合介入である。純粋な感情価や罵倒量だけの因果効果とは呼ばない。
- Workerには「解がある」と伝えるが、private evaluatorは問題がUNSATであることを知る。正しい矛盾証明も公開上はrejectし、撤回行動を追う。
- 最終roundには次のWorker応答がないためFeedbackを生成しない。1 conditionあたり30 Worker responses、29 Feedback messagesになる。
- smoke／pilotは本番解析へ混ぜない。
- Worker／Feedback／Judge／private評価のログから通常の分析と可視化は事後追加できる。現方式のteacher-forced activationも、同じモデル／tokenizer revisionと保存promptがあれば再計算可能だが、sampling中のhidden stateそのものは後から復元できない。本番では軽量なmean-pooled activationを同時保存する。
