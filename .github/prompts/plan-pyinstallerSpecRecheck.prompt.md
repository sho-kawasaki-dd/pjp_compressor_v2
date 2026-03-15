## Plan: PyInstaller spec再点検

現行の refactor 後コードを起動経路・動的 import・同梱データ参照の観点で確認した結果、[compressor_launcher_tkinter.spec](compressor_launcher_tkinter.spec) に即時必須の大幅追加は現時点では見当たらない。主眼は、1) 既存 `datas` が現行リソース参照と整合していることを維持、2) `hiddenimports` のうち旧構成の名残を整理、3) 実ビルドで最終確認する、の3点。推奨方針は「まず最小変更で stale な `hiddenimports` を見直し、その後 PyInstaller ビルドで不足モジュールが本当に出るか検証する」。 

**Steps**
1. 起動チェーン基準で packaging 対象を確定する
   - [compressor_launcher_tkinter.py](compressor_launcher_tkinter.py#L23) → [frontend/bootstrap.py](frontend/bootstrap.py#L52-L53) → [frontend/ui_tkinter.py](frontend/ui_tkinter.py#L28-L39) の import 連鎖を基準に、PyInstaller が静的解析できる import と、`hiddenimports` が必要な import を分ける。
2. 動的 import と optional dependency の実態を分離する
   - [backend/capabilities.py](backend/capabilities.py#L13-L18) の `importlib.import_module()` は capability 判定用であり、ここだけを見ると hidden import 候補に見えるが、実運用では [backend/core/pdf_utils.py](backend/core/pdf_utils.py#L23-L37) の遅延 import とあわせて「本当に PyInstaller が拾えないか」を切り分ける。
   - `fitz` / `pikepdf` は runtime 判定にも使われるため、追加の `hiddenimports` が必要かは build 実測で判断する。
3. `datas` / `binaries` の要否を確定する
   - [frontend/settings.py](frontend/settings.py#L12-L18) と [frontend/settings.py](frontend/settings.py#L50-L51) が参照する `frontend/config_data/ui_catalogs.json`、`sounds/`、`images/` は現在の [compressor_launcher_tkinter.spec](compressor_launcher_tkinter.spec#L13-L14) と整合しているため維持候補とする。
   - [shared/runtime_paths.py](shared/runtime_paths.py#L11-L21) の `_MEIPASS` 解決と [frontend/bootstrap.py](frontend/bootstrap.py#L13) / [frontend/ui_tkinter.py](frontend/ui_tkinter.py#L128) の利用箇所を基準に、追加データフォルダが増えていないことを確認済みとする。
   - Ghostscript / pngquant は [backend/capabilities.py](backend/capabilities.py#L23-L34) と [backend/core/image_utils.py](backend/core/image_utils.py#L66-L72) で PATH 探索前提のため、`binaries=[]` 維持を基本方針とする。
4. `hiddenimports` の過不足を整理する
   - 現行 `hiddenimports` にある [backend/services/pdf_service.py](backend/services/pdf_service.py)、[backend/services/image_service.py](backend/services/image_service.py)、[backend/services/cleanup_service.py](backend/services/cleanup_service.py) は現行起動経路では未使用のため、整理候補として扱う。
   - 一方で [backend/services/archive_service.py](backend/services/archive_service.py) は [backend/orchestrator/job_runner.py](backend/orchestrator/job_runner.py#L26) から実使用されているため維持候補とする。
   - `frontend.*` や `backend.core.*` の多くは通常 import 連鎖で到達しており、機械的に `hiddenimports` を増やすのではなく、build warning が出たモジュールだけ追加する方針にする。
5. 実ビルド前提の最終確認項目を定義する
   - `pyinstaller --clean` 実行時に missing module warning が `fitz` / `pikepdf` / `backend.*` / `frontend.*` で出るか確認する。
   - 生成物で起動、スプラッシュ表示、サウンド再生、D&D、JSON 読み込み、画像アイコン表示を確認する。
   - 依存未導入時でも UI 起動だけは維持されるかを、PDF/PNG 外部ツール未導入ケースで確認する。

**Relevant files**
- `c:\Users\tohbo\python_programs\pjp_compressor_v2\compressor_launcher_tkinter.spec` — `datas` / `hiddenimports` / `binaries` の見直し対象
- `c:\Users\tohbo\python_programs\pjp_compressor_v2\compressor_launcher_tkinter.py` — エントリポイント。PyInstaller 解析の起点
- `c:\Users\tohbo\python_programs\pjp_compressor_v2\frontend\bootstrap.py` — 起動時の遅延 import と splash / sound の使用箇所
- `c:\Users\tohbo\python_programs\pjp_compressor_v2\frontend\settings.py` — JSON・sounds・images の実参照元
- `c:\Users\tohbo\python_programs\pjp_compressor_v2\shared\runtime_paths.py` — frozen 時の resource path 解決
- `c:\Users\tohbo\python_programs\pjp_compressor_v2\backend\capabilities.py` — importlib ベースの optional dependency 判定
- `c:\Users\tohbo\python_programs\pjp_compressor_v2\backend\orchestrator\job_runner.py` — 実運用で必要な backend import 連鎖
- `c:\Users\tohbo\python_programs\pjp_compressor_v2\backend\services\archive_service.py` — 維持候補の service wrapper
- `c:\Users\tohbo\python_programs\pjp_compressor_v2\backend\services\pdf_service.py` — 整理候補の service wrapper
- `c:\Users\tohbo\python_programs\pjp_compressor_v2\backend\services\image_service.py` — 整理候補の service wrapper
- `c:\Users\tohbo\python_programs\pjp_compressor_v2\backend\services\cleanup_service.py` — 整理候補の service wrapper

**Verification**
1. `python -m PyInstaller --clean .\compressor_launcher_tkinter.spec` を実行し、build log の missing module / excluded module を確認する。
2. 生成した one-folder 配布物を起動し、スプラッシュ画像、ウィンドウアイコン、起動音、`ui_catalogs.json` 読み込み成功を確認する。
3. D&D で入力フォルダ設定が動くことを確認し、`tkinterdnd2` の datas / hiddenimports が十分か検証する。
4. Ghostscript / pngquant が未導入でもアプリ起動し、該当機能だけ制限されることを確認する。

**Decisions**
- 現時点の暫定判断: `datas` の追加は不要。
- 現時点の暫定判断: `binaries` の追加は不要。
- 変更候補は `hiddenimports` の削減・整理が中心で、増加は build 実測で必要性が出た場合に限定する。
- この調査では terminal 実行手段が無いため、PyInstaller 実ビルド結果までは未確認。

**Further Considerations**
1. `console=True` はクラッシュ時の保守性を優先する設定として妥当。配布 UX を優先して `console=False` にするかは別判断に切り出す。
2. [Documentation/README.md](Documentation/README.md#L114) の生成先表記は現 spec の `name='PDF_JPG_PNG_Compressor_v2'` とずれている可能性があるため、spec 変更の有無とは別に整合確認対象にする.
