# Plan: ffmpeg 動画圧縮機能の追加と UI タブ再編

**TL;DR**: `ffmpeg` を用いた動画ファイル一括圧縮を第3の圧縮ドメインとして追加する。外部ツール解決は既存の `system` 優先 → `bundled` (`vendor/ffmpeg-windows/`) 次点 → `unavailable`（UI無効化・劣化起動）の方式を踏襲する。CPU過負荷を防ぐため、動画タスクのみ **専用の単一ワーカー `ThreadPoolExecutor(max_workers=1)`** で直列実行し、画像・PDF の並列処理は妨げない。UIの品質スライダー（0〜100）は mapper 層で `CRF`（x264: 18〜40 / x265: 22〜44）へ変換し、`.mp4` に統一出力する。ただし **圧縮後のサイズが元以上になった場合は、拡張子も含めて元ファイルをそのままコピー** する。動画単体の進捗（`%`）は専用イベント `ProgressEvent(kind='video_progress')` で通知し、controller 側で全体進捗と合成してステータスバーへ表示する。肥大化したメインタブから「出力設定」を独立タブへ分離して4タブ構成とする。

---

## Steps

### Phase 1: 外部ツール解決とデータ契約・設定の拡張

1. **[shared/runtime_paths.py](../../shared/runtime_paths.py)** — `resolve_ffmpeg_executable()` の追加
   - `resolve_external_tool()` を使用し、`system_candidates=('ffmpeg',)`、`bundled_relative_candidates=('ffmpeg-windows/bin/ffmpeg.exe', 'ffmpeg-windows/ffmpeg.exe')` で解決する。

2. **[backend/contracts.py](../../backend/contracts.py)** — データ契約の拡張
   - `VideoCompressionConfig`（`frozen=True`）dataclass を新設する。backend は **`crf` のみを正** とし、UI の品質値（0〜100）は保持しない:
     - `enabled: bool = True`
     - `codec: Literal['libx264', 'libx265'] = 'libx264'`
     - `crf: int = 24`
     - `preset: str = 'medium'`
     - `audio_mode: Literal['aac', 'copy', 'none'] = 'aac'`
     - `audio_bitrate: str = '128k'`
     - `max_long_edge: int = 0`（`0` はリサイズなし）
   - `CapabilityReport` に以下を追加する（既定値付きのため既存の位置引数呼び出しは無変更で動作する）:
     - `ffmpeg_path: str | None = None`
     - `ffmpeg_source: ToolSource = 'unavailable'`
     - `ffmpeg_encoders: frozenset[str] = frozenset()`
     - `@property ffmpeg_available -> bool`（`ffmpeg_path` があり、かつ `'libx264' in ffmpeg_encoders`）
     - `@property ffmpeg_hevc_available -> bool`（`ffmpeg_available` かつ `'libx265' in ffmpeg_encoders`）
   - `EventKind` に `'video_progress'` を追加する。`ProgressEvent(kind='video_progress', message=<ファイル名>, current=<pct | None>)` とし、`current=None` は「動画タスク終了（表示クリア）」を表す。
   - `CompressionRequest` に `video_config: VideoCompressionConfig | None = None` を追加し、`to_legacy_kwargs()` にも `'video_config': self.video_config` を含める。

3. **[backend/capabilities.py](../../backend/capabilities.py)** — `ffmpeg` 可用性・エンコーダ検出の追加
   - `_detect_ffmpeg()` を追加し、解決できた場合は `ffmpeg -hide_banner -encoders` を1回実行（`CREATE_NO_WINDOW`、`timeout=10`、失敗時は空集合）して `libx264` / `libx265` の有無を収集する。
   - `detect_capabilities()` はジョブ開始ごとにも呼ばれる（`_tool_detection_summary()`）ため、ffmpeg 検出結果は `functools.lru_cache(maxsize=1)` でキャッシュする。テストでは `cache_clear()` で初期化する。
   - `detect_capabilities()` の返却値に `ffmpeg_path` / `ffmpeg_source` / `ffmpeg_encoders` を含める。

