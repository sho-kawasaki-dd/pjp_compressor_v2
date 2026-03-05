## Plan: Pathlib全面統一リファクタリング

アプリ全体のパス解決・パス操作を`os.path`/`os`依存から`pathlib.Path`中心へ統一し、設定定数も`Path`に揃える。外部API境界（Tkinter変数、subprocess引数など）だけ`str(...)`へ明示変換して互換性を保つ。まず低リスク層（設定・ユーティリティ）から移行し、次にバックエンド処理、最後にUI/起動系を移行して回帰を抑える。

**Steps**
1. Phase 1: 基盤方針と共通ルールの適用
2. `Path`型をプロジェクト内の標準パス型として採用し、関数I/Oの境界ルールを確定する: 内部は`Path`、外部ライブラリ/GUI境界で`str`化。
3. 既存`os.path`置換ルールを定義する: `join`→`/`、`exists`→`.exists()`、`basename`→`.name`、`splitext`→`.suffix/.stem`、`relpath`→`.relative_to()`、`abspath`→`.resolve()`。
4. `Path`型で比較不能なケース（`commonpath`相当）については`resolve()`後に`parents`を使う共通比較ヘルパー方針を確定する。
5. Phase 2: 設定・起動周りの移行（低〜中リスク、後続依存あり）
6. `shared/configs.py`のディレクトリ定数を`Path`型へ変更し、`APP_BASE_DIR`・`APP_DEFAULT_INPUT_DIR`・`APP_DEFAULT_OUTPUT_DIR`・`SOUNDS_DIR`・`IMAGES_DIR`を`Path`で定義する。`_runtime_base_dir()`も`Path`返却へ統一。*blocks step 9-16*
7. `frontend/sound_utils.py`の`resource_path()`を`Path`ベースへ移行し、音声ロード直前で必要なら`str`化する。
8. `frontend/bootstrap.py`の画像/音声参照を`Path`結合へ移行する。
9. Phase 3: バックエンド core/tools の包括移行（並列実行可）
10. `backend/core/file_ops.py`を`Path.rglob()`/`iterdir()`中心に再構成し、削除・空ディレクトリ整理・ログ用相対パス生成を`Path`で実装する。
11. `backend/core/archive_utils.py`のZIP探索/重複防止/相対パス計算を`Path`へ移行する。
12. `backend/core/pdf_utils.py`と`backend/core/image_utils.py`の`basename/exists/getsize/remove`を`Path`化し、`subprocess.run`のコマンド引数のみ`str`へ明示変換する。
13. `backend/core/worker_ops.py`の入出力パス処理（親ディレクトリ生成、サイズ取得、ログ名抽出）を`Path`へ移行する。
14. `backend/tools/mp3_to_wav.py`を`Path.iterdir()`と`.stem/.suffix`で書き換える。
15. Phase 4: オーケストレータ/UI層の移行（中〜高リスク）
16. `backend/orchestrator/job_runner.py`の再帰走査・相対パス維持・CSV出力先生成を`Path`ベースへ移行し、タスク投入時の型を`Path`に寄せる。
17. `frontend/ui_tkinter_controller.py`のD&D入力判定・出力ディレクトリ検証・警告音パス結合を`Path`化し、`_paths_overlap`を`resolve()+parents`ロジックに置換する。
18. `frontend/ui_tkinter.py`のDesktop解決を`Path.home()/"Desktop"`へ統一し、初期フォルダ生成・アイコン参照・デフォルトディレクトリ作成を`Path`化する。
19. `compressor_launcher_tkinter.py`は既に`Path`中心のため、型整合性（設定値受け渡し）だけ確認する。*parallel with step 16-18*
20. Phase 5: 互換層調整と最終整形
21. Tkinter変数やメッセージ表示に渡す箇所を点検し、必要な箇所で`str(path)`を明示化する。
22. `import os`の不要化を各ファイルで行い、`os.path`参照がゼロであることを確認する。
23. Phase 6: 検証
24. 静的検証: `os.path`/`os.walk`/`os.listdir`/`os.makedirs`などの残存をgrepで確認し、Path化漏れを検出する。
25. 回帰検証: 画像/PDF/ZIPを含む通常圧縮フロー、非対応ファイル処理、ログCSV出力、一時ファイル削除を実行確認する。
26. UI検証: 起動時スプラッシュ・サウンド再生・D&D入力・初期フォルダ作成（Desktop配下、日本語フォルダ名）を確認する。
27. 外部コマンド検証: Ghostscript/pngquant実行時の引数パスが正しく機能することを確認する。

