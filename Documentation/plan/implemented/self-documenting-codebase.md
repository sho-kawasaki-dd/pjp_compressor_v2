## Plan: Repo Self-Documentation Pass

コードベース全体を対象に、日本語を基本とした Why 重視の docstring と selective な inline コメントを追加する。既存の日本語記述スタイルと責務分割を保ちつつ、まず理解負荷の高い backend/orchestrator・frontend controller/view・test fixtures/regression から説明を厚くし、その後に薄いラッパー層と残りのテストへ一貫した説明を広げる。実装時は挙動変更を避け、コメント過多で可読性を落とさないことを明示的な境界とする。

**Phase 1 Output: Documentation Policy And Inventory**

Phase 1 は実装ではなく、後続フェーズで迷わないための判断基準と対象棚卸しを固定する段階として扱う。ここで決めるのは「何を書くか」よりも「どこまで書くか」「どこを優先するか」であり、コメント追加の粒度が途中でぶれないようにする。

**Documentation Policy**

- module docstring: そのモジュールが責務として持つ範囲、持たない範囲、他レイヤとの接点を 3-6 行で説明する
- public function or method docstring: What に加えて Why と主要な前提条件を書く。引数の逐語説明ではなく、呼び出し側が誤解しやすい制約を優先する
- internal helper docstring: 処理名だけで意図が伝わる場合は省略可。暗黙ルール、フォールバック、フォーマット変換、外部依存の都合があるものに限定して書く
- inline comment: 分岐理由、フォールバック理由、スレッド安全性、フォーマット規約、セキュリティ上の意図、回帰テストの守備範囲だけに使う
- test documentation: テスト名が十分に説明的な場合は関数ごとの docstring を強制しない。fixture、Dummy オブジェクト、境界値、複数条件マトリクス、セキュリティ回帰に重点を置く
- avoid: コードの逐語訳、代入や if 文の自明な説明、実装詳細の重複、コメントを読まないとコード変更できなくなる過剰な長文化

**Phase 1 Inventory**

1. Tier A: 先に説明しないと後続変更が危険な領域
   - backend/core/pdf_utils.py: PDF 非可逆圧縮、soft mask 再構成、pngquant/Pillow フォールバック、外部プロセス失敗時の退避戦略
   - backend/orchestrator/job_runner.py: ZIP 一時作業領域、task 生成、CSV の zip::path 規約、ミラー圧縮、進捗通知の責務分担
   - frontend/ui_tkinter_controller.py: メインスレッド制約、イベント駆動、engine/mode ごとの widget state machine、入出力重なりガード
   - tests/conftest.py: fixture 契約、factory デフォルト値、Tk 回帰用 monkeypatch の理由

2. Tier B: Tier A を読んだ後に理解を接続する中核領域
   - backend/core/image_utils.py: 品質値の正規化、resize mode 切替、pngquant quality 範囲の決め方
   - backend/core/worker_ops.py: worker task tuple の意味、拡張子別ディスパッチの境界
   - frontend/ui_tkinter_view.py: scroll container、mouse wheel、pack/forget ベースの見た目制御、コールバック補助の役割
   - frontend/ui_tkinter_mapper.py: UI 値の clamp/normalize と request 変換ルール
   - tests/integration/test_job_runner.py: DummyVar、DummyMapperApp、極端値の意図
   - tests/regression/test_tkinter_regression.py: ZIP 行列ケース、UI 回帰の守備範囲

3. Tier C: 境界整理と用語統一が主目的の補完領域
   - backend/contracts.py, backend/capabilities.py, backend/settings.py
   - backend/core/archive_utils.py, backend/core/file_ops.py, backend/core/format_utils.py, backend/core/compressor_utils.py
   - backend/services/\*.py, backend/tools/mp3_to_wav.py
   - frontend/ui_tkinter.py, frontend/bootstrap.py, frontend/settings.py, frontend/sound_utils.py, frontend/ui_tkinter_state.py, frontend/ui_contracts.py
   - tests/integration/test*ui_controller.py, tests/unit/test*\*.py