4. **[backend/settings.py](../../backend/settings.py) & [frontend/settings.py](../../frontend/settings.py)** — 既定値と対象拡張子の定義
   - `backend/settings.py` に動画既定値を追加する（**拡張子定義の正はここ**）:
     - `VIDEO_EXTENSIONS = frozenset({'mp4', 'mov', 'avi', 'mkv', 'webm', 'wmv', 'm4v'})`
     - `VIDEO_ENABLED_DEFAULT = True`
     - `VIDEO_QUALITY_DEFAULT = 75`（UI 用）
     - `VIDEO_CODEC_DEFAULT = 'libx264'`
     - `VIDEO_PRESET_DEFAULT = 'medium'`
     - `VIDEO_AUDIO_MODE_DEFAULT = 'aac'`
     - `VIDEO_AUDIO_BITRATE_DEFAULT = '128k'`
     - `VIDEO_MAX_LONG_EDGE_DEFAULT = 0`
     - `VIDEO_TEMP_PREFIX = '.pjp_tmp_'`
   - `frontend/settings.py` では `VIDEO_CLEANUP_EXTENSIONS = {f'.{e}' for e in VIDEO_EXTENSIONS}` を backend から派生させ、`INPUT_DIR_CLEANUP_EXTENSIONS` と `OUTPUT_DIR_CLEANUP_EXTENSIONS` に合流させる（二重定義によるズレを防止）。
   - 入力クリーンアップ対象に動画が加わることを README / リリースノートで周知する。

---

### Phase 2: Backend コア（`ffmpeg` 実行・進捗パース）の実装

