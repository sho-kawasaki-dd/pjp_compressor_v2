# ログ多言語化 実装計画

## 目的

UI の静的文言と同様に、ログ出力も JA/EN を選択できるようにする。

今回の前提は以下の通り。

- ログ言語は UI 言語設定を流用する
- `app_settings` に別の `log_language` は追加しない
- 対象範囲には画面ログ、CSV ヘッダー、CSV の `action` / `notes`、cleanup などの補助ログを含める
- 言語変更は次回起動後に反映する
- backend は `frontend.i18n` を直接 import せず、shared helper 経由で locale catalog を参照する

## 設計方針

現状は backend が日本語の完成済み文字列を生成し、frontend はそれをそのまま表示している。
このため、単純に locale キーを足すだけでは不十分で、以下をセットで実施する。

1. 実行時言語を `CompressionRequest` 経由で backend へ渡す
2. backend/frontend 共用のログ文言 helper を shared 層へ追加する
3. backend 側の直書き文字列をキー駆動へ置き換える
4. frontend 側の「ログ本文の日本語部分一致による状態遷移」を撤去する

## 実装タスク

### Task A: request 契約を拡張する

- 対象ファイル
  - `backend/contracts.py`
  - `tests/unit/test_contracts.py`
- 内容
  - `CompressionRequest` に `log_language` 相当の実行言語フィールドを追加する
  - 既存 call site とテストを更新する
- 完了条件
  - request 契約が新フィールド込みで整合し、既存生成経路が崩れない

### Task B: request builder で current language を渡す

- 対象ファイル
  - `frontend/ui_tkinter_mapper.py`
  - 必要に応じて `frontend/i18n.py`
  - `tests/integration/test_job_runner.py`
- 依存
  - Task A
- 内容
  - `build_compression_request()` で `get_current_language()` を使って実行言語を設定する
  - `ui_language.get()` は使わず、次回起動後反映の仕様を守る
- 完了条件
  - backend に渡る request に現在有効な言語が入る

### Task C: shared ログ文言 helper を追加する

- 対象ファイル
  - `shared/` 配下の新規 helper
  - `tests/unit/` 配下の helper 用テスト
- 依存
  - なし。Task A と並行可能
- 内容
  - locale catalog を指定言語で読み込む helper を追加する
  - missing key は安全な fallback を返す
  - frontend の既存 `t()` は維持し、backend 側のみ新 helper を利用する
- 完了条件
  - backend から JA/EN のログ文言を同じ API で取得できる

### Task D: locale キーを追加する

- 対象ファイル
  - `frontend/config_data/locales/ja.json`
  - `frontend/config_data/locales/en.json`
- 依存
  - Task C
- 内容
  - backend log 用キーを追加する
  - CSV header 用キーを追加する
  - CSV action / notes 用キーを追加する
  - size summary 用キーを追加する
- 完了条件
  - backend で必要なキーが JA/EN 両方に揃う

### Task E: job_runner のジョブ全体ログをキー駆動へ置換する

- 対象ファイル
  - `backend/orchestrator/job_runner.py`
- 依存
  - Task B, C, D
- 内容
  - 依存検出ログを置換する
  - 空入力ログを置換する
  - ZIP 展開開始と結果ログを置換する
  - 並列処理開始ログを置換する
  - CSV 作成成功と失敗ログを置換する
  - ZIP 再生成ログを置換する
  - 完了ログと統計ログを置換する
  - top-level error を置換する
- 完了条件
  - `job_runner.py` に残る日本語固定ログがなくなる

### Task F: CSV 文言をローカライズする

- 対象ファイル
  - `backend/orchestrator/job_runner.py`
  - locale catalog
- 依存
  - Task E
- 内容
  - CSV header を JA/EN で切り替える
  - CSV の `action` を JA/EN で切り替える
  - CSV の `notes` を JA/EN で切り替える
  - CSV ファイル名 `compression_log_YYYYMMDD_HHMMSS.csv` は維持する
- 完了条件
  - CSV を開いたときの固定文言が JA/EN で揃う

### Task G: cleanup ログをローカライズする

- 対象ファイル
  - `backend/core/file_ops.py`
- 依存
  - Task C, D
- 内容
  - 未指定ログを置換する
  - 削除ログを置換する
  - 削除失敗ログを置換する
  - 空フォルダ削除ログを置換する
  - cleanup 完了ログを置換する
  - cleanup 失敗ログを置換する