**Phase 1 Decisions Applied To This Repo**

- コメント言語は日本語を基本とし、API 名や外部ツール名などコード上の固有名詞だけ英語を残す
- backend は「入力不変」「フォールバック」「構造最適化」「外部依存の劣化運転」をキーワードに説明を揃える
- frontend は「メインスレッド」「表示状態の同期」「ユーザーが誤操作しても危険状態へ進ませない理由」を優先して説明する
- tests は「どの不具合を再発防止しているか」が一目で分かる説明を優先し、単純ケースでは説明を増やしすぎない
- 既存 docstring が十分な場所は書き直しではなく補強に留め、既存の責務分割を崩さない

**Phase 1 Exit Criteria**

- 以降のフェーズで追加する docstring と inline comment の粒度が判断できること
- 優先度付き対象一覧があり、どのファイルから手を付けるべきか合意できること
- 複雑ロジックの Why が不足している箇所を backend/frontend/tests それぞれで特定できていること
- 過剰コメントを避ける明示的なルールがあり、レビュー時の削除基準が共有できていること

**Steps**

1. Phase 1: Documentation policy and inventory. 対象シンボルの粒度を固定する。モジュール docstring は責務と境界、公開関数/メソッド docstring は What+Why+主要な前提、inline コメントは分岐理由・フォールバック理由・スレッド安全性・テスト意図のみに限定する。この方針が以降の全ステップをブロックする。
2. Phase 2: Backend high-complexity pass. d:/programming/py_apps/pjp_compressor_v2/backend/core/pdf_utils.py、d:/programming/py_apps/pjp_compressor_v2/backend/orchestrator/job_runner.py、d:/programming/py_apps/pjp_compressor_v2/backend/core/image_utils.py、d:/programming/py_apps/pjp_compressor_v2/backend/core/worker_ops.py を優先し、複雑な制御フローに Why コメントを追加する。特に PDF soft mask 再構成、pngquant/Pillow フォールバック、ZIP 一時作業領域、CSV の zip::path 規約、worker task 構造、ミラー圧縮の意図を明文化する。depends on 1。
3. Phase 3: Backend remaining source sweep. d:/programming/py_apps/pjp_compressor_v2/backend/contracts.py、capabilities.py、settings.py、core/archive_utils.py、core/file_ops.py、core/format_utils.py、core/compressor_utils.py、services/\*.py、tools/mp3_to_wav.py を対象に、境界説明と既存 docstring の補強を行う。薄い再エクスポート層は冗長なコメントを避け、なぜ層が存在するのかに限定して記述する。parallel with 4 after 1。
4. Phase 4: Frontend architecture pass. d:/programming/py_apps/pjp_compressor_v2/frontend/ui_tkinter_controller.py、ui_tkinter_view.py、ui_tkinter.py、bootstrap.py、settings.py、sound_utils.py、ui_tkinter_state.py、ui_tkinter_mapper.py、ui_contracts.py を対象に、メインスレッド制約、イベントから backend request への流れ、engine/mode による widget state machine、D&D 正規化、入出力衝突ガード、設定永続化の理由を docstring と inline コメントで補う。callback 群はイベント種別と副作用を明記する。depends on 1, parallel with 3。
5. Phase 5: Test explainability pass. d:/programming/py*apps/pjp_compressor_v2/tests/conftest.py、integration/test_job_runner.py、integration/test_ui_controller.py、regression/test_tkinter_regression.py、unit 以下の各 test*\*.py を対象に、fixture の契約と default 値の理由、Dummy オブジェクトの目的、境界値の意味、セキュリティ回帰や ZIP 行列テストが守る仕様を明文化する。単純な 1 assertion テストは過剰説明を避け、module header と複雑テスト前の短い Why コメントで補う。depends on 1, parallel with 3 and 4。
6. Phase 6: Consistency sweep. 全ファイルを横断して用語統一を行い、同じ概念に複数表現がないか確認する。重点用語は「可逆/非可逆」「フォールバック」「ミラー圧縮」「一時作業領域」「メインスレッド」「入力不変」「回帰防止」。docstring が implementation details を重複説明していないか、コメントがコードの逐語訳になっていないかを削る。depends on 2, 3, 4, 5。
7. Phase 7: Verification. 代表的な複雑ファイルを目視確認し、pytest の非 Tk スイートと Tk 回帰スイートを分けて実行して、コメント追加による構文崩れや import 破壊がないことを確認する。depends on 6。