5. **`backend/core/video_utils.py`**（新規作成） — `compress_video_ffmpeg()` の実装
   - 戻り値型を新設する:
     ```python
     @dataclass(frozen=True)
     class VideoCompressResult:
         ok: bool                 # ffmpeg 処理として成功（縮小 or 元維持）したか
         message: str
         final_outpath: str | None  # 実際に配置したファイル（失敗時 None）
         kept_original: bool = False
     ```
   - シグネチャ:
     ```python
     def compress_video_ffmpeg(
         inpath: str,
         outpath: str,             # 予定出力先（.mp4、衝突回避済み）
         original_outpath: str,    # 入力と同じ拡張子の出力先（元維持時に使用）
         video_config: VideoCompressionConfig,
         *,
         progress_callback: Callable[[int], None] | None = None,
         log_language: str = 'ja',
     ) -> VideoCompressResult:
     ```
   - `resolve_ffmpeg_executable()` でパスを解決し、未検出時は `ok=False`（`video_ffmpeg_missing`）を返す。
   - **一時ファイル**: 出力先ディレクトリ内に `f'{VIDEO_TEMP_PREFIX}{uuid4().hex}.mp4'` を生成して書き出す。`try/finally` で、正常に `replace` した場合以外は必ず `unlink(missing_ok=True)` する。
   - **ffmpeg 引数構成**:
     ```python
     cmd = [
         ffmpeg, '-hide_banner', '-nostdin', '-y',
         '-i', inpath,
         '-map', '0:v:0', '-map', '0:a:0?',      # 字幕・カバーアート等による失敗を防止
         '-vf', vf,
         '-c:v', codec, '-crf', str(crf), '-preset', preset,
         '-pix_fmt', 'yuv420p',
         *(['-tag:v', 'hvc1', '-x265-params', 'log-level=error'] if codec == 'libx265' else []),
         *audio_args,
         '-map_metadata', '0',
         '-movflags', '+faststart',
         '-progress', 'pipe:1', '-nostats',
         str(temp_out),
     ]
     ```
     - 映像フィルタ: `yuv420p` は偶数解像度が必須のため、**常に末尾で偶数丸め** を行う。
       ```python
       even = 'scale=trunc(iw/2)*2:trunc(ih/2)*2'
       if max_long_edge > 0:
           e = max_long_edge
           vf = (f"scale=w='if(gte(iw,ih),min({e},iw),-2)':"
                 f"h='if(gte(iw,ih),-2,min({e},ih))',{even}")
       else:
           vf = even
       ```
     - 音声: `'aac'` → `-c:a aac -b:a <audio_bitrate>`、`'copy'` → `-c:a copy`、`'none'` → `-an`
   - **サブプロセス起動と進捗パース**（stdout/stderr の片側詰まりによるデッドロック防止）:
     ```python
     proc = subprocess.Popen(
         cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
         text=True, encoding='utf-8', errors='replace',
         creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)
                       | getattr(subprocess, 'BELOW_NORMAL_PRIORITY_CLASS', 0),
     )
     ```
     - 単一ループで行を読み、以下をパースする:
       - `Duration: (\d+):(\d+):(\d+(?:\.\d+)?)` → 総マイクロ秒 `total_us`
       - `out_time_us=(\d+)`（`N/A` は無視）→ `pct = min(99, max(0, int(current_us * 100 / total_us)))`
       - `progress=end` → 完了
     - `Duration: N/A`（総尺不明）の場合は `%` を通知しない。
     - UI へのイベント過多を防ぐため、前回通知から `1%` 以上増加かつ `0.2秒` 以上経過したときのみ `progress_callback(pct)` を呼ぶ。
     - 失敗時の詳細表示用に、出力末尾を `collections.deque(maxlen=30)` で保持する。整形は [backend/core/pdf_utils.py](../../backend/core/pdf_utils.py) の `_sanitize_subprocess_error()` を共通ユーティリティへ切り出して再利用する（内部パス露出抑止・240文字制限）。
   - **タイムアウト**: 長尺動画の誤中断を避けるため、固定タイムアウトは設けない。停止手段はアプリ終了時のプロセス終了（Step 6）とする。進捗停滞（ストール）検知は将来課題とする。
   - **音声 copy の自動フォールバック**: `audio_mode == 'copy'` で失敗した場合、`aac` に切り替えて1回だけ再試行し、その旨をメッセージに含める（webm の Vorbis/Opus、wmv の WMA、mov の PCM 等は MP4 へ copy できないため）。
   - **結果の配置**:

     | ケース | 配置 | 戻り値 |
     |---|---|---|
     | 成功・`temp_size < orig_size` | `temp_out.replace(outpath)` | `ok=True, final_outpath=outpath` |
     | 成功・`temp_size >= orig_size` | 一時ファイル削除 → `shutil.copy2(inpath, original_outpath)`（**拡張子も含め元のまま**、ミラー設定に関係なく常に実施） | `ok=True, final_outpath=original_outpath, kept_original=True` |
     | ffmpeg 失敗 | 一時ファイル削除のみ（コピー要否は job_runner が判断） | `ok=False, final_outpath=None` |

   - **実行中プロセスの追跡**: モジュールレベルに `_ACTIVE_PROCS: set[subprocess.Popen]` と `_ACTIVE_LOCK = threading.Lock()` を持ち、起動時に登録・終了時に除去する。`terminate_active_video_processes(timeout: float = 3.0) -> None` を提供し、`terminate()` → `wait(timeout)` → 残存時 `kill()` を行う。
   - **残留一時ファイル掃除**: `cleanup_stale_video_temps(output_dir: Path) -> int` を提供し、出力フォルダ配下の `f'{VIDEO_TEMP_PREFIX}*.mp4'` を削除する。

6. **`backend/services/video_service.py`**（新規作成）
   - 既存 [backend/services/pdf_service.py](../../backend/services/pdf_service.py) と同じ構成で、`compress_video_ffmpeg` / `terminate_active_video_processes` / `cleanup_stale_video_temps` を公開する。

---

### Phase 3: ワーカー・オーケストレータの統合（直列実行・`.mp4` 統一・進捗通知）

