このリポジトリで、shared/configs.py に混在している設定を責務ごとに分離し、保存場所を整理してください。目的は、shared を本当に共通な境界だけに絞り、frontend 固有・backend 固有・runtime 固有の設定をそれぞれ適切な場所へ移すことです。また、純粋な定数データは JSON ファイルへ外出ししてください。

前提:
- Windows 環境です。
- 現在の主要境界は backend/contracts.py の CompressionRequest と frontend/ui_tkinter_mapper.py の request 組み立てです。
- 既存の挙動は原則維持してください。特に Tkinter UI の初期値、PDF 圧縮の既定値、PyInstaller でのリソース参照、Desktop 既定フォルダの扱いを壊さないこと。

やってほしいこと:
1. shared/configs.py の値を分類し、frontend 所有、backend 所有、runtime/packaging 所有、JSON 化候補に分ける。
2. runtime/packaging 用の Python モジュールを用意し、APP_BASE_DIR / RESOURCE_BASE_DIR 相当のパス解決をそこへ移す。
3. backend 用 settings を用意し、PDF 圧縮既定値や Ghostscript 既定値を移す。
4. frontend 用 settings を用意し、UI 初期値、cleanup 対象拡張子、表示ラベル、長辺プリセット、画像/音声リソース参照を移す。
5. 純粋データだけを JSON 化する。候補は PDF モード表示名、Ghostscript プリセット表示名、長辺プリセット一覧。必要ならローダ関数を Python 側に置き、型と内容を検証する。
6. backend が UI 表示用データに依存しないようにする。たとえば PDF_COMPRESS_MODES は backend 側では allowed values の検証へ置き換える。
7. 既存 import を安全に置き換える。必要なら shared/configs.py に一時的な互換レイヤを残してもよいが、最終的に責務が明確になるようにする。
8. 関連テストを更新または追加し、起動確認と既存テストで回帰がないことを確認する。

制約:
- root cause を直す。単なる import の付け替えだけで終わらせない。
- 不要な大規模設計変更はしない。現行アーキテクチャの延長で整理する。
- Python の runtime ロジックは JSON に入れない。
- Path や OS 依存や PyInstaller 依存の値は Python モジュール側に残す。
- JSON は読みっぱなしにせず、ローダで妥当性を担保する。
- コメントや命名は既存スタイルに合わせる。

特に確認してほしいコード:
- shared/configs.py
- backend/contracts.py
- frontend/ui_tkinter_mapper.py
- frontend/ui_tkinter.py
- frontend/bootstrap.py
- frontend/ui_tkinter_state.py
- frontend/ui_tkinter_view.py
- frontend/ui_tkinter_controller.py
- backend/core/pdf_utils.py
- backend/orchestrator/job_runner.py
- backend/core/compressor_utils.py

完了条件:
- 設定の責務境界がコード上で説明可能になっている。
- shared/configs.py への依存が大幅に減るか、明確な互換用途だけになる。
- JSON 化対象が妥当で、runtime ロジックが混ざっていない。
- 既存機能の挙動が維持され、テストまたは起動確認で検証されている。

最終報告では次を簡潔にまとめてください:
- どう分離したか
- なぜその配置にしたか
- JSON 化したものと JSON 化しなかったもの
- 互換レイヤが残る場合は、その理由と今後の撤去条件
- 実行したテストと未確認事項
