# Plan: ffmpeg 動画圧縮機能の追加と UI タブ再編

**TL;DR**: `ffmpeg` を用いた動画ファイル一括圧縮を第3の圧縮ドメインとして追加する。外部ツール解決は既存の `system` 優先 → `bundled` (`vendor/ffmpeg-windows/`) 次点 → `unavailable`（UI無効化・劣化起動）の方式を踏襲し、保持条件の判定・出力検証に使う `ffprobe` も必須とする。アプリ内の圧縮ジョブは同時に1件、動画タスクは **専用の単一ワーカー `ThreadPoolExecutor(max_workers=1)`** で直列実行する。これは同時エンコード数の制限であり、CPU使用率の上限は保証しない。UIの品質スライダー（0〜100）は mapper 層で `CRF`（x264: 18〜40 / x265: 22〜44）へ変換する。**本編映像・全音声・全字幕と関連情報の保持をMP4統一より優先**し、保持条件を満たして元より小さくなる場合のみ `.mp4` を出力する。保持条件を満たせない場合と元以上サイズの場合は、ミラー設定に関係なく **元拡張子のままコピーし、元維持の理由を通知**する。音声の既定はコピーとし、HDR・字幕の装飾などを安全に保持できない入力は初版では元維持とする。停止フラグと出力フォルダ排他で終了・一時ファイル掃除を安全に行う。動画進捗は開始・更新・終了を区別するイベントで全体進捗と合成し、「出力設定」を独立させた4タブ構成とする。

---

## Steps

### Phase 1: 外部ツール解決とデータ契約・設定の拡張

1. **[shared/runtime_paths.py](../../shared/runtime_paths.py)** — `resolve_ffmpeg_executable()` / `resolve_ffprobe_executable()` の追加
   - `resolve_external_tool()` を使用し、`system_candidates=('ffmpeg',)`、`bundled_relative_candidates=('ffmpeg-windows/bin/ffmpeg.exe', 'ffmpeg-windows/ffmpeg.exe')` で解決する。
   - `ffprobe` も同様に、`system_candidates=('ffprobe',)`、`bundled_relative_candidates=('ffmpeg-windows/bin/ffprobe.exe', 'ffmpeg-windows/ffprobe.exe')` で解決する。

2. **[backend/contracts.py](../../backend/contracts.py)** — データ契約の拡張
   - `VideoCompressionConfig`（`frozen=True`）dataclass を新設する。backend は **`crf` のみを正** とし、UI の品質値（0〜100）は保持しない:
     - `enabled: bool = True`
     - `codec: Literal['libx264', 'libx265'] = 'libx264'`
     - `crf: int = 24`
     - `preset: str = 'medium'`
     - `audio_mode: Literal['aac', 'copy', 'none'] = 'copy'`
     - `audio_bitrate: str | None = None`（`None` はトラックごとのチャンネル数に応じたAACビットレートを採用）
     - `max_long_edge: int = 0`（`0` はリサイズなし）
   - backend の入口でも codec / CRF / preset / audio_mode / audio_bitrate / max_long_edge を検証する。`Literal` と dataclass だけでは実行時の入力を検証できないため、不正な dict / 値は明示的なエラーにする。
   - `CapabilityReport` に以下を追加する（既定値付きのため既存の位置引数呼び出しは無変更で動作する）:
     - `ffmpeg_path: str | None = None`
     - `ffmpeg_source: ToolSource = 'unavailable'`
     - `ffmpeg_encoders: frozenset[str] = frozenset()`
     - `ffprobe_path: str | None = None`
     - `ffprobe_source: ToolSource = 'unavailable'`
     - `ffmpeg_detection_error: str | None = None`
     - `ffprobe_detection_error: str | None = None`（検出失敗のサニタイズ済み詳細。供給元と使用可否を区別する）
     - `@property ffmpeg_available -> bool`（`ffmpeg_path` があり、検出エラーがなく、かつ `'libx264' in ffmpeg_encoders`）
     - `@property ffprobe_available -> bool`（`ffprobe_path` があり、検出エラーがない）
     - `@property video_available -> bool`（`ffmpeg_available` かつ `ffprobe_available`）
     - `@property ffmpeg_hevc_available -> bool`（`ffmpeg_available` かつ `'libx265' in ffmpeg_encoders`）
   - `EventKind` に `'video_progress'` / `'cancelled'` を追加し、`ProgressEvent` の末尾に `video_phase: Literal['started', 'updated', 'finished'] | None = None` を追加する。
     - 動画イベントは `kind='video_progress'`、`message=<ファイル名>`、`video_phase=<段階>`、`current=<pct | None>`。`current=None` は **割合不明のみ**を表し、表示のクリアは `video_phase='finished'` で行う。
     - `'cancelled'` はジョブの終端イベントで、途中までの集計値と中断メッセージを持つ。中断時に通常完了の `stats` イベントを送らない。
   - 実行制御用の `JobControl` を追加する（圧縮設定や永続化対象ではない）:
     - `cancel_event: threading.Event` と `launch_lock: threading.Lock` をジョブごとに生成する。
     - `request_cancel()` は `launch_lock` 内で `cancel_event.set()` する。動画サブプロセスの停止確認・起動・登録も同じロックで扱い、停止要求と起動の競合を防ぐ。
     - executor / 子プロセスの停止待ちはロック外で行う。`JobControl` を `CompressionRequest` の設定値には含めない。
   - `CompressionRequest` に `video_config: VideoCompressionConfig | None = None` を追加し、`to_legacy_kwargs()` にも `'video_config': self.video_config` を含める。

3. **[backend/capabilities.py](../../backend/capabilities.py)** — `ffmpeg` / `ffprobe` 可用性・エンコーダ検出の追加
   - `_detect_ffmpeg()` を追加し、解決できた場合は `ffmpeg -hide_banner -encoders` を1回実行（`CREATE_NO_WINDOW`、`timeout=10`）して `libx264` / `libx265` / `aac` の有無を収集する。
   - `_detect_ffprobe()` は解決後に `ffprobe -version` を実行して起動可否を確認する（`timeout=10`）。未検出と検出コマンドの失敗を区別し、失敗理由をUI・ログへ通知できるよう検出結果に保持する。ffmpeg の検出失敗も、理由なしで空集合へ置き換えない。
   - `detect_capabilities()` はジョブ開始ごとにも呼ばれるため、動画ツールの検出結果は `functools.lru_cache(maxsize=1)` でアプリ起動中キャッシュする。PATHやビルド変更の反映には再起動が必要と明記し、テストでは `cache_clear()` で初期化する。
   - `detect_capabilities()` の返却値に `ffmpeg_path` / `ffmpeg_source` / `ffmpeg_encoders` / `ffprobe_path` / `ffprobe_source` を含める。ジョブ開始時のレポートをワーカーへ渡し、ファイルごとに別の実行パスを再解決しない。

