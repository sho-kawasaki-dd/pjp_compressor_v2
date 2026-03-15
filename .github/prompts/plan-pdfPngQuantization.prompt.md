## Plan: PDF PNG Quantization

PDF のネイティブ非可逆圧縮で、PNG 系画像は常に PNG のまま処理し、pngquant が使える環境では量子化、使えない環境では Pillow の 256 色固定減色へフォールバックする。これに合わせて `pdf_png_to_jpeg` をデータモデルごと削除し、GUI には PDF 用 PNG 品質スライダーと、pngquant 未検出時の無効化注記を追加する。あわせて、今回の改修コードには自己文書として読める詳細なコメントを付し、分岐意図・フォールバック条件・UI 有効/無効の理由がコード上から追える状態にする。

**Steps**
1. Phase 1: request/worker 配線を更新する。`backend/settings.py` に PDF 用 PNG 品質の既定値を追加し、`backend/contracts.py` の `CompressionRequest` と `to_legacy_kwargs()`、`frontend/ui_tkinter_mapper.py`、`backend/orchestrator/job_runner.py`、`backend/core/worker_ops.py` から `pdf_png_to_jpeg` を除去して `pdf_png_quality` を通す。これが backend/UI 実装の前提になる。
2. Phase 2: PDF 非可逆圧縮の PNG 処理を差し替える。`backend/core/pdf_utils.py` で PNG/BMP/TIFF/GIF など PNG 系として扱う経路を独立させ、JPEG 系は従来どおり JPEG 品質で再圧縮、PNG 系は一時ファイルまたはバイト列経由で pngquant を実行して減色する。品質レンジは既存 PNG 圧縮と同様に slider 値を上限、`max(0, quality-20)` を下限にする案を第一候補とする。
3. Phase 2: pngquant 不可時のフォールバックを `backend/core/pdf_utils.py` に実装する。Pillow の `Image.quantize(colors=256)` を使って 256 色固定 PNG を生成し、PDF 用 PNG 品質スライダー値は無視する。結果メッセージと debug 出力では、`pngquant` 利用か `Pillow 256-color fallback` かを識別できるようにする。
4. Phase 2: `backend/core/pdf_utils.py` の関数シグネチャを更新する。`compress_pdf_lossy()` と `compress_pdf_native()` から `png_to_jpeg` を削除し、`png_quality` を受ける形へ統一する。`both` モードや lossless fallback でも新パラメータを通す。
5. Phase 3: Tkinter state/protocol/view/controller を更新する。`frontend/ui_tkinter_state.py` と `frontend/ui_contracts.py` に `pdf_png_quality` を追加し、`frontend/ui_tkinter_view.py` では native lossy セクションの `PNG → JPEG 変換` checkbox を削除して PDF 用 PNG 品質スライダーと注記ラベルへ置き換える。
6. Phase 3: PDF 用 PNG スライダーの有効/無効制御を整理する。`frontend/ui_tkinter_controller.py` の `_update_pdf_controls()` は現在 `_native_lossy_widgets` を mode ベースで一括制御しているため、PDF 用 PNG スライダーだけ capability ベースで止められるよう、専用 widget 群または専用 helper を追加する。条件は `native` エンジンかつ `lossy/both` モードかつ `capabilities.pngquant_available` のときのみ有効、それ以外は無効。pngquant 未検出時は `Pillow 256 色固定減色のため PNG 品質は無効` という注記を表示する。
7. Phase 4: テストを更新する。`tests/unit/test_contracts.py`、`tests/unit/test_ui_tkinter_mapper.py`、`tests/integration/test_job_runner.py`、`tests/integration/test_ui_controller.py` の request/host/dummy を `pdf_png_quality` ベースへ置換し、`tests/unit/test_pdf_utils.py` には少なくとも `pngquant` 使用時と Pillow fallback 時の 2 ケースを追加する。前者は subprocess または helper 呼び出しの品質レンジと `replace_image()` 実行を、後者は 256 色固定でスライダー値非依存なことを確認する。
8. Phase 5: 回帰確認を行う。unit/integration の関連テストを優先実行し、GUI では native PDF lossy/both の切替、pngquant 有無でのスライダー活性状態、注記表示、既存 JPEG 品質表示の文言変更有無を確認する。