7. **[backend/core/worker_ops.py](../../backend/core/worker_ops.py)** — タスク拡張と動画ディスパッチ
   - **タスクタプルの拡張**: 既存 index 0〜19 は変更せず、末尾に3要素を追加する（job_runner の `task[16..18]` 参照は維持される）。

     | index | 要素 |
     |---|---|
     | 20 | `video_config: VideoCompressionConfig \| None`（動画処理しない場合 `None`） |
     | 21 | `video_progress_callback: Callable[[int], None] \| None` |
     | 22 | `original_outpath: str`（入力と同じ拡張子の出力先） |

     旧形式（20要素）互換のため、切り詰めは次の形にする:
     ```python
     args = tuple(args[:23]) + (None,) * max(0, 23 - len(args))
     ```
   - `WorkerFileResult` に `final_outpath: str | None = None` を追加する。
   - `process_single_file()` で `ext in VIDEO_EXTENSIONS and video_config is not None` の場合に `compress_video_ffmpeg()` を呼び出す。動画処理可否の判定は job_runner が行い、worker は `video_config` の有無だけで分岐する。
     - `ok=True` → `processed=True`、`final_outpath` を設定。`out_size` は `final_outpath` のサイズを採用する。
     - `ok=False` → `processed=False`（フォールバックコピーは job_runner に委ねる）。
   - `_csv_action_key()` に動画分岐を追加する: 通常成功 `'csv_action_video'`、元維持 `'csv_action_video_kept_original'`。
   - 動画タスク終了時（成功・失敗とも）に `video_progress_callback` へ終了通知を送れるよう、job_runner 側のラッパーで扱う（Step 8）。

8. **[backend/orchestrator/job_runner.py](../../backend/orchestrator/job_runner.py)** — 出力パス確定・executor 分離・進捗連携
   - `_tool_detection_summary()` に `ffmpeg` の検出結果（`system` / `bundled` / `unavailable`）を追加する。
   - `run_compression_job()` に以下の引数を追加する:
     - `video_config: VideoCompressionConfig | dict[str, Any] | None = None`（dict は `VideoCompressionConfig(**d)` へ正規化）
     - `event_func: Callable[[ProgressEvent], None] | None = None`（`video_progress` 送出用）
   - **動画処理可否の一括判定**（ジョブ開始時に1回）: `video_config.enabled` かつ `report.ffmpeg_available` かつ選択コーデックが `report.ffmpeg_encoders` に含まれる場合のみ有効とする。コーデック非対応時は理由をログ出力して動画処理を無効化する。
   - 動画処理有効時はジョブ開始時に `cleanup_stale_video_temps(output_base)` を呼び、前回異常終了時の一時ファイルを掃除する。
   - **出力パス確定（2パス方式・同名衝突回避）**:
     1. `append_task()` は **候補（入力パス・既定出力パス・CSV 文脈）を収集するだけ** とする（通常走査分・ZIP 展開分の両方）。
     2. `claimed: set[str]`（キーは `str(path).casefold()`、Windows の大文字小文字非区別に対応）を用意する。
     3. まず「拡張子が変わらない出力」（非動画、`.mp4` 入力の動画、動画処理無効時の動画）をすべて `claimed` に登録する。
     4. 次に拡張子が変わる動画（`.mov` / `.m4v` 等）について、`stem.mp4` → `stem_{ext}.mp4` → `stem_{ext}_2.mp4` → … の順に空き名を割り当てる。
     5. 確定パスでタスクタプルを構築する。`original_outpath` には既定出力パス（元拡張子）を入れる。
   - **executor 分離**（Semaphore は使わない。全汎用ワーカーが動画待ちで塞がり画像・PDF が停止する問題を回避）:
     ```python
     with ThreadPoolExecutor(max_workers=max_workers) as general_ex, \
          ThreadPoolExecutor(max_workers=1, thread_name_prefix='pjp-video') as video_ex:
         futures = {general_ex.submit(process_single_file, t): t for t in general_tasks}
         futures.update({video_ex.submit(run_video_task, t): t for t in video_tasks})
         for future in as_completed(futures):
             ...  # 既存ループを維持
     ```
     - `run_video_task` は `process_single_file` を呼び、`finally` で `ProgressEvent(kind='video_progress', message=name, current=None)` を送出する。
     - タスク構築時、index 21 に `lambda pct, name=inpath.name: event_func(ProgressEvent(kind='video_progress', message=name, current=pct))` を設定する（`event_func` 未指定時は `None`）。
   - **フォールバックコピー**: `processed=False` かつ `copy_non_target_files` の場合、動画タスクは `outpath`（.mp4）ではなく **`original_outpath`（元拡張子）へコピー** する。
   - **CSV 出力パス**: `result.final_outpath` がある場合、CSV の `output_path` 列のファイル名をそれに差し替える:
     ```python
     if result.final_outpath:
         csv_output = str(PurePosixPath(csv_output).with_name(Path(result.final_outpath).name))
     ```
     同様に、フォールバックコピー時は元拡張子のファイル名を CSV に記録する。
   - `compressible_extensions` は、動画処理有効時のみ `VIDEO_EXTENSIONS` を合流させる（無効時は動画を「対象外」としてミラーコピー扱い）。
   - `_csv_action_label()` に `csv_action_video` / `csv_action_video_kept_original` を追加する。
   - `run_compression_request()`:
     - `run_compression_job(...)` 呼び出しに **`video_config=request.video_config` と `event_func=event_callback` を明示的に追加** する（同関数は `to_legacy_kwargs()` を経由しないため）。

