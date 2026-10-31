# Plan: ffmpeg 動画圧縮機能の追加と UI タブ再編

**TL;DR**: `ffmpeg` を用いた動画ファイル一括圧縮を第3の圧縮ドメインとして追加する。外部ツール解決は既存の `system` 優先 → `bundled` (`vendor/ffmpeg-windows/`) 次点 → `unavailable`（UI無効化・劣化起動）の方式を踏襲する。CPU過負荷を防ぐため動画エンコードのみ `threading.Semaphore(1)` で同時1プロセスに制限し、UIの品質スライダー（0〜100）を内部で `CRF`（18〜42）へ変換して `.mp4` に統一出力する。また、動画単体の進捗（`%`）を `ProgressEvent(kind='status')` 経由で下部ステータスバーへ表示し、肥大化したメインタブから「出力設定」を独立タブへ分離して4タブ構成とする。

---

## Steps

### Phase 1: 外部ツール解決とデータ契約・設定の拡張

1. **[shared/runtime_paths.py](../../shared/runtime_paths.py)** — `resolve_ffmpeg_executable()` の追加
   - `resolve_external_tool()` を使用し、`system_candidates=('ffmpeg',)`、`bundled_relative_candidates=('ffmpeg-windows/bin/ffmpeg.exe', 'ffmpeg-windows/ffmpeg.exe')` で解決する。

2. **[backend/contracts.py](../../backend/contracts.py)** — データ契約の拡張
   - `VideoCompressionConfig` dataclass を新設する:
     - `enabled: bool = True`
     - `codec: Literal['libx264', 'libx265'] = 'libx264'`
     - `quality: int = 75`
     - `crf: int = 24`
     - `preset: str = 'medium'`
     - `audio_mode: Literal['aac', 'copy', 'none'] = 'aac'`
     - `audio_bitrate: str = '128k'`
     - `max_long_edge: int = 0`（`0` はリサイズなし）
   - `CapabilityReport` に `ffmpeg_path: str | None = None`、`ffmpeg_source: ToolSource = 'unavailable'`、および `@property def ffmpeg_available(self) -> bool` を追加する。
   - `CompressionRequest` に `video_config: VideoCompressionConfig | None = None` を追加し、`to_legacy_kwargs()` にも `'video_config': self.video_config` を含める。

3. **[backend/capabilities.py](../../backend/capabilities.py)** — `ffmpeg` 可用性検出の追加
   - `_detect_ffmpeg()` を追加し、`detect_capabilities()` の返却値に `ffmpeg_path` と `ffmpeg_source` を含める。

4. **[backend/settings.py](../../backend/settings.py) & [frontend/settings.py](../../frontend/settings.py)** — 既定値と対象拡張子の定義
   - `backend/settings.py` に動画既定値を追加する:
     - `VIDEO_EXTENSIONS = frozenset({'mp4', 'mov', 'avi', 'mkv', 'webm', 'wmv', 'm4v'})`
     - `VIDEO_ENABLED_DEFAULT = True`
     - `VIDEO_QUALITY_DEFAULT = 75`
     - `VIDEO_CODEC_DEFAULT = 'libx264'`
     - `VIDEO_PRESET_DEFAULT = 'medium'`
     - `VIDEO_AUDIO_MODE_DEFAULT = 'aac'`
     - `VIDEO_AUDIO_BITRATE_DEFAULT = '128k'`
     - `VIDEO_MAX_LONG_EDGE_DEFAULT = 0`
   - `frontend/settings.py` の `INPUT_DIR_CLEANUP_EXTENSIONS` と `OUTPUT_DIR_CLEANUP_EXTENSIONS` に `{'.mp4', '.mov', '.avi', '.mkv', '.webm', '.wmv', '.m4v'}` を追加する。

---

### Phase 2: Backend コア（`ffmpeg` 実行・進捗パース）の実装