- 完了条件
  - cleanup 補助ログが JA/EN 化される

### Task H: ZIP 展開ログをローカライズする

- 対象ファイル
  - `backend/core/archive_utils.py`
- 依存
  - Task C, D
- 内容
  - 展開成功ログを置換する
  - 展開失敗ログを置換する
  - cycle 上限ログを置換する
  - 全体エラーログを置換する
- 完了条件
  - ZIP 展開補助ログが JA/EN 化される

### Task I: 画像圧縮結果メッセージをローカライズする

- 対象ファイル
  - `backend/core/image_utils.py`
- 依存
  - Task C, D
- 内容
  - Pillow JPEG/PNG の結果文言を置換する
  - pngquant の成功文言を置換する
  - fallback 文言を置換する
  - 失敗文言を置換する
- 完了条件
  - 画像圧縮結果が JA/EN で統一される

### Task J: PDF 圧縮結果メッセージをローカライズする

- 対象ファイル
  - `backend/core/pdf_utils.py`
- 依存
  - Task C, D
- 内容
  - native lossy/lossless の結果文言を置換する
  - Ghostscript の skip / ok / failure を置換する
  - combined path の文言を置換する
  - detail summary を置換する
- 完了条件
  - PDF 圧縮結果が JA/EN で統一される

### Task K: worker の message 合成責務を整理する

- 対象ファイル
  - `backend/core/worker_ops.py`
- 依存
  - Task I, J
- 内容
  - action 部分と size summary 部分の責務を分ける
  - UI 表示と CSV が同じ完成文言を安全に共有できるようにする
- 完了条件
  - worker 戻りメッセージの構造が整理され、翻訳点が増殖しない

### Task L: controller の文字列部分一致依存を撤去する

- 対象ファイル
  - `frontend/ui_tkinter_controller.py`
- 依存
  - Task E, K
- 内容
  - `_append_log()` の `'完了！'` 判定を撤去する
  - `_append_log()` の `'処理中にエラー発生'` 判定を撤去する
  - 完了や失敗の状態更新を `stats` / `error` / 必要なら `status` event ベースに寄せる
- 完了条件
  - ログ本文の自然言語に依存せず status が更新される

### Task M: cleanup 呼び出し境界の責務を整理する

- 対象ファイル
  - `frontend/ui_tkinter_controller.py`
  - `backend/core/file_ops.py`
- 依存
  - Task G, L
- 内容
  - cleanup target label の受け渡しを見直す
  - 翻訳済み文字列依存を減らす
  - controller と backend の責務境界を明確にする
- 完了条件
  - cleanup 呼び出し境界が多言語化に対して安定する

### Task N: 自動テストを更新する

- 対象ファイル
  - `tests/unit/test_contracts.py`
  - `tests/unit/test_i18n.py`
  - helper 用 unit test
  - `tests/integration/test_job_runner.py`
  - `tests/integration/test_ui_controller.py`
- 依存
  - 主要実装完了後
- 内容
  - request 言語の伝播を検証する
  - JA/EN のログ出力を検証する
  - JA/EN の CSV header/action/notes を検証する
  - empty input / ZIP 展開 / cleanup の回帰を検証する
  - controller の status 更新が文字列依存でないことを検証する
- 完了条件
  - 多言語化対象の自動テストが通る

### Task O: 手動確認を行う

- 依存
  - Task N
- 内容
  - JA 起動で圧縮、cleanup、ZIP 展開、CSV 出力を確認する
  - UI 言語を EN に保存して再起動する
  - EN 再起動後に同じ操作を行い、ログ欄と CSV が英語になることを確認する
  - EN 保存後、再起動前の同一セッションではログ言語が即時切替しないことを確認する
- 完了条件
  - 仕様通りの言語反映タイミングと出力内容が確認できる

## 推奨実行順

1. PR1: Task A, B, C
2. PR2: Task D, E, F
3. PR3: Task G, H
4. PR4: Task I, J, K
5. PR5: Task L, M, N, O

## 並列可能な作業

- Task A と Task C は並行可能
- Task E と Task G と Task H は helper と locale キーが揃えば分担可能
- Task I と Task J は並行可能

## 検証コマンド

```powershell
pytest tests/unit/test_i18n.py tests/unit/test_app_settings.py tests/unit/test_contracts.py
pytest tests/integration/test_job_runner.py tests/integration/test_ui_controller.py
```

必要なら以下も実施する。

```powershell
pytest tests/regression/test_tkinter_regression.py -k log
```