4. **[backend/settings.py](../../backend/settings.py) & [frontend/settings.py](../../frontend/settings.py)** — 既定値と対象拡張子の定義
   - `backend/settings.py` に動画既定値を追加する（**拡張子定義の正はここ**）:
     - `VIDEO_EXTENSIONS = frozenset({'mp4', 'mov', 'avi', 'mkv', 'webm', 'wmv', 'm4v'})`
     - `VIDEO_ENABLED_DEFAULT = True`
     - `VIDEO_QUALITY_DEFAULT = 75`（UI 用）
     - `VIDEO_CODEC_DEFAULT = 'libx264'`
     - `VIDEO_PRESET_DEFAULT = 'medium'`
     - `VIDEO_AUDIO_MODE_DEFAULT = 'copy'`
     - `VIDEO_AUDIO_BITRATE_DEFAULT = None`
     - `VIDEO_MAX_LONG_EDGE_DEFAULT = 0`
     - `VIDEO_TEMP_PREFIX = '.pjp_tmp_'`
     - `VIDEO_TEMP_ROOT_NAME = '.pjp_video_work'`（アプリ専用作業領域）
     - `OUTPUT_JOB_LOCK_FILENAME = '.pjp_job.lock'`
   - AAC自動ビットレートは共有ヘルパーでトラック単位に決定する。初版は1ch=96k、2ch=128k、3〜6ch=384k、7〜8ch=512kとし、未対応・不明のレイアウトは暗黙にダウンミックスしない。明示的な `audio_bitrate` 指定は優先する。
   - `frontend/settings.py` では `VIDEO_CLEANUP_EXTENSIONS = {f'.{e}' for e in VIDEO_EXTENSIONS}` を backend から派生させ、`INPUT_DIR_CLEANUP_EXTENSIONS` と `OUTPUT_DIR_CLEANUP_EXTENSIONS` に合流させる（二重定義によるズレを防止）。
   - 入力クリーンアップ対象に動画が加わることを README / リリースノートで周知する。

---

### Phase 2: Backend コア（保持条件判定・実行・キャンセル）の実装