5. **`backend/core/video_utils.py`**（新規作成） — `compress_video_ffmpeg()` の実装
   - シグネチャ:
     ```python
     def compress_video_ffmpeg(
         inpath: str,
         outpath: str,
         video_config: VideoCompressionConfig | dict[str, Any],
         *,
         progress_callback: Callable[[int], None] | None = None,
         log_language: str = 'ja',
     ) -> tuple[bool, str]:
     ```
   - `resolve_ffmpeg_executable()` でパスを解決し、未検出時は `(False, translate(log_language, 'video_ffmpeg_missing'))` を返す。
   - 出力中断時の破損ファイル残留を防ぐため、出力先ディレクトリ内に一時ファイル（`.tmp_<uuid>.mp4`）を生成して書き出し、正常完了後に `temp_out.replace(outpath)` でアトミックに配置する。
   - `ffmpeg` 引数構成:
     - 映像: `-c:v <codec> -crf <crf> -preset <preset> -pix_fmt yuv420p`
     - リサイズ（`max_long_edge > 0` の場合のみ）: `-vf "scale='if(gt(iw,ih),min(EDGE,iw),-2)':'if(gt(iw,ih),-2,min(EDGE,ih))'"`（拡大防止かつ偶数ピクセル丸め）
     - 音声: `'aac'` → `-c:a aac -b:a 128k`、`'copy'` → `-c:a copy`、`'none'` → `-an`
     - Web最適化・進捗出力: `-movflags +faststart -progress pipe:1 -nostats`
   - サブプロセス進捗パース:
     - Windows 環境では `creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)` を指定してコンソールウィンドウの点滅を防止する。
     - `Duration: HH:MM:SS.xx` から総マイクロ秒 `total_us` を抽出し、`out_time_us=(\d+)` から進捗率 `pct = min(99, max(0, int(current_us * 100 / total_us)))` を算出する。
     - UI スレッドへのイベント過多を防ぐため、前回通知から `1%` 以上増加かつ `0.2秒` 以上経過したときのみ `progress_callback(pct)` を呼び出す。

6. **`backend/services/video_service.py`**（新規作成）
   - `backend/core/video_utils.py` の `compress_video_ffmpeg` をサービス層として再公開する。

---

### Phase 3: ワーカー・オーケストレータの統合（CPU負荷制御・`.mp4` 統一・進捗通知）

7. **[backend/core/worker_ops.py](../../backend/core/worker_ops.py)** — Semaphore 制御と動画ディスパッチ
   - モジュールレベルに `_VIDEO_ENCODE_SEMAPHORE = threading.Semaphore(1)` を定義する。
   - `_csv_action_key()` に動画拡張子の分岐（`'csv_action_video'`）を追加する。
   - `process_single_file()` で `ext in VIDEO_EXTENSIONS` を処理する:
     - `video_config` が有効かつ `ffmpeg` 利用可能時は `with _VIDEO_ENCODE_SEMAPHORE:` 内で `compress_video_ffmpeg()` を呼び出し、`progress_callback` から `video_status_callback(inpath.name, pct)` へ中継する。
     - 無効時または `ffmpeg` 未検出時は `processed = False` として返し、後段の `copy_non_target_files`（ミラーコピー）やスキップ処理に委ねる。

8. **[backend/orchestrator/job_runner.py](../../backend/orchestrator/job_runner.py)** — `.mp4` 出力パス正規化とステータス連携
   - `_tool_detection_summary()` に `ffmpeg` の検出結果（`system` / `bundled` / `unavailable`）を追加する。
   - `run_compression_job()` に `video_config: VideoCompressionConfig | dict[str, Any] | None = None` と `status_func: Callable[[str], None] | None = None` を追加する。
   - `append_task()` で動画ファイル（かつ動画圧縮が有効で `ffmpeg` が利用可能な場合）の `outpath` を `.with_suffix('.mp4')` に変換する。同一出力先に別拡張子の同名動画（例: `sample.mp4` と `sample.mov`）が存在する場合は `sample_mov.mp4` へリネームして衝突を回避する。
   - 動画ワーカーから単体進捗 `video_pct` を受け取った際、全体の進捗状況と合わせて `status_func` へ通知する（例: `処理中... 40% (4/10) - 動画圧縮中: movie.mov (65%)`）。
   - `run_compression_request()` 内で `on_status` コールバックを定義し、`ProgressEvent(kind='status', message=message)` を送出する。

---

### Phase 4: Frontend（UI 4タブ化・動画設定セクション・品質→CRF変換）

9. **[frontend/ui_tkinter_state.py](../../frontend/ui_tkinter_state.py) & [frontend/ui_contracts.py](../../frontend/ui_contracts.py)** — UI State と Protocol 定義
   - `initialize_ui_state()` に動画設定用の Tk 変数を追加する:
     - `video_enabled: tk.BooleanVar`（既定 `True`）
     - `video_quality: tk.IntVar`（既定 `75`）
     - `video_codec: tk.StringVar`（既定 `'libx264'`）
     - `video_preset: tk.StringVar`（既定 `'medium'`）
     - `video_audio_mode: tk.StringVar`（既定 `'aac'`）
     - `video_max_long_edge: tk.StringVar`（既定 `'0'`）
   - `CompressionRequestAppProtocol` と `TkUiControllerHostProtocol` に動画用 state 変数・ウィジェット・`output_settings_tab` を追加する。