---

### Phase 4: Frontend（UI 4タブ化・動画設定セクション・品質→CRF変換・進捗合成）

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
      ```python
      def quality_to_crf(q: int, codec: str = 'libx264') -> int:
          base = round(40 - (max(0, min(100, q)) / 100.0) * 22)
          return min(51, base + (4 if codec == 'libx265' else 0))
      ```

      | 品質 Q | libx264 | libx265 |
      |---|---|---|
      | 100 | 18 | 22 |
      | 75（既定） | 24 | 28（x265 既定値相当） |
      | 0 | 40 | 44 |

    - `build_video_config(app)` を追加し、CRF を確定させた `VideoCompressionConfig` を構築して `build_compression_request()` で `CompressionRequest.video_config` に格納する。動画無効時は `None` とする。
    - `max_long_edge` は既存の `to_non_negative_int(..., max_value=MAX_RESIZE_DIMENSION)` で正規化する。

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
      - 音声処理 Combobox（`AAC 128kbps` / `そのままコピー（非対応時は AAC へ自動切替）` / `音声なし`）
      - 長辺リサイズ上限 Combobox（`変更なし` / `3840` / `1920` / `1280` / `854`）
      - 注記: 「圧縮後に元より大きくなる場合は元ファイルをそのまま出力します」

12. **[frontend/ui_tkinter_controller.py](../../frontend/ui_tkinter_controller.py)** — 動画 UI 活性制御・進捗合成・終了処理
    - `_update_video_controls()` を追加する:
      - `capabilities.ffmpeg_available` が `False`（ffmpeg 未検出、または libx264 非対応）のときは動画セクション全体を `disabled` にして未検出／対応エンコーダなしの注記を表示する。
      - `ffmpeg_hevc_available` が `False` のときは H.265 Radiobutton のみ `disabled` にし注記を表示する（選択中なら `libx264` へ戻す）。
      - 利用可能時は `video_enabled` トグルに応じて子ウィジェットの `normal` / `disabled` を切り替える。
    - `_refresh_video_engine_status()` を新設し、`ffmpeg` の供給元（`system` / `bundled` / `unavailable`）と H.265 可否を表示する。
    - **動画進捗の合成表示**（ステータスのちらつき防止）:
      - controller に `self._video_progress: tuple[str, int | None] | None` を保持する。
      - `_on_progress_event()` で `kind == 'video_progress'` を受けたら状態を更新（`current=None` ならクリア）し、ステータスを再描画する。
      - `_update_progress_ui()` は `t('status_processing', ...)` に、動画進捗がある場合 `t('status_video_suffix', name=..., pct=...)`（総尺不明時は `t('status_video_suffix_nopct', name=...)`）を連結して表示する。
      - `stats` / `error` イベント受信時に動画進捗状態をクリアする。
    - `start_compress()` に動画設定の開始時ログを追加する（例: `動画: H.264 / 品質 75 (CRF 24) / preset=medium / 音声=aac / 長辺=変更なし / ffmpeg=system`）。
    - `on_exit()` で `host.destroy()` の前に `terminate_active_video_processes()` を呼び、ffmpeg 子プロセスの残留を防ぐ（圧縮スレッドは `daemon=True` のため）。