5. **`backend/core/video_utils.py`**（新規作成） — `compress_video_ffmpeg()` の実装
   - 戻り値型を新設する:
     ```python
     @dataclass(frozen=True)
     class VideoCompressResult:
         ok: bool                 # 縮小出力または元維持の配置が完了したか
         message: str
         final_outpath: str | None  # 実際に配置したファイル（失敗時 None）
         kept_original: bool = False
         kept_original_reason: Literal['no_gain', 'retention'] | None = None
         cancelled: bool = False
     ```
   - シグネチャ:
     ```python
     def compress_video_ffmpeg(
         inpath: str,
         outpath: str,             # 予定出力先（.mp4、衝突回避済み）
         original_outpath: str,    # 入力と同じ拡張子の出力先（元維持時に使用）
         video_config: VideoCompressionConfig,
         *,
         capabilities: CapabilityReport,
         job_control: JobControl,
         temp_dir: Path,           # 排他取得済みのジョブ専用作業領域
         progress_callback: Callable[[int | None], None] | None = None,
         log_language: str = 'ja',
     ) -> VideoCompressResult:
     ```
   - `capabilities` の確定済みパスを使用し、ffmpeg / ffprobe が使用不可なら `ok=False` と具体的な理由を返す。
   - **入力解析**: `ffprobe -v error -show_format -show_streams -show_chapters -of json <input>` を実行し、JSONの型・必須情報を検証する。映像・音声・字幕、言語・タイトル・disposition、チャンネル数・レイアウト、チャプター、回転、色特性・HDR関連side data、総尺を取得する。解析失敗・不正JSONは通常の処理失敗として通知し、「保持成功」に置き換えない。
   - **保持範囲と事前判定**:
     - 本編映像は最初の非カバー映像のみ。全音声・全字幕と、関連する言語・トラック名・既定／強制選択状態・チャプターを保持対象にする。追加映像やカバーアートは初版の保持対象外であることを明記する。
     - 音声の既定はコピー。明示的なAAC指定と、通知付きのコピー非対応トラックのAAC変換は音質完全維持の例外とする。`none` 指定時だけ全音声の削除を許可する。チャンネル数・レイアウトを暗黙に変えない。
     - 字幕を黙って削除・焼き込みしない。初版の字幕コピー対象は `mov_text` に限定し、全字幕をMP4へコピー可能な場合のみエンコードする。
     - SRT等は `mov_text` へ変換可能だが装飾の完全保持を保証できず、初版では字幕変換・装飾損失を許可するUIを設けないため元維持とする。ASS/SSAの装飾・位置指定、PGS等の未対応字幕、ASS関連の添付フォントを必要とする入力も元維持とする。MP4の対応可否を字幕形式全般に対して一律に断定しない。
     - PQ / HLG、Dolby Vision等のHDR関連情報を検出した入力は初版では元維持とする。`yuv420p` への変換をHDR→SDRトーンマッピングとは扱わない。
     - 保持対象の情報を採用ビルド・MP4で表現できないと判定した場合は、エンコードを省略して元維持とする。理由をログ・CSVへ残す。MKV自動選択とHDR変換は将来課題。
   - **一時ファイル**: `temp_dir` 内に `f'{VIDEO_TEMP_PREFIX}{uuid4().hex}.mp4'` を生成する。作業領域は出力と同じファイルシステムに配置し、正常配置には `replace` を使う。`try/finally` で一時ファイルを削除し、削除失敗はパスをサニタイズして通知する。
   - **ffmpeg 引数構成**:
     ```python
     cmd = [
         ffmpeg_path, '-hide_banner', '-nostdin', '-y',
         '-i', inpath,
         '-map', '0:V:0',
         *audio_map_args,
         '-map', '0:s?',
         '-vf', vf,
         '-c:v', codec, '-crf', str(crf), '-preset', preset,
         '-pix_fmt', 'yuv420p',
         *(['-tag:v', 'hvc1', '-x265-params', 'log-level=error'] if codec == 'libx265' else []),
         *audio_args,
         *subtitle_args,
         *stream_metadata_args,
         '-map_metadata', '0',
         '-map_chapters', '0',
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
     - 音声ありの場合は `audio_map_args=['-map', '0:a?']` で全音声を選択する。`none` 指定時はマップを省略して `-an` とする。
     - `audio_args` はトラック別に作る。コピー対象は `-c:a:<index> copy`、AAC対象は `-c:a:<index> aac -b:a:<index> <bitrate>`。`-ac 2` 等による無断ダウンミックスはしない。
     - `subtitle_args` は字幕ありの場合 `['-c:s', 'copy']`。`stream_metadata_args` は選択した入力・出力トラックの対応に基づいて言語・タイトル・dispositionを維持する。グローバルな `-map_metadata 0` だけで保持完了と判断しない。
     - 回転メタデータは自動回転後の映像と整合させ、二重回転を防ぐ。
   - **サブプロセス起動と進捗パース**（stdout/stderr の片側詰まりによるデッドロック防止）:
     ```python
     proc = subprocess.Popen(
         cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
         text=True, encoding='utf-8', errors='replace',
         creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)
                       | getattr(subprocess, 'BELOW_NORMAL_PRIORITY_CLASS', 0),
     )
     ```
     - 総尺 `total_us` はffprobe JSONの有限な正の duration を使用する。欠落・不明なら割合不明として扱い、stderrの `Duration` ヘッダには依存しない。
     - 単一ループで行を読み、以下をパースする:
       - `out_time_us=(\d+)`（`N/A` は無視）→ `pct = min(99, max(0, int(current_us * 100 / total_us)))`
       - `progress=end` → エンコード進捗の終了。成功判定は終了コード・出力検証・配置後に行う。
     - 総尺不明時は `progress_callback(None)` で処理中・割合不明を通知する。開始・終了イベントとは区別する。
     - UI へのイベント過多を防ぐため、割合既知時は前回通知から `1%` 以上増加かつ `0.2秒` 以上経過したときのみ通知する。不明時は初回通知のみとする。開始・終了イベントは間引かない。
     - 失敗時の詳細表示用に、出力末尾を `collections.deque(maxlen=30)` で保持する。整形は [backend/core/pdf_utils.py](../../backend/core/pdf_utils.py) の `_sanitize_subprocess_error()` を共通ユーティリティへ切り出して再利用する（内部パス露出抑止・240文字制限）。
   - **タイムアウト**: エンコードに固定タイムアウトは設けない。ファイル解析・出力検証のffprobeには `timeout=30` を設け、タイムアウトを処理失敗として通知する。ffprobeもプロセス追跡・キャンセルの対象にする。ストール検知は将来課題とする。
   - **音声 copy の限定フォールバック**:
     - 採用ビルドのMP4対応と入力解析によりコピー非対応が確定したトラックだけをAACに変更する。実行失敗から再試行する場合も、エラーが特定トラックのコピー非対応に起因すると確認できた場合に限定し、再試行は1回まで。
     - 映像・字幕・ディスク・権限・中断等の失敗はAAC再試行しない。AACエンコーダなし、または音声レイアウトを維持できない場合は、保持条件による元維持とする。
     - Opus / Vorbis等を一律に「MP4へコピー不可」としない。現行FFmpegのMP4 muxerには対応するコーデックもあり、採用ビルドの格納可否と再生機器の互換性を分けて扱う。
     - AAC切替は対象トラック・理由・ビットレートを通知し、停止要求後は再試行しない。
   - **出力検証**: 配置前にffprobeで一時出力を解析する。本編映像、全音声・全字幕の対応、言語・タイトル・既定／強制選択状態、音声チャンネル数・レイアウト、チャプター、回転を入力解析結果と比較する。字幕コピーは字幕内容・タイミングも採用ビルドの実ファイルテストで検証する。保持条件違反は元維持へ切り替え、解析自体の失敗・破損出力は通常失敗とする。
   - **結果の配置**:

     | ケース | 配置 | 戻り値 |
     |---|---|---|
     | 保持条件を満たす成功・`temp_size < orig_size` | `temp_out.replace(outpath)` | `ok=True, final_outpath=outpath` |
     | 成功・`temp_size >= orig_size` | 一時ファイル削除 → 元ファイルを元拡張子で配置（ミラー設定に関係なく実施） | `ok=True, kept_original=True, kept_original_reason='no_gain'` |
     | 事前判定または出力検証で保持条件を満たせない | 一時ファイル削除 → 元ファイルを元拡張子で配置（ミラー設定に関係なく実施） | `ok=True, kept_original=True, kept_original_reason='retention'` |
     | ffmpeg 失敗 | 一時ファイル削除のみ（コピー要否は job_runner が判断） | `ok=False, final_outpath=None` |
     | キャンセル | 一時ファイル削除のみ。再試行・元維持・フォールバックコピーを行わない | `ok=False, final_outpath=None, cancelled=True` |

   - 元維持時の `final_outpath` は常に `original_outpath` とする。元コピーは停止確認付きのブロック単位コピーと `shutil.copystat` でジョブ一時領域へ作成してから配置し、不完全なコピーで既存成果物を上書きしない。長大な動画のコピー中も停止可能にし、コピー・配置失敗は `ok=False` として通知する。
   - 処理開始、解析後、再試行前、コピー前、最終配置前で停止を確認する。最終配置の停止確認と `replace` は `launch_lock` 内で行い、停止要求受理後の配置を防ぐ。停止前に配置済みの成果物は残す。
   - **実行中プロセスの追跡**: ffmpeg / ffprobeを所有する `JobControl` と対応付けて追跡する。`launch_lock` 内で停止確認→`Popen`→登録を行う。停止要求受理後に新しいプロセスを起動しない。
   - `terminate_active_video_processes(job_control: JobControl, timeout: float = 3.0) -> None` を提供する。対象ジョブの停止要求後、スナップショットを取得し、ロック外で `terminate()` → `wait(timeout)` → 残存時 `kill()` → `wait()` を行って回収する。正常終了・例外とも追跡解除し、停止失敗も通知する。
   - **残留一時ファイル掃除**: `cleanup_stale_video_temps(output_dir: Path) -> int` は出力排他取得中だけ呼ぶ。専用作業領域の所有マーカーを確認した過去ジョブのUUIDディレクトリだけを削除する。出力ツリー全体の接頭辞一致ファイル、所有不明のディレクトリ、作業領域外を指すリンクは削除しない。

6. **`backend/services/video_service.py`**（新規作成）
   - 既存 [backend/services/pdf_service.py](../../backend/services/pdf_service.py) と同じ構成で、`compress_video_ffmpeg` / `terminate_active_video_processes` / `cleanup_stale_video_temps` を公開する。
   - **`backend/orchestrator/job_lock.py`**（新規作成）に出力排他の取得・解放を実装する。Windows標準の `msvcrt.locking` による非ブロッキングのOSファイルロックを使い、PIDの記録だけを排他判定に使わない。
     - 解決済み出力ルートの `OUTPUT_JOB_LOCK_FILENAME` を全圧縮ジョブ・出力クリーンアップで共有する。取得失敗は処理中である旨を通知し、走査・掃除・CSV作成・コピー等を開始しない。
     - ロックファイルは解放後も残し、削除・再作成による排他の分断を避ける。プロセス異常終了時はOSがロックを解放する。
     - ジョブの走査前から全executorの終了・ZIP再生成・CSV閉鎖・一時領域掃除まで保持し、`finally` で解放する。
     - 排他取得→過去作業領域掃除→`output_base / VIDEO_TEMP_ROOT_NAME / <job_uuid>` と所有マーカー生成の順に行う。現在ジョブの作業領域は終了時に後片付けする。

---

### Phase 3: ワーカー・オーケストレータの統合（直列実行・安全な配置・進捗通知）

7. **[backend/core/worker_ops.py](../../backend/core/worker_ops.py)** — タスク拡張と動画ディスパッチ
   - **タスクタプルの拡張**: 既存 index 0〜19 は変更せず、末尾に6要素を追加する（job_runner の `task[16..18]` 参照は維持される）。

     | index | 要素 |
     |---|---|
     | 20 | `video_config: VideoCompressionConfig \| None`（動画処理しない場合 `None`） |
     | 21 | `video_progress_callback: Callable[[int \| None], None] \| None` |
     | 22 | `original_outpath: str`（入力と同じ拡張子の出力先） |
     | 23 | `job_control: JobControl \| None`（新APIでは全タスクに共通の制御を渡す） |
     | 24 | `capabilities: CapabilityReport \| None` |
     | 25 | `video_temp_dir: str \| None` |

     旧形式（20要素）互換のため、切り詰めは次の形にする:
     ```python
     args = tuple(args[:26]) + (None,) * max(0, 26 - len(args))
     ```
   - `WorkerFileResult` の末尾に `final_outpath: str | None = None`、`kept_original_reason: Literal['no_gain', 'retention'] | None = None`、`cancelled: bool = False` を追加する。
   - `process_single_file()` は最初に停止確認し、未開始タスクは中断結果を返す。`ext in VIDEO_EXTENSIONS and video_config is not None` の場合に `compress_video_ffmpeg()` を呼び出す。必要な capabilities / job_control / temp_dir の欠落は明示的な契約エラーとし、無効な動画タスクを通常成功にしない。
     - `ok=True` → `processed=True`、`final_outpath` を設定。`out_size` は `final_outpath` のサイズを採用する。
     - `ok=False` → `processed=False`。`cancelled` は結果に伝搬し、中断と実行失敗を区別する。
   - `_csv_action_key()` に動画分岐を追加する: 圧縮成功 `'csv_action_video'`、サイズ理由の元維持 `'csv_action_video_kept_original'`、保持条件による元維持 `'csv_action_video_kept_retention'`、中断 `'csv_action_cancelled'`。元維持を「圧縮成功」と表示しない。
   - 動画タスクの開始・終了通知は job_runner 側のラッパーで扱う（Step 8）。

8. **[backend/orchestrator/job_runner.py](../../backend/orchestrator/job_runner.py)** — 出力パス確定・executor 分離・進捗連携
   - `_tool_detection_summary()` に `ffmpeg` / `ffprobe` の検出結果（`system` / `bundled` / `unavailable`）と検出失敗理由を追加する。ジョブで確定した同じレポートを使用する。
   - `run_compression_job()` に以下の引数を追加する:
     - `video_config: VideoCompressionConfig | dict[str, Any] | None = None`（dict は `VideoCompressionConfig(**d)` へ正規化）
     - `event_func: Callable[[ProgressEvent], None] | None = None`（`video_progress` 送出用）
     - `job_control: JobControl | None = None`（未指定時はジョブ内で生成。GUIからは追跡可能な共通インスタンスを渡す）
   - **実行ライフサイクル**: Step 6の出力排他を取得してから走査・掃除・ZIP展開・CSV作成を始める。キャンセル済みなら開始しない。終了・例外・中断とも `finally` でCSV、一時ZIP展開領域、動画一時領域、出力ロックを後片付けする。
   - **動画処理可否の一括判定**（ジョブ開始時に1回）: `video_config is not None` かつ `video_config.enabled` かつ `report.video_available` かつ選択コーデックが `report.ffmpeg_encoders` に含まれる場合のみ有効とする。未検出・検出失敗・コーデック非対応の理由をログ出力する。AACエンコーダの有無は音声処理の必要時に判定する。
   - **出力パス確定（2パス方式・同名衝突回避）**:
     1. `append_task()` は **候補（入力パス・既定出力パス・CSV 文脈）を収集するだけ** とする（通常走査分・ZIP 展開分の両方）。
     2. `claimed: set[str]`（キーは `str(path).casefold()`、Windows の大文字小文字非区別に対応）を用意する。
     3. まず全候補の既定出力パスを `claimed` に登録する。動画の `original_outpath` も元維持・失敗時コピーの予約先として確保する。ZIP由来と通常ファイルが同じ既定出力パスを要求する場合も、重複を黙って上書きせず割当時に解消する。
     4. 次に拡張子が変わる動画（`.mov` / `.m4v` 等）について、`stem.mp4` → `stem_{ext}.mp4` → `stem_{ext}_2.mp4` → … の順に空き名を割り当てる。
     5. 確定パスでタスクタプルを構築する。`original_outpath` には衝突解消済みの元拡張子出力パスを入れる。予約先を含む最終出力パスとCSVパスの対応を保持する。既存出力の上書き方針は従来動作を維持し、新規変換名の候補は既存ファイルとも衝突させない。
   - **executor 分離**（Semaphore は使わない。全汎用ワーカーが動画待ちで塞がり画像・PDF が停止する問題を回避）:
     ```python
     with ThreadPoolExecutor(max_workers=max_workers) as general_ex, \
          ThreadPoolExecutor(max_workers=1, thread_name_prefix='pjp-video') as video_ex:
         futures = {general_ex.submit(process_single_file, t): t for t in general_tasks}
         futures.update({video_ex.submit(run_video_task, t): t for t in video_tasks})
         for future in as_completed(futures):
             ...  # 既存ループを維持
     ```
     - 上記は通常時の概念図。実装では停止を監視し、未開始futureを `cancel()` する。キャンセル済みfutureを完了待ち集合から除外し、`as_completed()` にキャンセル済みfutureだけが残って終了待ちし続けないようにする。
     - `run_video_task` は停止確認後に `video_phase='started', current=None` を送出して処理を呼び、`finally` で `video_phase='finished'` を送出する。
     - index 21 のコールバックは `video_phase='updated', current=pct` を送出する。割合不明の `None` も更新として扱い、開始・終了と混同しない。`event_func` 未指定時は `None`。
     - 停止要求後は未開始処理・AAC再試行・フォールバックコピー・ZIP再生成を行わない。実行中の画像・PDFは既存処理の終了を待ち、未開始タスクは全executorでキャンセルする。停止前に配置された成果物は残す。
     - executorのスレッドは終了待ちの対象になるため、親圧縮スレッドの `daemon=True` を終了保証に使わない。出力排他はexecutorの終了前に解放しない。
   - **フォールバックコピー**: 中断ではない `processed=False` かつ `copy_non_target_files` の場合、動画タスクは **`original_outpath`（元拡張子）へコピー** する。停止確認をコピー前・配置前に行い、一時領域から配置する。
   - **保持条件による元維持**: ミラー設定に関係なく実施し、配置できた場合のみ `processed` 集計に含める。圧縮成功・サイズ理由の元維持・保持条件の元維持をログ・CSVで区別し、具体的な保持不可理由をnotesへ記録する。
   - **CSV 出力パス**: `result.final_outpath` がある場合、CSV の `output_path` 列のファイル名をそれに差し替える:
     ```python
     if result.final_outpath:
         csv_output = Path(result.final_outpath).relative_to(output_base).as_posix()
     ```
     同様に、フォールバックコピー時は実際の元拡張子出力パスを記録する。通常入力でもZIP由来でも、ファイル名だけでなく衝突解消後の相対パス全体を記録する。中断・失敗で配置されていない場合は成果物があるようなCSVを作らない。
   - `compressible_extensions` は、動画処理有効時のみ `VIDEO_EXTENSIONS` を合流させる（無効時は動画を「対象外」としてミラーコピー扱い）。
   - `_csv_action_label()` に動画圧縮・サイズ理由／保持条件による元維持・中断の各ラベルを追加する。
   - 中断時は部分集計を伴う `cancelled` イベントを送り、通常の完了ログ・完了統計を送らない。旧コールバックAPIでも中断理由をログへ通知する。
   - `run_compression_request()`:
     - `job_control: JobControl | None = None` 引数を追加する。`run_compression_job(...)` に **`video_config=request.video_config`、`event_func=event_callback`、`job_control=job_control` を明示的に渡す**（同関数は `to_legacy_kwargs()` を経由しないため）。

---

### Phase 4: Frontend（UI 4タブ化・動画設定セクション・品質→CRF変換・進捗合成）

9. **[frontend/ui_tkinter_state.py](../../frontend/ui_tkinter_state.py) & [frontend/ui_contracts.py](../../frontend/ui_contracts.py)** — UI State と Protocol 定義
   - `initialize_ui_state()` に動画設定用の Tk 変数を追加する:
     - `video_enabled: tk.BooleanVar`（既定 `True`）
     - `video_quality: tk.IntVar`（既定 `75`）
     - `video_codec: tk.StringVar`（既定 `'libx264'`）
     - `video_preset: tk.StringVar`（既定 `'medium'`）
     - `video_audio_mode: tk.StringVar`（既定 `'copy'`）
     - `video_max_long_edge: tk.StringVar`（既定 `'0'`）
   - `CompressionRequestAppProtocol` と `TkUiControllerHostProtocol`、view mixinの属性宣言に動画用 state 変数・ウィジェット・`output_settings_tab` を追加する。
   - controller は実行中 `JobControl`、ジョブ実行中フラグ、終了要求フラグを保持する。開始・入力／出力クリーンアップボタンを属性として保持し、実行中の活性制御に使用する。

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
    - 音声モードの表示名と backend 値は対応表で変換する。既定は `copy`、AACビットレートはUIに固定128kbpsとして表示せず `None`（チャンネル数に応じた自動値）を渡す。
    - `max_long_edge` は既存の `to_non_negative_int(..., max_value=MAX_RESIZE_DIMENSION)` で正規化する。

11. **[frontend/ui_tkinter_view.py](../../frontend/ui_tkinter_view.py)** — 「出力設定」タブの分離と「動画圧縮設定」の構築
    - `_build_notebook()` を4タブ構成に更新する:
      1. `圧縮設定` (`self.settings_tab`)
      2. `出力設定` (`self.output_settings_tab`) **← 新設**
      3. `アプリ設定` (`self.app_settings_tab`)
      4. `ログ・進捗` (`self.log_tab`)
    - 従来 `_build_settings_tab()` 末尾で呼んでいた `self._build_output_section()` を `self.output_settings_tab` 配下へ移動する。
    - `_build_settings_tab()` 内に `_build_video_section()`（背景色 `#f1fff4` の `LabelFrame`）を新設し、以下のコントロールを配置する:
      - `ffmpeg` / `ffprobe` 検出状態ラベル (`self.video_engine_status_var`)
      - 「動画を圧縮する（保持可能な場合は.mp4形式で出力）」Checkbutton
      - 動画品質スライダー（0〜100、現在値と変換後 CRF 目安を表示）
      - 映像コーデック選択 Radiobutton（`H.264 (高互換)` / `H.265 (高圧縮)`）
      - エンコード速度 Preset Combobox（`ultrafast` / `fast` / `medium` / `slow`）
      - 音声処理 Combobox（`そのままコピー（非対応トラックのみ AAC へ切替）` / `AAC（チャンネル数に応じたビットレート）` / `音声なし（全音声を削除）`）。既定はコピー。
      - 長辺リサイズ上限 Combobox（`変更なし` / `3840` / `1920` / `1280` / `854`）
      - 注記: 「全音声・全字幕を保持します。保持できない場合や圧縮後に元より大きくなる場合は元ファイルをそのまま出力します」
      - 注記: 「初版のHDR・字幕変換が必要な動画は元維持です。AAC変換は音質が変わり、音声なしは全音声を削除します」
      - Preset / 音声 / 長辺のComboboxは選択式 `readonly` とし、表示文言をbackend値として直接渡さない。

