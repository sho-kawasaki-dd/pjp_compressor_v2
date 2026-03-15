## Plan: pytest test strategy rollout

pytest を単なる導入状態で止めず、速い unit と実ファイルを使う integration を日常運用の標準にし、重い regression は必要時に選択実行できる 3 層構成へ整理する。既存の手動回帰スクリプトと pure function 群をそのまま活かしつつ、外部ツール依存と Tkinter 依存を marker で分離して、Windows 開発環境でも回しやすい構成にする。

**Steps**
1. Phase 1: テスト土台を整備する。 [pyproject.toml](pyproject.toml) に pytest 設定を追加し、tests 配下の共通 fixture・共通 helper・marker 運用方針を定義する。ここで unit / integration / regression / slow / requires_tk / requires_external を明示し、通常実行は unit + integration、選択実行は regression に分ける。
2. Phase 1: 共通 fixture 設計を固める。 tmp_path を基礎に、画像生成、PDF 生成、ZIP 生成、CSV 出力確認、イベント収集、CapabilityReport 差し替え、subprocess モック、Tk headless 初期化の fixture を用意する。これは後続すべてのテストの前提であり、以降の工程をブロックする。
3. Phase 2: 純粋ロジックの unit test を先に広げる。 [backend/contracts.py](backend/contracts.py), [backend/capabilities.py](backend/capabilities.py), [backend/core/archive_utils.py](backend/core/archive_utils.py), [backend/core/image_utils.py](backend/core/image_utils.py), [frontend/ui_tkinter_mapper.py](frontend/ui_tkinter_mapper.py) を対象に、入力境界値、分岐、フォールバック、設定解決ロジックを高速に検証する。ここは Phase 3 と並列可能だが、fixture だけは Step 2 に依存する。
4. Phase 3: 中核 orchestration の unit / 準結合 test を作る。 [backend/orchestrator/job_runner.py](backend/orchestrator/job_runner.py) の task 構築、ZIP staging、CSV 出力、progress/stats 通知、空入力時の終了動作、mirror モード分岐を、worker 実処理をモックして検証する。ここで大量分岐の回帰点を先に押さえる。
5. Phase 4: 実ファイルを使う integration test を追加する。 [backend/core/image_utils.py](backend/core/image_utils.py) と [backend/orchestrator/job_runner.py](backend/orchestrator/job_runner.py) を軸に、JPEG/PNG 圧縮、ZIP 展開あり・なし、mirror あり・なし、CSV 出力あり・なしの代表シナリオを実行する。優先度は「圧縮結果の正しさ」なので、サイズ縮小・出力生成・入力不変・例外時の graceful handling を確認する。
6. Phase 4: PDF 系は段階的に split する。 [backend/core/pdf_utils.py](backend/core/pdf_utils.py) は pure に近い import fallback と option routing を unit 化し、PyMuPDF / pikepdf / Ghostscript を使う実圧縮は integration または requires_external 付きで分離する。常時実行では外部コマンドなしでも価値が出るよう、未導入時の失敗メッセージと fallback を先に固定する。
7. Phase 5: Tkinter の headless integration / regression を追加する。 [frontend/ui_tkinter_controller.py](frontend/ui_tkinter_controller.py) の path overlap、UI state 切替、progress event dispatch、start_compress の入力検証を pytest 化し、[scripts/tkinter_regression_check.py](scripts/tkinter_regression_check.py) の内容をベースに代表回帰シナリオを regression marker へ移植する。GUI は常時実行へ最小限の integration だけ入れ、重めの総合シナリオは regression に残す。
8. Phase 5: 回帰テストの役割を明確化する。 regression は「既知の壊れやすい代表導線」の固定に限定し、ZIP matrix、ダイアログ差し替え、thread 起動、cleanup、入力/出力重なり防止を保持する。新機能追加時はまず unit / integration を作り、過去バグや UI 配線破壊だけ regression に追加する運用ルールを定義する。
9. Phase 6: 実行プロファイルを文書化する。開発者向けに最速実行、標準実行、GUI 含む確認、外部ツール込み確認を README か開発ドキュメントへ追記し、失敗時にどの層へ追加すべきか判断できる基準を明文化する。
10. Phase 6: 導入順を最適化する。最初のマイルストーンは unit の大量追加と job_runner 周辺 integration までに留め、その後に PDF 実圧縮と Tkinter regression を追加する 2 段階導入にする。理由は、coverage を早く増やしつつ flaky 要因を後ろへ送れるため。