---

### Phase 5: 多言語カタログ・ビルド定義・テスト・ドキュメントの更新

13. **[frontend/config_data/locales/ja.json](../../frontend/config_data/locales/ja.json) & [frontend/config_data/locales/en.json](../../frontend/config_data/locales/en.json)**
    - 日英両方に以下を追加する:
      - タブ・セクション: `tab_output`、`section_video_settings`、動画UIラベル群・注記
      - CSV アクション: `csv_action_video`、`csv_action_video_kept_original`
      - ステータス: `status_video_suffix`、`status_video_suffix_nopct`
      - ログ: `video_ffmpeg_missing`、`video_success`、`video_kept_original`、`video_failed`、`video_audio_copy_fallback`、`video_codec_unavailable`、`log_video_settings`
      - 検出: `capability_ffmpeg_label`、H.265 非対応注記

14. **ビルド・配布**
    - [compressor_launcher_tkinter.spec](../../compressor_launcher_tkinter.spec): `vendor/` 全体を同梱済みのため変更不要（`vendor/ffmpeg-windows/` が含まれることを確認）。
    - [pjp_compressor.iss](../../pjp_compressor.iss) / [vendor_zip.ps1](../../vendor_zip.ps1): `vendor/ffmpeg-windows/` を含めた配布物の構成とサイズ増（100MB 超）を確認する。
    - **ライセンス**: `vendor/ffmpeg-windows/` に ffmpeg の LICENSE とソース入手先（ビルド元 URL・バージョン）を同梱する。GPL ビルド（libx264/libx265 同梱）は本体 AGPL-3.0 と両立する。

15. **テストの追加・更新**
    - `tests/unit/test_video_utils.py`（新規）:
      - コマンド生成（`-map`、`-nostdin`、`-y`、`-pix_fmt`、libx265 時の `-tag:v hvc1`）
      - 映像フィルタ式（リサイズ有無、偶数丸め）
      - `Duration` / `out_time_us` / `N/A` / `progress=end` のパースと間引き条件
      - `audio_mode='copy'` 失敗時の `aac` 再試行（`Popen` モック）
      - 縮小成功時の `.mp4` 配置、元以上時の **元拡張子でのコピー**（`final_outpath` / `kept_original`）、失敗時の一時ファイル削除
      - `terminate_active_video_processes()` と `cleanup_stale_video_temps()`
    - [tests/unit/test_capabilities.py](../../tests/unit/test_capabilities.py): `ffmpeg` の `system` / `bundled` / `unavailable` 解決順序、エンコーダ検出、`lru_cache` の `cache_clear()` 運用。
    - [tests/unit/test_contracts.py](../../tests/unit/test_contracts.py) & [tests/unit/test_ui_tkinter_mapper.py](../../tests/unit/test_ui_tkinter_mapper.py): `quality_to_crf()` の境界値（0 / 75 / 100、x265 補正）、`VideoCompressionConfig` の伝搬、`ffmpeg_available` / `ffmpeg_hevc_available`。
    - [tests/integration/test_job_runner.py](../../tests/integration/test_job_runner.py):
      - `.mov` 等の `.mp4` 統一出力と CSV `output_path` の一致
      - 同名衝突回避（`sample.mp4` と `sample.MOV`、`sample_mov.mp4` 既存時、ZIP 展開分を含む）
      - 失敗時フォールバックコピーが元拡張子になること
      - 元以上サイズ時に元拡張子で配置され `processed` 扱いになること
      - 動画 executor が単一ワーカーで直列実行され、かつ画像タスクがブロックされないこと（遅延モックで検証）
      - `video_progress` イベント（途中 `%` と終了 `None`）の送出
      - `run_compression_request()` 経由で `video_config` が届くこと
    - [tests/integration/test_ui_controller.py](../../tests/integration/test_ui_controller.py): ダミー host に動画用変数・ウィジェットを追加し、進捗合成表示と `on_exit()` のプロセス終了呼び出しを検証する。
    - [tests/regression/test_tkinter_regression.py](../../tests/regression/test_tkinter_regression.py): Notebook のタブ数アサーションを `3` → `4` に更新し、`出力設定` タブ分離と動画セクション（ffmpeg なし／H.265 なし）の活性状態を回帰テストする。
    - [tests/conftest.py](../../tests/conftest.py): `CapabilityReport` 生成箇所は新フィールドが既定値付きのため変更不要（必要に応じ ffmpeg 有りフィクスチャを追加）。

