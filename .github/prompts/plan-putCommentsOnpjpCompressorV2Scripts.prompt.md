## Plan: 全ソース自己文書化コメント整備

本番コードと scripts 配下の Python を対象に、日本語で what と why の両方を補う。既存の日本語 docstring 方針を踏襲しつつ、単純なラッパや自明な処理には過剰な行コメントを避け、複雑な制御・アルゴリズム・状態遷移には詳細コメントを追加する。実装はコメント密度をファイル種別ごとに分け、まず全体ルールを揃えてから高複雑度ファイル、最後に単純ファイルへ展開する。

**Steps**
1. Phase 1: コメント方針の固定化。既存の docstring と inline comment の書き方を基準に、対象ファイルを 3 つに分類する。A: 複雑ロジック中心で詳細コメントを厚く入れるファイル。B: 状態や UI 構築が中心でセクションコメント主体にするファイル。C: 単純ユーティリティや再公開ラッパでモジュール説明と最小限の補足に留めるファイル。
2. Phase 1: 変更対象一覧を確定する。含めるのは c:\Users\tohbo\python_programs\pjp_compressor_v2\compressor_launcher_tkinter.py、c:\Users\tohbo\python_programs\pjp_compressor_v2\frontend\*.py、c:\Users\tohbo\python_programs\pjp_compressor_v2\backend\*.py、c:\Users\tohbo\python_programs\pjp_compressor_v2\backend\core\*.py、c:\Users\tohbo\python_programs\pjp_compressor_v2\backend\orchestrator\*.py、c:\Users\tohbo\python_programs\pjp_compressor_v2\backend\services\*.py、c:\Users\tohbo\python_programs\pjp_compressor_v2\backend\tools\*.py、c:\Users\tohbo\python_programs\pjp_compressor_v2\shared\*.py、c:\Users\tohbo\python_programs\pjp_compressor_v2\scripts\*.py。除外するのは __pycache__、生成物、Documentation 配下、spec・ps1・toml・txt・md・html。
3. Phase 2: 高複雑度 backend から着手する。c:\Users\tohbo\python_programs\pjp_compressor_v2\backend\orchestrator\job_runner.py と c:\Users\tohbo\python_programs\pjp_compressor_v2\backend\core\pdf_utils.py に対し、処理全体の流れを示すモジュール説明、公開関数の詳細 docstring、主要ブロックごとの why/what コメントを入れる。特にタスク組み立て、ZIP 展開戦略、PDF 画像抽出、DPI 計算、画像再圧縮条件分岐、キャッシュ利用理由を明文化する。
4. Phase 2: backend の中複雑度ファイルを並列的に展開する。c:\Users\tohbo\python_programs\pjp_compressor_v2\backend\core\archive_utils.py、image_utils.py、worker_ops.py、file_ops.py、format_utils.py、compressor_utils.py、c:\Users\tohbo\python_programs\pjp_compressor_v2\backend\capabilities.py、contracts.py に対し、関数単位の docstring 拡充と必要箇所の処理ブロックコメントを追加する。*parallel with step 5*
5. Phase 2: backend の薄いサービス層とツール層を整える。c:\Users\tohbo\python_programs\pjp_compressor_v2\backend\services\archive_service.py、cleanup_service.py、image_service.py、pdf_service.py、c:\Users\tohbo\python_programs\pjp_compressor_v2\backend\tools\mp3_to_wav.py は、再公開の意図や利用文脈が分かる短いモジュール docstring と必要最低限の関数説明に留める。*parallel with step 4*
6. Phase 3: frontend のエントリと契約面を先に整備する。c:\Users\tohbo\python_programs\pjp_compressor_v2\compressor_launcher_tkinter.py、c:\Users\tohbo\python_programs\pjp_compressor_v2\frontend\bootstrap.py、ui_contracts.py、ui_tkinter_mapper.py に対し、起動フロー、エラー処理、Protocol の責務、UI 状態から CompressionRequest への変換規則を詳細化する。これは後続の UI 本体コメントの基準になる。*depends on 1*
7. Phase 3: frontend の状態・制御・表示を役割別に整備する。c:\Users\tohbo\python_programs\pjp_compressor_v2\frontend\ui_tkinter_state.py では状態変数をセクション見出し付きで整理し、変数群の役割を説明する。c:\Users\tohbo\python_programs\pjp_compressor_v2\frontend\ui_tkinter_controller.py ではイベント起点、バックグラウンド処理、UI スレッド復帰、検証処理の流れをコメント化する。c:\Users\tohbo\python_programs\pjp_compressor_v2\frontend\ui_tkinter_view.py ではレイアウト構築をセクション単位で説明し、細かな widget 生成自体の逐一説明は避ける。c:\Users\tohbo\python_programs\pjp_compressor_v2\frontend\ui_tkinter.py と sound_utils.py はアプリ統合と補助機能の文脈説明を中心にする。*depends on 6*
8. Phase 4: shared と scripts を整備する。c:\Users\tohbo\python_programs\pjp_compressor_v2\shared\configs.py は既存コメントを維持しつつ、設定群の意味が不明瞭な箇所だけ補う。c:\Users\tohbo\python_programs\pjp_compressor_v2\scripts\tkinter_regression_check.py には、fixture 生成意図、ZIP ケース設計、検証観点、スレッド連携の流れを詳しく説明する。*depends on 1*
9. Phase 5: 用語と文体を全体で統一する。コメント言語は日本語に統一し、冗長な逐語説明やコードの単純言い換えを削る。公開 API は docstring、複雑分岐はブロックコメント、単純代入や自明な処理にはコメントなし、という基準で見直す。*depends on 3, 4, 5, 7, 8*
10. Phase 5: コメント追加に伴う副作用を検証する。未閉じ三連引用符、インデント崩れ、文字エンコーディング問題がないかを確認し、Python ファイル全体の構文チェックと必要な回帰確認を実施する。*depends on 9*