12. **[frontend/ui_tkinter_controller.py](../../frontend/ui_tkinter_controller.py)** — 動画 UI 活性制御・進捗合成・終了処理
    - `_update_video_controls()` を追加する:
      - `capabilities.video_available` が `False`（ffmpeg / ffprobe 未検出・検出失敗、または libx264 非対応）のときは動画セクション全体を `disabled` にして具体的な理由を表示する。
      - `ffmpeg_hevc_available` が `False` のときは H.265 Radiobutton のみ `disabled` にし注記を表示する（選択中なら `libx264` へ戻す）。
      - 利用可能時は `video_enabled` トグルに応じて子ウィジェットを切り替える。Comboboxの有効状態は `readonly`、その他の操作部品は `normal` とし、H.265不可状態を後から有効化しない。
    - `_refresh_video_engine_status()` を新設し、`ffmpeg` / `ffprobe` の供給元（`system` / `bundled` / `unavailable`）、検出失敗理由、H.265可否を表示する。
    - **[frontend/ui_tkinter.py](../../frontend/ui_tkinter.py)** の `App.__init__()` で、レイアウト構築後に `_refresh_video_engine_status()` / `_update_video_controls()` を呼ぶ。起動直後から正しい活性状態にする。
    - **動画進捗の合成表示**（ステータスのちらつき防止）:
      - controller に `self._video_progress: tuple[str, int | None] | None` と最新の全体進捗件数 `(current, total)` を保持する。新規ジョブ開始時に両方を初期化する。
      - `_on_progress_event()` はイベント全体の処理を既存の `_schedule_on_ui_thread()` 経由でメインスレッドへ中継する。動画状態・全体件数の変更と再描画もメインスレッドに統一する。
      - `video_phase='started'` / `'updated'` で状態を設定し、`'finished'` でクリアする。`current=None` の開始・更新は割合不明であり、表示を消さない。
      - `_update_progress_ui()` は `t('status_processing', ...)` に、動画進捗がある場合 `t('status_video_suffix', name=..., pct=...)`（総尺不明時は `t('status_video_suffix_nopct', name=...)`）を連結して表示する。
      - `stats` / `error` / `cancelled` の終端イベント受信時に動画状態をクリアし、開始・クリーンアップ操作を復帰させる。中断は部分集計と中断状態を表示し、通常完了の文言を使わない。
    - **二重起動防止**: `start_compress()` はジョブ実行中・終了要求中なら開始を拒否して通知する。スレッド開始前に実行中フラグと新しい `JobControl` を設定し、開始ボタンを無効化する。例外時も活性状態を復帰させる。
    - 実行中は入力・出力クリーンアップを無効化し、メソッド入口でも拒否する。クリーンアップ実行中も圧縮開始を拒否する。出力クリーンアップはbackendと同じ出力排他を取得してから実施し、別インスタンスの処理中出力を削除しない。
    - `start_compress()` に動画設定の開始時ログを追加する（例: `動画: H.264 / 品質 75 (CRF 24) / preset=medium / 音声=copy / 長辺=変更なし / ffmpeg=system / ffprobe=system`）。
    - **終了処理**: `on_exit()` は既存の確認ダイアログを維持する。確認後は終了要求フラグを設定して操作を無効化し、`JobControl.request_cancel()` → 未開始タスクのキャンセル → 実行中ffmpeg / ffprobeの停止・回収 → ワーカーの後片付け完了を待つ。
      - プロセス停止・スレッド終了待ちでメインスレッドをブロックしない。停止処理は補助スレッドで行い、Tkの `after()` で終了状態を確認する。
      - Tkイベントループはワーカーとイベント中継が終わるまで維持し、その後に `host.destroy()` を呼ぶ。終了前に全executorが終了し、ロック・一時ファイルが解放されたことを確認する。
      - 停止失敗はログ・UIへ通知して状態を維持する。`daemon=True`、`shutdown(wait=False)`、`atexit` だけで安全に終了できると仮定しない。