**Relevant files**
- `c:\Users\tohbo\python_programs\pjp_compressor_v2\backend\settings.py` — `PDF_LOSSY_*` 定数群に PDF 用 PNG 品質既定値を追加する。
- `c:\Users\tohbo\python_programs\pjp_compressor_v2\backend\contracts.py` — `CompressionRequest` と `to_legacy_kwargs()` を `pdf_png_quality` へ移行する。
- `c:\Users\tohbo\python_programs\pjp_compressor_v2\backend\orchestrator\job_runner.py` — worker task tuple と `run_compression_job()` の引数既定値を更新する。
- `c:\Users\tohbo\python_programs\pjp_compressor_v2\backend\core\worker_ops.py` — PDF 処理分岐の引数展開を `pdf_png_quality` に差し替える。
- `c:\Users\tohbo\python_programs\pjp_compressor_v2\backend\core\pdf_utils.py` — PNG 系 PDF 画像の pngquant 量子化と Pillow fallback を実装する本体。
- `c:\Users\tohbo\python_programs\pjp_compressor_v2\backend\capabilities.py` — 新規検出項目は不要だが、既存 `pngquant_available` を PDF UI 制御で再利用する前提を確認対象とする。
- `c:\Users\tohbo\python_programs\pjp_compressor_v2\frontend\ui_tkinter_state.py` — `pdf_png_quality` の Tk 変数を追加する。
- `c:\Users\tohbo\python_programs\pjp_compressor_v2\frontend\ui_contracts.py` — mapper/controller が参照する Protocol を更新する。
- `c:\Users\tohbo\python_programs\pjp_compressor_v2\frontend\ui_tkinter_mapper.py` — UI state から `CompressionRequest` へ `pdf_png_quality` を流す。
- `c:\Users\tohbo\python_programs\pjp_compressor_v2\frontend\ui_tkinter_view.py` — PDF native lossy セクションの widget 構成を差し替える。
- `c:\Users\tohbo\python_programs\pjp_compressor_v2\frontend\ui_tkinter_controller.py` — PDF widget の mode/capability 連動を調整する。
- `c:\Users\tohbo\python_programs\pjp_compressor_v2\tests\unit\test_pdf_utils.py` — PNG 系 PDF 画像の新ロジックを検証する。
- `c:\Users\tohbo\python_programs\pjp_compressor_v2\tests\unit\test_contracts.py` — legacy kwargs の更新を検証する。
- `c:\Users\tohbo\python_programs\pjp_compressor_v2\tests\unit\test_ui_tkinter_mapper.py` — request 生成の更新を検証する。
- `c:\Users\tohbo\python_programs\pjp_compressor_v2\tests\integration\test_job_runner.py` — orchestrator への引数伝搬を検証する。
- `c:\Users\tohbo\python_programs\pjp_compressor_v2\tests\integration\test_ui_controller.py` — PNG スライダー活性制御と status/host ダミー更新の受け皿。

**Verification**
1. `pytest tests/unit/test_pdf_utils.py tests/unit/test_contracts.py tests/unit/test_ui_tkinter_mapper.py tests/integration/test_job_runner.py tests/integration/test_ui_controller.py`
2. pngquant がある環境では、native PDF `lossy` で PNG を含む PDF を処理し、出力ログに pngquant 経路が出ること、GUI の PDF PNG スライダーが有効であることを確認する。
3. pngquant を一時的に隠した環境では、同じ画面で PDF PNG スライダーが無効になり、注記が表示され、Pillow 256 色フォールバックで処理が継続することを確認する。
4. native PDF `both` と `lossless` を切り替え、`lossless` では lossy controls が無効、`both` では DPI/JPEG は有効だが PNG スライダーは capability 条件に従うことを確認する。

**Decisions**
- `jpeg→png` は現行コード上の用語と整合しないため、今回の仕様は `PNG → JPEG 変換を廃止し、PNG 系は常に PNG のまま処理` として扱う。
- Ghostscript 経路には PNG 品質スライダーを適用しない。対象は `backend/core/pdf_utils.py` の native lossy ロジックとその GUI 表示に限定する。
- Pillow fallback の色数は要件どおり 256 色固定にし、GUI の PDF PNG 品質値は表示のみ保持して backend では無視する。
- 既存の通常 PNG 圧縮の `png_quality` と `use_pngquant` は別設定のまま維持し、今回の変更は PDF 内 PNG のみを対象にする。

**Further Considerations**
1. 実装時は `backend/core/image_utils.py` の pngquant 呼び出しロジックを helper 化して再利用するか、`pdf_utils.py` 側に閉じた helper を置くかを早めに決める。変更影響を最小化するなら `pdf_utils.py` 内 helper が無難。
2. 既存ドキュメントに `PNG → JPEG 変換` の記載がある場合だけ、コード変更後に該当箇所を更新する。