**Relevant files**
- c:\Users\tohbo\python_programs\pjp_compressor_v2\compressor_launcher_tkinter.py - 起動エントリ、クラッシュログ、初期化失敗時の責務説明を追加
- c:\Users\tohbo\python_programs\pjp_compressor_v2\frontend\bootstrap.py - スプラッシュ表示と本体初期化の順序、表示時間制約の理由を補足
- c:\Users\tohbo\python_programs\pjp_compressor_v2\frontend\ui_contracts.py - Protocol ごとの責務境界を明示
- c:\Users\tohbo\python_programs\pjp_compressor_v2\frontend\ui_tkinter_mapper.py - UI 値から backend request へ変換する規則を説明
- c:\Users\tohbo\python_programs\pjp_compressor_v2\frontend\ui_tkinter_state.py - Tk 変数群を用途別に見出し化
- c:\Users\tohbo\python_programs\pjp_compressor_v2\frontend\ui_tkinter_controller.py - イベント駆動、検証、ワーカースレッド連携の流れを整理
- c:\Users\tohbo\python_programs\pjp_compressor_v2\frontend\ui_tkinter_view.py - レイアウトのセクション構造と各 UI ブロックの役割を説明
- c:\Users\tohbo\python_programs\pjp_compressor_v2\frontend\ui_tkinter.py - App 統合クラス、終了処理、アイコン設定の文脈を補足
- c:\Users\tohbo\python_programs\pjp_compressor_v2\frontend\sound_utils.py - 任意依存としての音再生処理の役割を最小限説明
- c:\Users\tohbo\python_programs\pjp_compressor_v2\backend\contracts.py - データ契約、イベント種別、互換用変換の意図を明確化
- c:\Users\tohbo\python_programs\pjp_compressor_v2\backend\capabilities.py - 外部依存検出の方針とフォールバックを説明
- c:\Users\tohbo\python_programs\pjp_compressor_v2\backend\orchestrator\job_runner.py - 圧縮ジョブ全体の実行順序、タスク生成、ZIP モード処理、集計更新を重点説明
- c:\Users\tohbo\python_programs\pjp_compressor_v2\backend\core\pdf_utils.py - PDF 圧縮アルゴリズムの中心。最重要コメント対象
- c:\Users\tohbo\python_programs\pjp_compressor_v2\backend\core\archive_utils.py - 再帰展開、循環防止、ZIP 再構築の理由を説明
- c:\Users\tohbo\python_programs\pjp_compressor_v2\backend\core\image_utils.py - 画像圧縮方針、変換条件、品質設定を説明
- c:\Users\tohbo\python_programs\pjp_compressor_v2\backend\core\worker_ops.py - 拡張子ベース分岐と単一ファイル処理フローを説明
- c:\Users\tohbo\python_programs\pjp_compressor_v2\backend\core\file_ops.py - 集計・削除ロジックは簡潔な docstring 中心
- c:\Users\tohbo\python_programs\pjp_compressor_v2\backend\core\format_utils.py - 軽量ユーティリティとして簡潔維持
- c:\Users\tohbo\python_programs\pjp_compressor_v2\backend\core\compressor_utils.py - 互換 API と新 orchestrator の橋渡しを説明
- c:\Users\tohbo\python_programs\pjp_compressor_v2\backend\services\archive_service.py - thin wrapper の意図だけ明示
- c:\Users\tohbo\python_programs\pjp_compressor_v2\backend\services\cleanup_service.py - thin wrapper の意図だけ明示
- c:\Users\tohbo\python_programs\pjp_compressor_v2\backend\services\image_service.py - thin wrapper の意図だけ明示
- c:\Users\tohbo\python_programs\pjp_compressor_v2\backend\services\pdf_service.py - thin wrapper の意図だけ明示
- c:\Users\tohbo\python_programs\pjp_compressor_v2\backend\tools\mp3_to_wav.py - 単機能 CLI の用途説明のみ
- c:\Users\tohbo\python_programs\pjp_compressor_v2\shared\configs.py - 設定値の意図が不明な箇所のみ補足
- c:\Users\tohbo\python_programs\pjp_compressor_v2\scripts\tkinter_regression_check.py - fixture 設計、回帰観点、実行補助のコメントを追加