---

### Phase 5: 多言語カタログ・ビルド定義・テスト・ドキュメントの更新

13. **[frontend/config_data/locales/ja.json](../../frontend/config_data/locales/ja.json) & [frontend/config_data/locales/en.json](../../frontend/config_data/locales/en.json)**
    - 日英両方に以下を追加する:
      - タブ・セクション: `tab_output`、`section_video_settings`、動画UIラベル群・注記
      - CSV アクション: `csv_action_video`、`csv_action_video_kept_original`、`csv_action_video_kept_retention`、`csv_action_cancelled`
      - ステータス: `status_video_suffix`、`status_video_suffix_nopct`、中断・終了待ち
      - ログ: `video_ffmpeg_missing`、`video_ffprobe_missing`、検出／解析／出力検証失敗、`video_success`、`video_kept_original`、保持不可の具体的理由、`video_failed`、`video_audio_copy_fallback`、`video_codec_unavailable`、`log_video_settings`
      - 排他・停止: 二重起動拒否、出力使用中、クリーンアップ拒否、中断、停止／一時ファイル削除失敗
      - 検出: `capability_ffmpeg_label`、`capability_ffprobe_label`、H.265非対応注記

14. **ビルド・配布**
    - [compressor_launcher_tkinter.spec](../../compressor_launcher_tkinter.spec): `vendor/` 全体を同梱済み。ffmpeg / ffprobeと必要なDLL・ライセンス資料が含まれ、新規Pythonモジュールも収集されることを確認する。
    - [pjp_compressor.iss](../../pjp_compressor.iss) / [vendor_zip.ps1](../../vendor_zip.ps1): `vendor/ffmpeg-windows/` を含めた配布物の構成・実サイズ・インストール時間を確認する。凍結アプリで実行パス解決と両ツールの起動を検証する。
    - **採用ビルド**: ffmpeg / ffprobeは同じ配布ビルドで揃え、バージョン、入手元、ハッシュ、ビルド設定、libx264 / libx265 / AAC等の依存・ライセンスを固定する。`--enable-nonfree` ビルドは採用しない。
    - **ライセンス・対応ソース**: LICENSEの同梱だけで完了としない。配布バイナリに対応するFFmpeg・外部ライブラリのソース、適用パッチ、ビルド設定・再現情報を、採用ライセンスに従って提供できるようにする。単なる上流トップページや消失し得る第三者URLだけに依存しない。
    - GPLビルドと本体AGPL-3.0の関係は配布構成に基づいて確認し、互換性と対応ソース提供義務を別に扱う。ダウンロード案内・配布ドキュメントにもライセンスと対応ソース入手方法を記載する。