10. **[frontend/ui_tkinter_mapper.py](../../frontend/ui_tkinter_mapper.py)** — 品質（0〜100）から CRF への変換
    - `quality_to_crf(quality: int, codec: str = 'libx264') -> int` を実装する:
      - `Q=100` → `CRF=18`、`Q=75` → `CRF=24`、`Q=0` → `CRF=40` の線形補間（`round(40 - (q / 100.0) * 22)`）。
      - `codec == 'libx265'` の場合は `+2` 補正（上限 `42`）を適用する。
    - `build_video_config(app)` を追加し、`build_compression_request()` で `CompressionRequest.video_config` に格納する。

11. **[frontend/ui_tkinter_view.py](../../frontend/ui_tkinter_view.py)** — 「出力設定」タブの分離と「動画圧縮設定」の構築
    - `_build_notebook()` を4タブ構成に更新する:
      1. `圧縮設定` (`self.settings_tab`)
      2. `出力設定` (`self.output_settings_tab`) **← 新設**
      3. `アプリ設定` (`self.app_settings_tab`)
      4. `ログ・進捗` (`self.log_tab`)
    - 従来 `_build_settings_tab()` 末尾で呼んでいた `self._build_output_section()` を `self.output_settings_tab` 配下へ移動する。
    - `_build_settings_tab()` 内に `_build_video_section()`（背景色 `#f1fff4` の `LabelFrame`）を新設し、以下のコントロールを配置する:
      - `ffmpeg` 検出状態ラベル (`self.video_engine_status_var`)
      - 「動画を圧縮する（.mp4形式で出力）」Checkbutton
      - 動画品質スライダー（0〜100、現在値と変換後 CRF 目安を表示）
      - 映像コーデック選択 Radiobutton（`H.264 (高互換)` / `H.265 (高圧縮)`）
      - エンコード速度 Preset Combobox（`ultrafast` / `fast` / `medium` / `slow`）
      - 音声処理 Combobox（`AAC 128kbps` / `そのままコピー` / `音声なし`）
      - 長辺リサイズ上限 Combobox（`変更なし` / `3840` / `1920` / `1280` / `854`）

12. **[frontend/ui_tkinter_controller.py](../../frontend/ui_tkinter_controller.py)** — 動画 UI 活性制御と開始ログ
    - `_update_video_controls()` を追加し、`capabilities.ffmpeg_available` が `False` のときは動画セクション全体を `disabled` にして未検出注記を表示する。利用可能時は `video_enabled` トグルに応じて子ウィジェットの `normal` / `disabled` を切り替える。
    - `_refresh_pdf_engine_status()`（または新設の `_refresh_video_engine_status()`）で `ffmpeg` の供給元（`system` / `bundled` / `unavailable`）を表示する。
    - `start_compress()` に動画設定の開始時ログ出力を追加する。

---

### Phase 5: 多言語カタログ・ビルド定義・テスト・ドキュメントの更新

13. **[frontend/config_data/locales/ja.json](../../frontend/config_data/locales/ja.json) & [frontend/config_data/locales/en.json](../../frontend/config_data/locales/en.json)**
    - `tab_output`、`section_video_settings`、動画UIラベル群、CSVアクション名（`csv_action_video`）、動画進捗ステータス文言（`status_processing_video`）を日英両方で追加する。

14. **[compressor_launcher_tkinter.spec](../../compressor_launcher_tkinter.spec)**
    - `vendor/` 同梱ロジックで `vendor/ffmpeg-windows/` も同様にバンドル対象として扱われることを確認・調整する。

15. **テストの追加・更新**
    - `tests/unit/test_video_utils.py`（新規）: コマンド生成、CRF適用、リサイズフィルタ式、`Duration` / `out_time_us` からの進捗 `%` パース、一時ファイル置換と失敗時クリーンアップの単体テスト。
    - [tests/unit/test_capabilities.py](../../tests/unit/test_capabilities.py): `ffmpeg` の `system` / `bundled` / `unavailable` 解決順序テスト。
    - [tests/unit/test_contracts.py](../../tests/unit/test_contracts.py) & [tests/unit/test_ui_tkinter_mapper.py](../../tests/unit/test_ui_tkinter_mapper.py): `quality_to_crf()` の変換値検証と `VideoCompressionConfig` の伝搬テスト。
    - [tests/integration/test_job_runner.py](../../tests/integration/test_job_runner.py): `.mov` 等の `.mp4` 統一出力、同名衝突回避、Semaphore 経由の直列実行、`status` イベント発火の検証。
    - [tests/regression/test_tkinter_regression.py](../../tests/regression/test_tkinter_regression.py): Notebook の4タブ構成（`出力設定` タブ分離）と動画セクションの活性/非活性状態の回帰テスト。