16. **[README.md](../../README.md) & [Documentation/README.md](../../Documentation/README.md)**
    - 動画圧縮機能、4タブ構成、`vendor/ffmpeg-windows/` の配置手順とライセンス同梱、元以上サイズ時の元ファイル維持、入力クリーンアップ対象への動画追加について追記する。

---

## Relevant files

- [shared/runtime_paths.py](../../shared/runtime_paths.py) — `resolve_ffmpeg_executable()` の追加先
- [backend/contracts.py](../../backend/contracts.py) — `VideoCompressionConfig`、`CapabilityReport`、`CompressionRequest`、`EventKind`（`video_progress`）の拡張
- [backend/capabilities.py](../../backend/capabilities.py) — `ffmpeg` 検出・エンコーダ検出・キャッシュ
- [backend/settings.py](../../backend/settings.py) — 動画圧縮の既定値・対象拡張子（正）・一時ファイル接頭辞
- `backend/core/video_utils.py` *(新規)* — `ffmpeg` サブプロセス実行、進捗パーサ、元維持判定、プロセス追跡、一時ファイル掃除
- `backend/services/video_service.py` *(新規)* — 動画圧縮サービス層の公開入口
- [backend/core/pdf_utils.py](../../backend/core/pdf_utils.py) — `_sanitize_subprocess_error()` の共通化元
- [backend/core/worker_ops.py](../../backend/core/worker_ops.py) — タスクタプル拡張（index 20〜22）、`final_outpath`、動画ディスパッチ
- [backend/orchestrator/job_runner.py](../../backend/orchestrator/job_runner.py) — 2パス出力パス確定、動画専用 executor、フォールバックコピー、CSV パス補正、`video_progress` 送出
- [frontend/settings.py](../../frontend/settings.py) — クリーンアップ対象拡張子（backend から派生）
- [frontend/ui_contracts.py](../../frontend/ui_contracts.py) — 動画 state・widget・新規タブの Protocol 定義
- [frontend/ui_tkinter_state.py](../../frontend/ui_tkinter_state.py) — 動画設定用 Tk 変数の初期化
- [frontend/ui_tkinter_mapper.py](../../frontend/ui_tkinter_mapper.py) — 品質→CRF 変換と `VideoCompressionConfig` 構築
- [frontend/ui_tkinter_view.py](../../frontend/ui_tkinter_view.py) — 「出力設定」タブの独立化（4タブ構成）と「動画圧縮設定」セクション
- [frontend/ui_tkinter_controller.py](../../frontend/ui_tkinter_controller.py) — 動画 UI 活性制御、進捗合成表示、開始ログ、終了時プロセス停止
- [frontend/config_data/locales/ja.json](../../frontend/config_data/locales/ja.json) / [frontend/config_data/locales/en.json](../../frontend/config_data/locales/en.json) — 日英ロケール文言
- [pjp_compressor.iss](../../pjp_compressor.iss) / [vendor_zip.ps1](../../vendor_zip.ps1) — 配布物構成の確認

---

## Verification