**Relevant files**
- c:\Users\tohbo\python_programs\pjp_compressor_v2\pyproject.toml — pytest 設定、marker、既定 testpaths の追加先。
- c:\Users\tohbo\python_programs\pjp_compressor_v2\backend\contracts.py — ProgressEvent / CapabilityReport / CompressionRequest の unit test 対象。
- c:\Users\tohbo\python_programs\pjp_compressor_v2\backend\capabilities.py — importlib / shutil.which 差し替えでの能力検出 test 対象。
- c:\Users\tohbo\python_programs\pjp_compressor_v2\backend\core\archive_utils.py — 再帰 ZIP 展開、サイクル上限、失敗ログの test 対象。
- c:\Users\tohbo\python_programs\pjp_compressor_v2\backend\core\image_utils.py — Pillow 圧縮、pngquant fallback、resize 分岐の test 対象。
- c:\Users\tohbo\python_programs\pjp_compressor_v2\backend\core\pdf_utils.py — import fallback、圧縮分岐、外部依存分離の重点対象。
- c:\Users\tohbo\python_programs\pjp_compressor_v2\backend\orchestrator\job_runner.py — 実ファイル統合シナリオとイベント駆動の主対象。
- c:\Users\tohbo\python_programs\pjp_compressor_v2\frontend\ui_tkinter_mapper.py — pure function の unit test 主対象。
- c:\Users\tohbo\python_programs\pjp_compressor_v2\frontend\ui_tkinter_controller.py — headless GUI integration の主対象。
- c:\Users\tohbo\python_programs\pjp_compressor_v2\scripts\tkinter_regression_check.py — pytest regression へ移植する基準シナリオ。

**Verification**
1. unit のみ実行して、外部依存なしで数秒以内に完走することを確認する。
2. unit + integration を標準実行し、画像圧縮、ZIP 処理、CSV 出力、イベント通知、Tk headless の最小シナリオが安定して通ることを確認する。
3. regression を選択実行し、ZIP matrix、GUI 配線、cleanup、重なり防止が既存スクリプトと同等以上に担保されることを確認する。
4. requires_external を付けた PDF / pngquant 系を依存あり環境だけで実行し、未導入環境では skip されることを確認する。
5. 新規テスト追加後、失敗時に「unit に入れるべきか integration に入れるべきか regression に残すべきか」が marker と命名規則だけで判断できる状態を確認する。

**Decisions**
- 常時実行の標準セットは unit + integration とする。
- regression は選択実行にし、重い GUI 総合シナリオと壊れやすい代表導線を保持する。
- 最優先リスクは圧縮結果の正しさと graceful failure であり、CSV や GUI はそれを支える範囲で段階導入する。
- Ghostscript と pngquant の実行確認は includes だが、日常実行の必須条件にはしない。
- service 層は薄い wrapper のため、個別網羅より core / orchestrator 側カバレッジを優先する。

**Further Considerations**
1. PDF 実圧縮の fixture は最小サンプル PDF をリポジトリ同梱する案と、テスト時に動的生成する案がある。推奨は生成ベースで、バイナリ管理を増やさない。
2. GUI regression の常時 CI 化は将来の選択肢として残すが、初期段階では flaky 回避のため regression marker に隔離するのが妥当。
3. 将来的に coverage 閾値を導入するなら、まず core と orchestrator の安定化後に段階設定するのが安全。