15. **テストの追加・更新**
    - `tests/unit/test_video_utils.py`（新規）:
      - コマンド生成（`-map 0:V:0`、全音声 `0:a?`、全字幕 `0:s?`、`-map_chapters 0`、`-nostdin`、`-y`、`-pix_fmt`、libx265 時の `-tag:v hvc1`）
      - 映像フィルタ式（リサイズ有無、偶数丸め）
      - ffprobe JSONの型・HDR・音声／字幕／チャプター解析、不正JSON・タイムアウト・解析失敗の明示通知
      - ffprobe duration / `out_time_us` / `N/A` / `progress=end` と割合既知・不明の間引き条件
      - コピー非対応トラックだけのAAC切替と再試行上限。映像失敗・ディスクエラー・中断時には再試行しないこと
      - AAC自動ビットレートの1ch / 2ch / 6ch / 8ch、チャンネル数・レイアウト維持、未対応レイアウトを無断変換しないこと
      - 全字幕コピー、字幕変換・添付フォント・HDR等の保持条件による元維持、出力検証不一致時の元維持
      - 縮小成功時の `.mp4` 配置、サイズ／保持条件による **元拡張子でのコピー**（`final_outpath` / `kept_original_reason`）、失敗時の一時ファイル削除
      - コピー途中・最終配置前のキャンセル、既存成果物の維持、コピー／配置／削除失敗の通知
      - 起動と停止要求を競合させても停止後にffmpeg / ffprobeが起動しないこと、`kill()` 後の回収
      - 残留掃除が所有マーカー付きの過去作業領域だけを対象とし、所有不明ファイル・領域外リンクを削除しないこと
    - `tests/unit/test_job_lock.py`（新規）: 同一出力への別プロセスの取得拒否、解放後の取得、所有プロセス異常終了後の取得、ロックファイルを削除しないこと。
    - [tests/unit/test_capabilities.py](../../tests/unit/test_capabilities.py): ffmpeg / ffprobeの解決順序、実行失敗と未検出の区別、エンコーダ検出、`cache_clear()` 運用。
    - [tests/unit/test_contracts.py](../../tests/unit/test_contracts.py) & [tests/unit/test_ui_tkinter_mapper.py](../../tests/unit/test_ui_tkinter_mapper.py): CRF境界値、コピー既定・自動ビットレート、設定伝搬・不正値検証、`video_available`、段階付き動画イベントと中断イベント、`JobControl` のジョブ間非共有。
    - [tests/integration/test_job_runner.py](../../tests/integration/test_job_runner.py):
      - 保持可能な `.mov` 等の `.mp4` 出力と CSV `output_path` の一致
      - 同名衝突回避（`sample.mp4` と `sample.MOV`、`sample_mov.mp4` 既存時、元維持の予約先、ZIP由来と通常入力の既定パス重複）
      - 失敗時フォールバックコピーが元拡張子になること
      - サイズ／保持条件による元維持がミラー設定なしでも配置され、実配置後のみ `processed` 集計され、CSVアクション・理由が区別されること
      - 動画 executor が単一ワーカーで直列実行され、かつ画像タスクがブロックされないこと（遅延モックで検証）
      - `video_progress` の開始・更新・終了、割合不明の送出
      - 未開始futureのキャンセルで完了待ちが停止せず、次のプロセス・再試行・コピー・ZIP再生成が始まらないこと
      - 中断の部分集計、通常完了ログ・イベントの抑止、CSV・ZIP展開領域・動画一時領域・出力排他の解放
      - 排他取得失敗時に掃除・CSV作成・コピーを行わないこと
      - `run_compression_request()` 経由で設定・実行制御が届くこと、旧20要素タスクとの互換
    - [tests/integration/test_ui_controller.py](../../tests/integration/test_ui_controller.py): 割合不明を含む進捗合成・メインスレッド中継、二重開始・クリーンアップ拒否、終了確認の拒否／承認、停止待ち中のイベントループ維持、後片付け完了後のdestroyを検証する。
    - [tests/regression/test_tkinter_regression.py](../../tests/regression/test_tkinter_regression.py): 4タブ構成、起動直後のffmpegなし／ffprobeなし／H.265なし／動画無効状態、Comboboxの `readonly` 復帰を検証する。
    - [tests/conftest.py](../../tests/conftest.py): `CapabilityReport` 生成箇所は新フィールドが既定値付きのため変更不要（必要に応じ ffmpeg 有りフィクスチャを追加）。
    - `tests/integration/test_video_ffmpeg.py`（新規、`requires_external`）: 採用ビルドで生成した短尺動画を実処理し、本編選択、全音声・全字幕の言語／選択状態、音声レイアウト、字幕本文・装飾・表示タイミング、チャプター、回転を検証する。保持不能入力では元コピーのハッシュ一致を検証する。必要なツール／エンコーダがない環境は理由付きでskipする。