**Relevant files**

- d:/programming/py_apps/pjp_compressor_v2/backend/core/pdf_utils.py — PDF 非可逆圧縮、soft mask、pngquant/Pillow フォールバックの Why を最優先で補う
- d:/programming/py_apps/pjp_compressor_v2/backend/orchestrator/job_runner.py — ZIP 一時作業領域、task 生成、CSV 規約、ミラー圧縮、進捗通知の全体意図を補う
- d:/programming/py_apps/pjp_compressor_v2/backend/core/image_utils.py — 品質値正規化、resize 分岐、pngquant quality 範囲の理由を明記する
- d:/programming/py_apps/pjp_compressor_v2/backend/core/worker_ops.py — worker task schema と拡張子別ディスパッチの意図を説明する
- d:/programming/py_apps/pjp_compressor_v2/backend/contracts.py — 既存スタイルの基準として維持しつつ境界説明を参照する
- d:/programming/py_apps/pjp_compressor_v2/frontend/ui_tkinter_controller.py — メインスレッド安全性、イベント処理、パス検証の Why を補う
- d:/programming/py_apps/pjp_compressor_v2/frontend/ui_tkinter_view.py — scroll container、mouse wheel、widget packing、callback 群の理由を補う
- d:/programming/py_apps/pjp_compressor_v2/frontend/ui_tkinter.py — App 初期化順序と副作用の理由を説明する
- d:/programming/py_apps/pjp_compressor_v2/frontend/ui_tkinter_mapper.py — UI 値の clamp/normalize と request 変換ルールの意図を補強する
- d:/programming/py_apps/pjp_compressor_v2/tests/conftest.py — fixture 契約、デフォルト値、monkeypatch の目的を明記する
- d:/programming/py_apps/pjp_compressor_v2/tests/integration/test_job_runner.py — Dummy オブジェクトと境界値の意図を説明する
- d:/programming/py_apps/pjp_compressor_v2/tests/regression/test_tkinter_regression.py — ZIP 行列ケースと UI 回帰シナリオの守備範囲を説明する
- d:/programming/py_apps/pjp_compressor_v2/Documentation/README.md — 必要であれば documentation policy を短く追記し、コード内説明との整合性だけ確認する

**Verification**

1. python -m pytest tests/unit tests/integration -m "not requires_external and not requires_tk"
2. Tk 実行環境がある端末で python -m pytest tests/regression -m "regression and requires_tk"
3. 代表確認として backend/core/pdf_utils.py、backend/orchestrator/job_runner.py、frontend/ui_tkinter_controller.py、tests/conftest.py を目視し、Why がコードを読まずに追えるか確認する
4. grep/検索で TODO や英日表記ゆれを洗い、コメント追加時に古い説明と矛盾していないか確認する

**Decisions**

- 対象範囲はテストを含む全コードベース一括
- 追加言語は日本語を基本とする
- 目的は自己文書化であり、挙動変更・リファクタリング・命名変更は含めない
- 単純なコードには過剰な inline コメントを付けず、複雑分岐・暗黙ルール・回帰意図に絞る
- 既存の module-level docstring が十分な箇所は補強のみに留め、説明の重複を避ける

**Further Considerations**

1. 実装時は大きな一括編集よりも backend/frontend/tests の 3 まとまりでレビュー可能な差分に分けると確認しやすい
2. worker task tuple のように説明しづらい構造があるが、この依頼では原則としてコメントで補い、構造変更は別タスクに分離する
3. テスト名は比較的良好なので、各テスト関数へ一律 docstring を付けるより fixture と複雑シナリオへ重点投下する方が効果が高い