16. **[README.md](../../README.md) & [Documentation/README.md](../../Documentation/README.md)**
    - 動画圧縮機能、4タブ構成、`vendor/ffmpeg-windows/` の配置手順について追記する。

---

## Relevant files

- [shared/runtime_paths.py](../../shared/runtime_paths.py) — `resolve_ffmpeg_executable()` の追加先
- [backend/contracts.py](../../backend/contracts.py) — `VideoCompressionConfig`、`CapabilityReport`、`CompressionRequest` の拡張
- [backend/capabilities.py](../../backend/capabilities.py) — `ffmpeg` 検出の統合
- [backend/settings.py](../../backend/settings.py) — 動画圧縮の既定値・対象拡張子定義
- `backend/core/video_utils.py` *(新規)* — `ffmpeg` サブプロセス実行とリアルタイム進捗パーサ
- `backend/services/video_service.py` *(新規)* — 動画圧縮サービス層の公開入口
- [backend/core/worker_ops.py](../../backend/core/worker_ops.py) — `_VIDEO_ENCODE_SEMAPHORE` と拡張子ディスパッチ
- [backend/orchestrator/job_runner.py](../../backend/orchestrator/job_runner.py) — `.mp4` 出力パス正規化と動画単体進捗の `status` イベント通知
- [frontend/settings.py](../../frontend/settings.py) — クリーンアップ対象拡張子への動画拡張子追加
- [frontend/ui_contracts.py](../../frontend/ui_contracts.py) — 動画 state・widget・新規タブの Protocol 定義
- [frontend/ui_tkinter_state.py](../../frontend/ui_tkinter_state.py) — 動画設定用 Tk 変数の初期化
- [frontend/ui_tkinter_mapper.py](../../frontend/ui_tkinter_mapper.py) — 品質スライダー値（0〜100）から CRF への変換と `VideoCompressionConfig` 構築
- [frontend/ui_tkinter_view.py](../../frontend/ui_tkinter_view.py) — 「出力設定」タブの独立化（4タブ構成）と「動画圧縮設定」セクションの追加
- [frontend/ui_tkinter_controller.py](../../frontend/ui_tkinter_controller.py) — `ffmpeg` 可用性に応じた UI 活性制御と開始時ログ出力
- [frontend/config_data/locales/ja.json](../../frontend/config_data/locales/ja.json) / [frontend/config_data/locales/en.json](../../frontend/config_data/locales/en.json) — 日英ロケール文言の追加

---

## Verification

1. `pytest tests/unit/test_capabilities.py tests/unit/test_contracts.py tests/unit/test_ui_tkinter_mapper.py tests/unit/test_video_utils.py`
2. `pytest tests/integration/test_job_runner.py tests/regression/test_tkinter_regression.py`
3. `ffmpeg` 導入環境にて `.mp4` / `.mov` を含むフォルダを圧縮し、出力が `.mp4` に統一され、エンコード中に下部ステータスバーへ動画単体の進捗（`%`）が表示されることを確認する。
4. `ffmpeg` 未検出環境（モックまたは一時リネーム）にてアプリを起動し、エラーなく起動して動画設定セクションのみが無効化され、PDF・画像圧縮が従来どおり動作することを確認する。
5. UI 上で「圧縮設定」「出力設定」「アプリ設定」「ログ・進捗」の4タブが正しく表示・遷移でき、既存の出力設定（CSV出力、ZIP展開/再圧縮、ミラーコピー等）が「出力設定」タブから問題なく機能することを確認する。

---

## Decisions

- **CPU負荷対策**: `ThreadPoolExecutor` は維持し、動画エンコード処理のみ `threading.Semaphore(1)` で同時実行数を1本に制限する（画像・PDFの並列処理は妨げない）。
- **品質設定のUI表現**: ユーザー向けには画像・PDFと同じ 0〜100 の品質スライダーを提示し、mapper 層で `CRF`（18〜42）へ変換する。
- **出力コンテナ形式**: 入力動画の拡張子にかかわらず、出力時は互換性の高い `.mp4` に統一する。
- **進捗表示**: `ffprobe` への追加依存は持たせず、`ffmpeg -progress pipe:1` の出力と `Duration` ヘッダから単体進捗率を算出してステータスバー（`ProgressEvent(kind='status')`）へ流す。
- **タブ構成**: メインタブの肥大化を防ぐため、「出力設定」を独立した第2タブへ切り出す。