16. **[README.md](../../README.md) & [Documentation/README.md](../../Documentation/README.md)**
    - 動画圧縮機能、4タブ構成、ffmpeg / ffprobeの配置・検出キャッシュ、ライセンスと対応ソース入手方法を追記する。
    - 保持範囲（最初の本編映像・全音声・全字幕・関連情報）、コピー既定、AAC／音声削除の例外、HDR／字幕変換が必要な入力の元維持、MP4格納可否と再生互換性の違いを明記する。
    - サイズ／保持条件による元維持はミラー設定に関係なく実施し、通常の処理失敗はミラー設定に従うこと、同時1ジョブ・出力排他・キャンセルの扱い、CPU使用率上限を保証しないことを説明する。
    - 入力クリーンアップ対象への動画追加は取り消せない削除範囲の変更としてREADME・リリースノートで周知する。

---

## Relevant files

- [shared/runtime_paths.py](../../shared/runtime_paths.py) — ffmpeg / ffprobeのパス解決
- [backend/contracts.py](../../backend/contracts.py) — 動画設定・ツール可用性・段階付き進捗／中断イベント・`JobControl`
- [backend/capabilities.py](../../backend/capabilities.py) — ffmpeg / ffprobe検出・失敗理由・エンコーダ検出・キャッシュ
- [backend/settings.py](../../backend/settings.py) — 動画既定値・対象拡張子・作業領域・ロック名
- `backend/core/video_utils.py` *(新規)* — 保持条件解析・出力検証・全音声／字幕・限定AAC切替・元維持・キャンセル・プロセス回収
- `backend/services/video_service.py` *(新規)* — 動画圧縮サービス層の公開入口
- `backend/orchestrator/job_lock.py` *(新規)* — 出力フォルダのOS排他ロック
- [backend/core/pdf_utils.py](../../backend/core/pdf_utils.py) — `_sanitize_subprocess_error()` の共通化元
- [backend/core/worker_ops.py](../../backend/core/worker_ops.py) — タスク拡張（index 20〜25）・実配置結果・元維持理由・中断
- [backend/orchestrator/job_runner.py](../../backend/orchestrator/job_runner.py) — 出力排他・パス予約・executor分離／キャンセル・CSV整合・確実な後片付け
- [frontend/settings.py](../../frontend/settings.py) — クリーンアップ対象拡張子（backend から派生）
- [frontend/ui_contracts.py](../../frontend/ui_contracts.py) — 動画 state・widget・新規タブの Protocol 定義
- [frontend/ui_tkinter_state.py](../../frontend/ui_tkinter_state.py) — 動画設定用 Tk 変数の初期化
- [frontend/ui_tkinter_mapper.py](../../frontend/ui_tkinter_mapper.py) — 品質→CRF 変換と `VideoCompressionConfig` 構築
- [frontend/ui_tkinter_view.py](../../frontend/ui_tkinter_view.py) — 「出力設定」タブの独立化（4タブ構成）と「動画圧縮設定」セクション
- [frontend/ui_tkinter.py](../../frontend/ui_tkinter.py) — 動画UI検出表示・活性制御の初回呼び出し
- [frontend/ui_tkinter_controller.py](../../frontend/ui_tkinter_controller.py) — 動画UI・段階付き進捗・二重開始／削除防止・安全な終了
- [frontend/config_data/locales/ja.json](../../frontend/config_data/locales/ja.json) / [frontend/config_data/locales/en.json](../../frontend/config_data/locales/en.json) — 日英ロケール文言
- [pjp_compressor.iss](../../pjp_compressor.iss) / [vendor_zip.ps1](../../vendor_zip.ps1) — 配布物構成の確認

---

## Verification

1. `pytest tests/unit/test_capabilities.py tests/unit/test_contracts.py tests/unit/test_ui_tkinter_mapper.py tests/unit/test_video_utils.py tests/unit/test_job_lock.py tests/unit/test_locale_catalog.py tests/unit/test_settings_split.py`
2. `pytest tests/integration/test_job_runner.py tests/integration/test_ui_controller.py tests/regression/test_tkinter_regression.py`
3. `pytest`（全体回帰）
4. 採用ffmpeg / ffprobeビルドで `pytest tests/integration/test_video_ffmpeg.py` を実行する。保持可能な入力だけがMP4になり、保持不可入力は元拡張子・同一内容で出力されることを確認する。全体進捗と動画名・割合（不明時は割合なし）が合成表示され、画像完了でちらつかないことを確認する。
5. 以下の動画で手動確認する:
   - 奇数解像度（例: 1279x719）→ エラーなく偶数丸めで出力される
   - 音声なし動画・字幕なし動画 → optional mapによりエラーなく出力される
   - 本編より先にカバーアートがある動画 → `0:V:0` により本編が選択される
   - 縦長・回転メタデータ付き動画 → 向きが保持される
   - 複数音声・多チャンネル音声 → 全トラック・言語・既定選択・レイアウトが保持され、AAC指定時のビットレートがチャンネル数に応じて変わる
   - MP4へコピー可能な音声（採用ビルドで対応するOpus等を含む）→ 不要なAAC変換がない
   - MP4コピー非対応と確認できる音声 → 該当トラックだけAAC切替の通知が出る。他のコピー可能な音声はコピーされる
   - 複数mov_text字幕 → 本文・装飾・タイミング・言語・既定／強制選択状態が保持される
   - ASS＋添付フォント、SRT等の変換必要字幕、PGS、HDR → 元ファイルが元拡張子で保持され、具体的な理由がログ・CSVに残る
   - チャプター付き動画 → チャプター名・時間が保持される
   - 総尺不明動画 → 動画名が処理中として表示され、割合不明を終了と誤認しない
   - 低ビットレートで出力が肥大化する動画 → **元の拡張子のまま元ファイルがコピー** され、CSV に `元ファイル維持` と記録される
   - 同一フォルダの `sample.mp4` と `sample.mov` → 上書きされず `sample.mp4` / `sample_mov.mp4` に出力される