**Verification**
1. 変更後に対象 Python 全ファイルの構文チェックを実施する。少なくとも python -m compileall 相当で docstring 追加による構文崩れを検知する。
2. 主要起動経路として compressor_launcher_tkinter.py の起動確認、または import ベースの軽量確認を行い、コメント追加による副作用がないことを確認する。
3. scripts\tkinter_regression_check.py が既存の回帰確認入口として使えるなら、その実行条件を確認し、実行可能な範囲で回帰確認する。
4. レビュー観点として、コメントがコードの逐語説明に終始していないか、複雑箇所で why が補えているか、日本語用語が全体で統一されているかを確認する。
5. UI レイアウト系ファイルでは、コメント量で可読性を落としていないかを重点確認する。

**Decisions**
- 対象範囲は本番コードと scripts 配下の Python ファイルを含む。
- コメント言語は日本語に統一する。
- コメント方針は what と why の両方を含むが、単純処理の逐語説明は避ける。
- Documentation 配下や非 Python ファイルは今回の対象外。
- 薄いラッパや __init__.py は詳細行コメントではなく役割説明中心にする。

**Further Considerations**
1. フロントエンドの view 系は行コメントを増やしすぎると視認性が落ちるため、メソッド内はセクション見出し中心に留めるのが推奨。
2. pdf_utils.py と job_runner.py は保守価値が高いため、ここだけは他ファイルより明確に厚いコメント密度を許容する。
3. 将来の保守を考えると、コメント追従が必要な複雑箇所は docstring とブロックコメントの役割を分けておくと更新しやすい。