**Relevant files**
- `c:\Users\tohbo\python_programs\pjp_compressor_v2\shared\configs.py` — 設定定数とランタイム基準パスを`Path`へ統一
- `c:\Users\tohbo\python_programs\pjp_compressor_v2\frontend\sound_utils.py` — `resource_path()`と再生前存在確認を`Path`化
- `c:\Users\tohbo\python_programs\pjp_compressor_v2\frontend\bootstrap.py` — スプラッシュ/起動音パス構築を`Path`化
- `c:\Users\tohbo\python_programs\pjp_compressor_v2\frontend\ui_tkinter.py` — Desktop初期化、アイコン参照、既定ディレクトリ作成を`Path`化
- `c:\Users\tohbo\python_programs\pjp_compressor_v2\frontend\ui_tkinter_controller.py` — D&D判定、重複判定、警告音パスを`Path`化
- `c:\Users\tohbo\python_programs\pjp_compressor_v2\backend\orchestrator\job_runner.py` — 探索・相対パス・CSV出力パスの`Path`化
- `c:\Users\tohbo\python_programs\pjp_compressor_v2\backend\core\file_ops.py` — 再帰探索/削除処理の`Path`化
- `c:\Users\tohbo\python_programs\pjp_compressor_v2\backend\core\archive_utils.py` — ZIP探索と相対表示の`Path`化
- `c:\Users\tohbo\python_programs\pjp_compressor_v2\backend\core\pdf_utils.py` — PDF処理メッセージ/存在確認/サイズ取得/一時削除の`Path`化
- `c:\Users\tohbo\python_programs\pjp_compressor_v2\backend\core\image_utils.py` — 画像処理とpngquant連携部の`Path`化
- `c:\Users\tohbo\python_programs\pjp_compressor_v2\backend\core\worker_ops.py` — 単一ファイル処理の入出力パス操作を`Path`化
- `c:\Users\tohbo\python_programs\pjp_compressor_v2\backend\tools\mp3_to_wav.py` — MP3走査/出力名生成を`Path`化
- `c:\Users\tohbo\python_programs\pjp_compressor_v2\compressor_launcher_tkinter.py` — 既存`Path`実装との整合確認

**Verification**
1. `rg "os\.path\.|os\.walk\(|os\.listdir\(|os\.makedirs\(|os\.remove\(|os\.rmdir\(" -g "**/*.py"`で残存箇所を確認（対象外の`os.environ`/`os.name`は許容判断を記録）。
2. アプリ起動後、既定フォルダの自動作成とスプラッシュ表示、通知音再生を確認。
3. D&Dでフォルダ入力/ファイル入力それぞれを試し、入力・出力重複判定が正しく動くことを確認。
4. PDF圧縮（PyMuPDF/pikepdf/Ghostscript）、PNG圧縮（pngquant）、通常画像圧縮（Pillow）を実行し、出力生成とログ文言を確認。
5. ZIP含む入力で展開→圧縮→CSVログの出力相対パスが従来どおりであることを確認。
6. 日本語パス（`これから圧縮`、`圧縮済みファイル`）を含むケースで失敗しないことを確認。

**Decisions**
- `shared/configs.py`の定数は`str`維持ではなく`Path`へ全面統一する。
- `os.path`のみではなく、パス操作系`os` API（`walk/listdir/makedirs/remove/rmdir`）も可能な限り`Path`メソッドへ包括置換する。
- ただし外部API境界（Tkinter変数、subprocess引数、必要なライブラリ呼び出し）では`str(path)`へ変換して互換性を担保する。
- 今回の主目的はパス処理統一であり、圧縮アルゴリズム自体の仕様変更は含めない。

**Further Considerations**
1. `Path`型を公開定数にしたことで、既存の文字列連結（`+`）が潜在的に残る場合はビルド時に型エラーでなく実行時エラーになるため、重点点検対象にする。
2. `relative_to()`は祖先関係にないと例外化するため、従来`relpath`で許容していたケースがないか境界テストを追加する。
3. 必要なら段階導入として、Phase 2-3完了時に一度回帰テストを実施し、Phase 4投入前に不具合を早期収束させる。