1. `pytest tests/unit/test_capabilities.py tests/unit/test_contracts.py tests/unit/test_ui_tkinter_mapper.py tests/unit/test_video_utils.py tests/unit/test_locale_catalog.py tests/unit/test_settings_split.py`
2. `pytest tests/integration/test_job_runner.py tests/integration/test_ui_controller.py tests/regression/test_tkinter_regression.py`
3. `pytest`（全体回帰）
4. `ffmpeg` 導入環境にて `.mp4` / `.mov` を含むフォルダを圧縮し、出力が `.mp4` に統一され、エンコード中に下部ステータスバーへ全体進捗と動画単体の進捗（`%`）が合成表示され、画像処理の完了でちらつかないことを確認する。
5. 以下の動画で手動確認する:
   - 奇数解像度（例: 1279x719）→ エラーなく偶数丸めで出力される
   - 音声なし動画 → `-map 0:a:0?` によりエラーなく出力される
   - 縦長・回転メタデータ付き動画 → 向きが保持される
   - webm（Vorbis/Opus）を `そのままコピー` 指定 → AAC 自動切替のログが出て出力される
   - 低ビットレートで出力が肥大化する動画 → **元の拡張子のまま元ファイルがコピー** され、CSV に `元ファイル維持` と記録される
   - 同一フォルダの `sample.mp4` と `sample.mov` → 上書きされず `sample.mp4` / `sample_mov.mp4` に出力される
6. 動画エンコード中にアプリを終了し、`ffmpeg` プロセスと `.pjp_tmp_*.mp4` が残らない（残った場合も次回ジョブ開始時に掃除される）ことを確認する。
7. `ffmpeg` 未検出環境（モックまたは一時リネーム）および libx265 非対応ビルドにてアプリを起動し、エラーなく起動して動画セクション全体（または H.265 のみ）が無効化され、PDF・画像圧縮が従来どおり動作することを確認する。
8. UI 上で「圧縮設定」「出力設定」「アプリ設定」「ログ・進捗」の4タブが正しく表示・遷移でき、既存の出力設定（CSV出力、ZIP展開/再圧縮、ミラーコピー等）が「出力設定」タブから問題なく機能することを確認する。

---

## Decisions

- **CPU負荷対策**: 汎用 `ThreadPoolExecutor` は維持し、動画タスクのみ **専用の単一ワーカー executor** で直列実行する。`Semaphore` 方式は汎用ワーカーが動画待ちで塞がり画像・PDF が停止するため採用しない。ffmpeg は `BELOW_NORMAL_PRIORITY_CLASS` で起動し UI 応答性を保つ。
- **品質設定のUI表現**: ユーザー向けには画像・PDFと同じ 0〜100 の品質スライダーを提示し、mapper 層で `CRF`（x264: 18〜40 / x265: 22〜44）へ変換する。backend 契約は `crf` のみを持つ。
- **出力コンテナ形式**: 圧縮に成功し元より小さくなった動画は `.mp4` に統一する。同名衝突は `stem_{ext}.mp4` 形式で回避する（大文字小文字非区別）。
- **元以上サイズ時の扱い**: 圧縮後サイズが元以上の場合は、**拡張子も含めて元ファイルをそのまま出力先へコピー** する（ミラー設定に関係なく実施し、`processed` として集計、CSV は `csv_action_video_kept_original`）。既存 Ghostscript の `pdf_gs_no_gain` と同じ方針。
- **失敗時の扱い**: ffmpeg 失敗時は未処理扱いとし、ミラーコピー有効時のみ **元拡張子のまま** フォールバックコピーする。
- **進捗表示**: `ffprobe` への追加依存は持たせず、`ffmpeg -progress pipe:1`（stderr を stdout へ統合して単一ループで読む）の出力と `Duration` ヘッダから単体進捗率を算出し、専用イベント `video_progress` で通知して controller が全体進捗と合成表示する。
- **タイムアウト**: 固定タイムアウトは設けず、アプリ終了時のプロセス終了で停止手段を担保する。ストール検知は将来課題。
- **エンコーダ互換**: ffmpeg 検出時に `-encoders` で libx264/libx265 の有無を確認し、非対応コーデックは UI で選択不可とする。H.265 出力には `-tag:v hvc1` を付与する。
- **タブ構成**: メインタブの肥大化を防ぐため、「出力設定」を独立した第2タブへ切り出す。