6. 複数動画の待機中・解析中・エンコード中・元コピー中・AAC再試行前に終了する。停止要求後に次のプロセス・再試行・コピー・ZIP再生成が始まらず、ffmpeg / ffprobe・executorが終了し、一時領域・出力ロックの後片付け後にウィンドウが閉じることを確認する。異常終了の残留領域は次回の排他取得後に限り掃除されることを確認する。
7. ffmpegなし／ffprobeなし／検出コマンド失敗／libx265なし環境で起動し、起動直後から動画セクション全体（またはH.265のみ）が無効化され、具体的な理由が表示されること、PDF・画像圧縮が従来どおり動作することを確認する。
8. UI 上で「圧縮設定」「出力設定」「アプリ設定」「ログ・進捗」の4タブが正しく表示・遷移でき、既存の出力設定（CSV出力、ZIP展開/再圧縮、ミラーコピー等）が「出力設定」タブから問題なく機能することを確認する。
9. 開始ボタン連打・処理中クリーンアップが拒否され、別アプリインスタンスが同じ出力フォルダの圧縮・出力クリーンアップを開始できないことを確認する。残留掃除が使用中・所有不明のファイルを削除しないことを確認する。
10. 凍結アプリ・インストーラで両ツールの起動、配布資料と対応ソースの取得を確認する。動画と画像の混在処理中にUI操作が応答し、画像タスクが動画待ちで停止しないことを実測する。CPU使用率そのものの上限保証は検証要件にしない。

---

## Decisions

- **同時実行・CPU負荷**: アプリ内の圧縮ジョブは同時に1件。汎用executorと動画専用の単一ワーカーexecutorを分離し、動画待ちが画像・PDFワーカーを塞がないようにする。ffmpegは低優先度で起動するが、内部のマルチスレッド処理によりCPUを使い切る可能性はある。初版は同時エンコード数の制限に目的を限定し、使用率の上限は保証しない。必要なら実測後にx264 / x265別のスレッド制限を追加する。
- **品質設定のUI表現**: ユーザー向けには画像・PDFと同じ 0〜100 の品質スライダーを提示し、mapper 層で `CRF`（x264: 18〜40 / x265: 22〜44）へ変換する。backend 契約は `crf` のみを持つ。
- **保持範囲**: 最初の非カバー本編映像、全音声・全字幕、および関連する言語・トラック名・既定／強制選択状態・音声レイアウト・チャプター・向きを保持する。追加映像・カバーアートは初版の対象外。字幕を黙って削除・焼き込みしない。音声の既定はコピー、明示的なAAC指定と通知付き限定フォールバックは音質維持の例外、音声なし指定だけは全音声削除の例外とする。
- **出力コンテナ形式**: 保持条件を満たし、圧縮後に元より小さくなる場合のみMP4を出力する。保持条件をMP4統一より優先する。同名衝突は大文字小文字非区別で解消し、元維持の出力先も予約する。MKV自動選択は初版に含めない。
- **保持条件による元維持**: 初版ではHDR、字幕変換・装飾／添付フォント等の保持不能、音声レイアウト維持不能、出力検証での保持条件違反は元拡張子のままコピーする。ミラー設定に関係なく実施し、実配置後のみ `processed` 集計する。サイズ理由の元維持・圧縮成功とは別のCSVアクションと具体的な理由を記録する。
- **元以上サイズ時の扱い**: 圧縮後サイズが元以上の場合は、**拡張子も含めて元ファイルをそのまま出力先へコピー** する（ミラー設定に関係なく実施し、`processed` として集計、CSV は `csv_action_video_kept_original`）。既存 Ghostscript の `pdf_gs_no_gain` と同じ方針。
- **失敗・中断**: 解析／実行／出力破損等の通常失敗は未処理とし、ミラー有効時のみ元拡張子でコピーする。中断は別結果で、停止後の再試行・元コピー・最終配置・ZIP再生成を禁止する。配置済み成果物は残し、部分集計を中断として通知する。
- **出力排他・一時領域**: 同一出力フォルダの圧縮・出力クリーンアップはOSファイルロックで排他する。全処理・executor・後片付け終了までロックを保持する。残留掃除は排他取得後に専用領域の所有確認済み過去ジョブだけを対象とする。
- **終了保証**: 共通停止フラグ、未開始futureキャンセル、起動との同期、実行中ffmpeg / ffprobeの停止・回収、後片付け完了待ちを一体で設計する。Tkイベントループを停止待ち中も維持し、親スレッドのdaemon属性を終了保証に使わない。
- **入力解析・進捗表示**: ffprobeを追加依存とし、JSONで保持条件と総尺を判定・出力検証する。割合は総尺と `out_time_us` から算出する。動画イベントは開始・更新・終了を区別し、`current=None` は割合不明に専用化する。全体件数と動画状態の更新・再描画はメインスレッドに統一する。
- **タイムアウト**: エンコードは固定タイムアウトなし、ffprobeのファイル解析・出力検証は30秒。両ツールをキャンセル対象にする。ストール検知は将来課題。
- **ツール・エンコーダ互換**: ffmpeg / ffprobeの起動可否とlibx264 / libx265 / AACを検出し、理由付きでUI活性を制御する。音声コピー可否と再生機器互換性を区別し、失敗を一律にAAC再試行しない。H.265出力には `-tag:v hvc1` を付与する。
- **配布**: 同一ビルドのffmpeg / ffprobeを固定し、非再配布可能なnonfreeビルドは採用しない。ライセンス互換性の確認と、バイナリに対応するソース・ビルド情報の提供を別の受入条件とする。
- **タブ構成**: メインタブの肥大化を防ぐため、「出力設定」を独立した第2タブへ切り出す。

## References

- [FFmpeg: Stream selection / stream specifiers](https://ffmpeg.org/ffmpeg.html) — `v` と `V`、全音声・全字幕の選択、metadata / dispositionの扱い
- [FFprobe documentation](https://ffmpeg.org/ffprobe.html) — JSONによるformat / streams / chapters解析
- [FFmpeg MP4 muxer implementation](https://github.com/FFmpeg/FFmpeg/blob/master/libavformat/movenc.c) — コーデック格納可否の確認元。実際の判定・テストは固定した採用ビルドに対して行う
- [Python: ThreadPoolExecutor](https://docs.python.org/3/library/concurrent.futures.html#concurrent.futures.ThreadPoolExecutor) — executorの終了待ち・未開始futureのキャンセル
- [FFmpeg license and legal considerations](https://ffmpeg.org/legal.html) — 採用ビルドのライセンス・対応ソース確認
