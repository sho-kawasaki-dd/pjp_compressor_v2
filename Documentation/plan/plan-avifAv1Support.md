# Plan: AVIF / AV1 の出力と、互換変換（AVIF→JPEG・AV1→H.264）への対応

> **チェックボックスの運用**: 各タスクの実装とテストが終わったら `- [ ]` を `- [x]` に変更してください。
> 着手したが完了していないタスクは `[ ]` のまま残し、行末に `（作業中）` と書き添えてください。
> 方針を変えた場合は、該当タスクを書き換えたうえで「変更履歴」に記録してください。

## 概要

高効率な圧縮と、古い環境との互換性の両方に対応するため、次の4つの経路を追加する。

| 経路 | 入力 | 出力 | 目的 | 容量が増えたとき |
|---|---|---|---|---|
| AVIF出力 | JPEG（PNGは任意） | AVIF | 高効率な圧縮 | **元ファイルを残す** |
| AV1出力 | 対象の動画すべて | MP4（AV1） | 高効率な圧縮 | 元ファイルを残す（既存の規則） |
| 互換変換（画像） | AVIF | JPEG | 古い環境で開ける形式にする | **そのまま出力する** |
| 互換変換（動画） | AV1の動画 | MP4（H.264） | 古い環境で再生できる形式にする | **そのまま出力する** |

容量が増えても出力するのは、**互換変換の2経路だけ**とする。既存の経路の判定は変えない。

- 動画: 元より小さくなければ元ファイルを残す。
- JPEG / PNG を同じ形式で出力する場合: サイズを判定せず出力する。

すべての新しい経路は**既定でOFF**にし、利用者が選んだときだけ動かす。

### 互換変換 ON 時の動作原則（対象外ファイルには触らない）

画像の互換変換（`avif_to_jpeg_compat`）と動画の互換変換（`av1_to_h264_compat`）は**別々に ON / OFF を設定できる**。
どちらか1つでも ON の場合は「互換変換モード」として動作し、**ON にした互換変換の対象ファイルだけを処理し、それ以外のファイルには一切触らない（通常の圧縮や PDF 圧縮を行わない）**。

| 画像の互換変換 (`avif_to_jpeg_compat`) | 動画の互換変換 (`av1_to_h264_compat`) | 処理するファイル | 触らない（スキップする）ファイル |
|---|---|---|---|
| **OFF** | **OFF** | 従来どおり（PDF、JPEG、PNG、有効時の全対象動画） | 対象外の拡張子（`.avif` を含む） |
| **ON** | **OFF** | **`.avif` のみ**（→ JPEG へ変換） | PDF、JPEG、PNG、すべての動画 |
| **OFF** | **ON** | **AV1 の動画のみ**（→ H.264 MP4 へ変換） | PDF、JPEG、PNG、`.avif`、**AV1 以外の動画（H.264 等）** |
| **ON** | **ON** | **`.avif` と AV1 の動画のみ** | PDF、JPEG、PNG、**AV1 以外の動画（H.264 等）** |

- 「触らない」ファイルは、`copy_non_target_files`（対象外ファイルも出力先にコピーする設定）が False（既定）なら出力フォルダに何も書き出さない。True（ミラー出力）のときだけ、`csv_action_non_target_copy` として無変換で出力先へコピーする。

## 前提（調査済みの事実）

- 同梱 FFmpeg（[vendor/ffmpeg-windows/bin/](../../vendor/ffmpeg-windows/bin/)）は、x264 だけを組み込んだビルドとして配布を承認したもの（[ffmpeg-distribution-audit.md](../ffmpeg-distribution-audit.md)）。
- 同梱 FFmpeg が持つ AV1 デコーダーは FFmpeg 内蔵の `av1` だけで、これはハードウェアでデコードできるときしか動かない。同梱ビルドにはハードウェアのデコード機能を使う仕組みが無いため、**AV1 の入力はどの PC でも変換に失敗する**（2026-11-06 に実データで確認。終了コード 69）。
- ffprobe は、デコーダーが無くても `codec_name=av1` を返す。
- 開発環境の Pillow 12.2.0 では AVIF の読み書きができる（`PIL.features.check("avif")` が True）。配布用 exe の中で使えるかはまだ確認していない。
- 動画は専用の1スレッド（`max_workers=1`）で順番に処理している。画像とPDFは `max(4, cpu_count)` 本のスレッドで並列に処理している（[job_runner.py](../../backend/orchestrator/job_runner.py)）。
- 動画の出力検証（`verify_output`）は、映像コーデックの種類を確認していない。
- 画像の経路には「容量が増えたら元ファイルを残す」判定が無く、出力の拡張子は常に入力と同じ。

## フェーズ構成と依存関係

```
フェーズ0（AV1入力の事前判定） ── 単独で先に出せる
フェーズ1（共通基盤） ──┬─ フェーズ2（AVIF出力）
                        └─ フェーズ3（AVIF→JPEG）
フェーズ4（FFmpeg作り直し・再承認） ──┬─ フェーズ5（AV1出力）
                                      └─ フェーズ6（AV1→H.264）
フェーズ7（UI・CSV・翻訳文・配布・文書） ── フェーズ2・3・5・6 と並行して進める
フェーズ8（検証）
```

- 画像の作業（フェーズ1〜3）は FFmpeg と関係ないので、フェーズ4 と並行して進められる。
- **フェーズ4の再承認が下りるまで、フェーズ5・6 の成果物を配布物に入れない。**
- UI・request の設定正規化に関する D-13・D-14 は、フェーズ2-2・6-1・7-2・7-4 の実装前に確定する。

---

## フェーズ0: AV1 入力の事前判定（今起きている失敗への対策）

AV1 を読めない環境では、変換を始める前に AV1 の入力を見つけて元ファイルを残す。

- [x] 0-1. [capabilities.py](../../backend/capabilities.py) に `_TRACKED_DECODERS = ('libdav1d', 'libaom-av1')` を追加し、`FfmpegDetection` に `decoders: frozenset[str]` を持たせて `-decoders` の一覧から検出する。結果は [contracts.py](../../backend/contracts.py) の `CapabilityReport` に `av1_decode_available: bool` プロパティ（またはフィールド）として追加する。
  - `-decoders` の取得失敗は別途記録し、AV1 以外の動画処理は継続する。AV1 入力は安全側で元ファイルを維持し、検出失敗の詳細も表示する。
- [x] 0-2. [video_utils.py](../../backend/core/video_utils.py) の `_compress()` で、HEVC の判定のすぐ後に AV1 の判定を入れる。入力が AV1（`info.contains_av1`）で、かつ `av1_decode_available` が False なら `keep('retention', ['av1_decoder_unavailable'])` を返す（デコーダー検出失敗時は失敗理由も追加する）。フェーズ6で互換変換モードを追加したあとは、互換変換の対象外判定を HEVC・AV1 の保持判定より先に行う（6-2）。
- [x] 0-3. `parse_probe_json()` の `MediaInfo` に、`contains_hevc` と同じ形で `contains_av1`（全映像ストリーム対象、フェーズ0のデコード不可判定用）を追加する。フェーズ6の互換変換対象かどうかの判定には、主映像（`info.video is not None and info.video.codec == 'av1'`）を使い分ける。
- [x] 0-4. 元ファイルを残した理由 `av1_decoder_unavailable` の表示文言を [ja.json](../../frontend/config_data/locales/ja.json) と [en.json](../../frontend/config_data/locales/en.json) に追加する。
- [x] 0-5. テストを追加する: `test_capabilities.py`（デコーダーの検出）、`test_video_utils.py`（AV1 入力で元ファイルが残る）、`test_video_ffmpeg.py`（同梱 FFmpeg で、理由が `av1_decoder_unavailable` になる）。

---

## フェーズ1: 画像の共通基盤（拡張子が変わる出力に対応する）

AVIF 出力と AVIF→JPEG はどちらも拡張子が変わり、「元ファイルを残す」場合もある。動画にしか無いこの仕組みを、画像にも使えるようにする。

- [ ] 1-1. [image_utils.py](../../backend/core/image_utils.py) で、`compress_image_pillow()` と `compress_png_pngquant()` に重複しているリサイズ処理を、helper 関数 `_apply_resize(img, resize_cfg)` に切り出す。既存の JPEG / PNG 圧縮の動作は変えない。
- [ ] 1-2. 新規経路（AVIF 出力・AVIF→JPEG 互換変換）向けに、EXIF・ICC プロファイル・画像の向きを引き継ぐ helper を追加する（既存の `compress_image_pillow()` には適用せず既存挙動を維持する）。
  - リサイズ前に `ImageOps.exif_transpose(img)` を適用してピクセルを正立させ、Orientation タグがリセットされた `exif` を保存時に渡す（ビューアでの二重回転と、縦横指定リサイズ時の向きずれを防ぐ）。
  - `_convert_cmyk_to_rgb()` で CMYK から RGB に変換した場合（`_cmyk_converted == True`）は、元の CMYK 用 `icc_profile` を破棄し、RGB 画像に CMYK プロファイルが埋め込まれないようにする。もともと RGB 系だった場合のみ `icc_profile` を引き継ぐ。
- [ ] 1-3. 画像処理の戻り値用に `ImageCompressResult` dataclass（`ok`, `message`, `final_outpath`, `kept_original`, `kept_original_reason: Literal['no_gain', 'retention'] | None`, `cancelled: bool`, `notes: tuple[str, ...]`）を追加し、動画の `VideoCompressResult` と同じ2階層の理由管理（`kept_original_reason` + `notes`）に揃える。停止は失敗・保持と区別して返す。既存の `(ok, message)` を返す関数は、互換のため残す。
- [ ] 1-4. [contracts.py](../../backend/contracts.py) に `ImageCompressionConfig` dataclass（`output_format`, `avif_quality`, `avif_speed`, `avif_include_png`, `avif_to_jpeg_compat`）を追加し、[worker_ops.py](../../backend/core/worker_ops.py) のタスクタプルには個別の設定値を増やすのではなく `ImageCompressionConfig` としてまとめて渡す。画像の結果からも `final_outpath`、`kept_original_reason`、`notes` を受け取り、出力サイズと CSV に反映する。
- [ ] 1-5. [job_runner.py](../../backend/orchestrator/job_runner.py) の `_plan_video_outputs()` を、拡張子が変わるファイルなら何でも扱える `_plan_converted_outputs()` に一般化する。
  - 変換後の拡張子は、入力の拡張子と設定から決める関数で返す（例: `.jpg→.avif`、`.avif→.jpg`、動画 `→.mp4`）。
  - 元ファイルを残す場合（`kept_original`）に備えて、元と同じ拡張子の出力パス（`original_outpath`）も画像のタスクに持たせ、予約済みパス（`claimed`）に含める。
  - 名前が衝突したら `{stem}_{src_ext}.{target_ext}` 形式で回避する（例: 入力に `photo.jpg` と `photo.avif` が両方あり、AVIF 出力が ON の場合は `photo_jpg.avif`）。
- [ ] 1-6. 「容量が増えたら元ファイルを残す」および「保持理由により元ファイルを残す」画像用の共通処理を追加する。並列実行（`max(4, cpu_count)`）で競合しないよう `.pjp_tmp_<uuid>` 形式の一時ファイルに書き出し、サイズ比較や保持判定のあとで `JobControl.launch_lock` 内で停止確認を行ってから正式な場所（`outpath` または `original_outpath`）に `replace()` する。起動時の残留一時ファイル掃除の対象にも含める。
  - 一時ファイルは出力先と同じファイルシステム上の、アプリが所有を確認できる作業領域に置く。異常終了後の掃除は出力排他を取得してから行い、接頭辞だけを根拠に所有不明のファイルを削除しない。
- [ ] 1-7. テストを追加する: リサイズ helper の切り出しで動作が変わらないこと、EXIF Orientation の二重回転が起きないこと、CMYK 変換時に CMYK ICC が残らないこと、拡張子が変わる出力名の計画と名前の衝突回避。
- [ ] 1-8. [job_runner.py](../../backend/orchestrator/job_runner.py) の失敗時フォールバックコピーを、動画だけでなく拡張子が変わる画像にも適用する。
  - ミラー出力（`copy_non_target_files=True`）では、予約済みの `original_outpath` に元拡張子のままコピーする。JPEG の実体を `.avif`、AVIF の実体を `.jpg` として配置しない。
  - コピーも一時領域を経由し、停止確認と正式配置を `JobControl.launch_lock` 内で行う。停止後はフォールバックコピーを開始せず、中断として扱う。
  - CSV の出力パスは今回実際に配置したパスだけを記録する。ミラー OFF の失敗、コピー失敗、中断などで配置されなかった場合は空欄にする。
  - 今回配置されなかった画像では、過去の出力ファイルを今回の成果物や出力サイズとして扱わない。失敗・中断は処理件数と前後サイズの集計から除外する。
- [ ] 1-9. 新画像経路のテストを追加する: 両方向の変換で保存失敗・正式配置失敗・保持コピー失敗を再現し、ミラー ON / OFF ごとの元拡張子へのコピー、CSV の実出力パス、集計を確認する。停止と正式配置の競合、既存出力の保護、一時ファイルの回収、異常終了後の所有確認付き掃除も検証する。

---

## フェーズ2: AVIF 出力（JPEG / PNG → AVIF）

- [ ] 2-1. [backend/settings.py](../../backend/settings.py) に次の既定値を追加する。
  - `IMAGE_OUTPUT_FORMAT_DEFAULT = 'original'`（選択肢は `'original'` と `'avif'`）
  - `AVIF_QUALITY_DEFAULT`（候補: 60）、`AVIF_SPEED_DEFAULT`（候補: 6、範囲は 0〜10）
  - `AVIF_TARGET_PNG_DEFAULT = False`
- [ ] 2-2. [contracts.py](../../backend/contracts.py) の `ImageCompressionConfig`、`CompressionRequest`、`to_legacy_kwargs()` に `image_output_format`、`avif_quality`、`avif_speed`、`avif_include_png` を追加し、範囲と排他条件（`avif_to_jpeg_compat=True` のときは `image_output_format == 'original'` であること）を検証する。
- [ ] 2-3. [image_utils.py](../../backend/core/image_utils.py) に `compress_image_to_avif()` を追加する。
  - CMYK を RGB に変換する。`exif_transpose` で向きを正立させてからリサイズし、EXIF と（非CMYK時の）ICC を引き継ぐ。
  - Pillow の `save(format='AVIF', quality=..., speed=...)` で保存する。
  - 透過（アルファ）は残す。
  - **出力が元以上の大きさなら元ファイルを残す**（`kept_original_reason='no_gain'`）。
- [ ] 2-4. [worker_ops.py](../../backend/core/worker_ops.py) で、互換変換モードが OFF かつ `image_output_format == 'avif'` のとき、`jpg` と `jpeg` を AVIF の経路に回す。`png` は `avif_include_png` が True のときだけ回し、False なら今までどおり pngquant / Pillow で処理する。
- [ ] 2-5. AVIF が使えない環境（`features.check('avif')` が False）を検出する。
  - `CapabilityReport` に `avif_available` を追加する。
  - 使えない環境で AVIF 出力（または AVIF→JPEG 互換変換）が指定されたら、ジョブ開始前の検証でエラーにする。今の圧縮経路に黙って戻すことはしない。
- [ ] 2-6. テストを追加する: AVIF で出力されること、容量が増えたら元ファイルが残ること、透過・EXIF・ICC が残ること、PNG を対象にするかどうかの切り替え。

---

## フェーズ3: 互換変換 AVIF → JPEG

- [ ] 3-1. `ImageCompressionConfig` と `CompressionRequest` に `avif_to_jpeg_compat: bool` を追加する。既定は False。JPEG の品質は既存の `jpg_quality` を使う。
- [ ] 3-2. [image_utils.py](../../backend/core/image_utils.py) に `convert_avif_to_jpeg()` を追加する。
  - 透過部分は白で塗りつぶす。CMYK を RGB に変換する。`exif_transpose` 後にリサイズし、EXIF と（非CMYK時の）ICC を引き継ぐ。
  - 動く AVIF（複数フレーム: `getattr(img, 'is_animated', False)` または `getattr(img, 'n_frames', 1) > 1`）は変換せず、元ファイルを残す（`kept_original_reason='retention'`, `notes=('animated_avif',)`）。
  - Pillow は `Image.open()` 時点で AVIF を 8bit RGB/RGBA にデコードするため、そのまま 8bit JPEG として出力する。`img.info`（ICC プロファイル名やメタデータ等）から HDR / 広色域が判別できた場合はベストエフォートで注記 `hdr_or_high_bitdepth_flattened` を残す。
  - **元より大きくても出力する**。容量が増えた場合は注記 `size_increased` を残す。
- [ ] 3-3. [worker_ops.py](../../backend/core/worker_ops.py) に `avif` の分岐と、通常圧縮より先に行う互換変換モードの対象判定を追加する。
  - ジョブ全体のモード（`avif_to_jpeg_compat or av1_to_h264_compat`）を worker でも参照できるようにし、画像・動画どちらかの互換変換が ON なら `.jpg` / `.jpeg` / `.png` / `.pdf` の通常圧縮を呼ばない。動画互換変換だけが ON の場合も同じとする。
  - `.avif` は `avif_to_jpeg_compat` が ON のときだけ処理する。OFF なら対象外とする。動画の対象判定は6-2に従う。
- [ ] 3-4. [job_runner.py](../../backend/orchestrator/job_runner.py) で、互換変換（画像または動画）が ON のときは `compressible_extensions` を互換変換の対象拡張子だけに絞る（`avif_to_jpeg_compat` が ON なら `'avif'`、`av1_to_h264_compat` が ON なら `VIDEO_EXTENSIONS` を含め、両方 ON ならその和集合とする。`'pdf'`, `'jpg'`, `'jpeg'`, `'png'` は含めない）。この集合は拡張子段階の候補判定であり、worker の通常圧縮を止める3-3の分岐や、動画コーデック判定の代わりにはしない。
- [ ] 3-5. テストを追加する: 容量が増えても出力されること、動く AVIF は元ファイルが残ること、透過が白になること、互換変換 ON のときは JPEG / PNG / PDF には触れず `.avif` のみ変換されること、OFF のとき `.avif` が対象外のファイルとして扱われること。
- [ ] 3-6. 対象外という判定を、worker からコピー・CSV・集計まで引き継ぐ。
  - `WorkerFileResult` に `is_non_target: bool` を追加し、未処理の失敗や中断と対象外を区別する。動画コーデック判定による対象外も `VideoCompressResult` から引き継ぐ。
  - orchestrator は拡張子だけで対象外を再判定せず、worker の確定結果を使う。対象外は `processed=False`、`final_outpath=None`、保持理由なしで返し、元ファイル保持の成功として数えない。
  - ミラー ON では `csv_action_non_target_copy` として元拡張子へコピーし、`csv_action_fallback_copy` と区別する。ミラー OFF ではファイルを出力せず、ログ・CSV の処理種別も圧縮失敗ではなく対象外スキップとして明示する（`csv_action_non_target_skip` を追加）。コピー失敗は明示的な失敗として記録する。
  - 対象外はミラーコピーの有無によらず `processed_files`・`orig_total`・`out_total` に含めない。進捗は対象外も1件として完了させる。

---

## フェーズ4: FFmpeg の作り直しと配布の再承認（フェーズ5・6 の前提）

- [ ] 4-1. ビルドスクリプトを作る。[build_ffmpeg_x264.sh](../../scripts/build_ffmpeg_x264.sh) を元に `build_ffmpeg_x264_av1.sh` を作り、`--enable-libsvtav1 --enable-libdav1d` を追加する。x264 は残す（ライセンスは GPLv3 のまま）。
  - `SVT-AV1` は **CMake**（`cmake`）、`dav1d` は **Meson + Ninja**（`meson`, `ninja`）でビルドするため、スクリプト冒頭の必須ツール確認に `cmake`, `meson`, `ninja` を追加し、それぞれ静的ライブラリ（`-DBUILD_SHARED_LIBS=OFF`、`--default-library=static`）としてビルド・インストールしてから FFmpeg を configure する。
- [ ] 4-2. SVT-AV1 と dav1d のソースを用意し、バージョンを固定して SHA256 を記録する。
- [ ] 4-3. ビルド後に、次を確認する。
  - エンコーダーの一覧に `libx264`、`libsvtav1`、`aac` がある。
  - デコーダーの一覧に `libdav1d` がある。
  - HEVC の encoder / decoder / parser が無効のままである。
  - `config_components.h` を確認した。
- [ ] 4-4. 新しいマニフェスト（例: `ffmpeg-x264-av1-manifest.json`）を作り、バイナリの SHA256 を固定する。
- [ ] 4-5. ライセンス文を [vendor/ffmpeg-windows/licenses/](../../vendor/ffmpeg-windows/licenses/) に追加する。
  - SVT-AV1: BSD-3-Clause-Clear と、AOM の特許ライセンス（AOM Patent License）
  - dav1d: BSD-2-Clause
  - `NOTICE.txt` と `README.txt` も更新する。
- [ ] 4-6. 配布の検証を更新する: [verify_ffmpeg_distribution.py](../../scripts/verify_ffmpeg_distribution.py)、`tests/unit/test_ffmpeg_distribution.py`、[pjp_compressor.iss](../../pjp_compressor.iss)、[vendor_zip.ps1](../../vendor_zip.ps1)。
- [ ] 4-7. [ffmpeg-distribution-audit.md](../ffmpeg-distribution-audit.md) に、今回のビルドの監査記録を追記する。
- [ ] 4-8. GitHub Release に掲載するソースを用意する: `svt-av1-source.tar.gz` と `dav1d-source.tar.gz`。
- [ ] 4-9. **【承認ゲート】ユーザーから配布の再承認を得る。** 承認を得るまでは vendor に配置せず、配布物にも入れない。
- [ ] 4-10. 承認を得たら、vendor のバイナリを差し替え、マニフェストの状態を `approved_for_redistribution` に更新する。

---

## フェーズ5: AV1 出力（libsvtav1）

- [ ] 5-1. [backend/settings.py](../../backend/settings.py) のコーデック関連の定数を、コーデックごとに分ける。
  - `VIDEO_ALLOWED_CODECS = {'libx264', 'libsvtav1'}`
  - CRF の範囲: `VIDEO_CRF_RANGE_BY_CODEC`（x264 は 0〜51、SVT-AV1 は 0〜63）
  - プリセット: `VIDEO_ALLOWED_PRESETS_BY_CODEC`（SVT-AV1 は数値の `'0'`〜`'13'`）
  - 既定の CRF: `VIDEO_CRF_DEFAULT_BY_CODEC`（SVT-AV1 の候補は 35）
- [ ] 5-2. [contracts.py](../../backend/contracts.py) の `VideoCompressionConfig` で、`codec` の型（`Literal`）を広げ、コーデックごとの範囲で検証する。あわせて `av1_to_h264_compat=True` のときは `codec == 'libx264'` でなければならないことを `__post_init__()` で検証する。
- [ ] 5-3. [capabilities.py](../../backend/capabilities.py) で、確認するエンコーダーに `libsvtav1` を加える（`_TRACKED_ENCODERS`）。`CapabilityReport` にコーデック別の利用可否（`h264_encode_available`、`av1_encode_available`）を追加し、動画が使えるかの判定（`tool_unavailable_reason()`）は `libx264` 固定ではなく、選んだコーデック（互換変換時は `libx264` と `av1_decode_available`）が使えるかで決める。
- [ ] 5-4. [video_utils.py](../../backend/core/video_utils.py) の `build_ffmpeg_command()` で、コーデックに応じて引数を組み立てる。
  - SVT-AV1: `-c:v libsvtav1 -crf N -preset P -pix_fmt yuv420p`
  - 必要なら `-svtav1-params` で、キーフレームの間隔などを調整する。
  - 出力形式は MP4（`av01`）。`+faststart` は今までどおり付ける。
- [ ] 5-5. `verify_output()` に、映像コーデックが想定どおりか（`h264` / `av1`）の確認を追加する。違っていたら `video_codec` を違反として記録する。
- [ ] 5-6. 入力が AV1 で、出力も AV1 の場合は、通常の圧縮として扱い、元より小さくなければ元ファイルを残す。デコードにはフェーズ4で入れる dav1d を使う。
- [ ] 5-7. SVT-AV1 が使うスレッド数を調べる。動画は1本ずつ処理するが、画像やPDFの並列処理と同時に走ると CPU を奪い合う。必要ならスレッド数の上限（`-svtav1-params lp=N`）や、低優先度での実行（`low_priority`）を設定する。
- [ ] 5-8. [ui_tkinter_mapper.py](../../frontend/ui_tkinter_mapper.py) の `quality_to_crf()` を、コーデックごとに計算するように拡張する。UI のプリセット名（`ultrafast` / `fast` / `medium` / `slow`）は、SVT-AV1 の数値に変換する（候補: 12 / 10 / 8 / 6）。
- [ ] 5-9. テストを追加する: コーデックごとの検証、組み立てた ffmpeg コマンド、映像コーデックの確認、品質から CRF への変換、外部ツールが必要な AV1 の実エンコード。

---

## フェーズ6: 互換変換 AV1 → MP4（H.264）

- [ ] 6-1. `VideoCompressionConfig` に `av1_to_h264_compat: bool` を追加する。既定は False。エンコードには既存の x264 の CRF とプリセットを使う（`av1_to_h264_compat=True` のときは `codec == 'libx264'` であることを契約で保証する）。
- [ ] 6-2. [video_utils.py](../../backend/core/video_utils.py) の `_compress()` で、主映像（`info.video`）のコーデックと設定に応じて次のとおり処理する。
  - ffprobe の解析後、互換変換モードの対象外判定を最初に行い、その後に対象ファイルの HEVC・AV1 デコード不可・保持条件を判定する。主映像が AV1 でない動画（主映像なしを含む）は、HEVC を含む場合や副映像だけが AV1 の場合も対象外として返す。ffprobe の起動・解析失敗は対象外と決めつけず、明示的な失敗として返す。

  | 入力（主映像） | 条件 | 動作 |
  |---|---|---|
  | AV1 以外（主映像なしを含む） | **互換変換 ON** | **最初に対象外として返す。保持処理やエンコードは行わない（`copy_non_target_files` が ON のときだけ orchestrator で無変換コピー）** |
  | AV1（通常圧縮では `contains_av1` も対象） | 対象外ではなく、AV1 を読めない | 元ファイルを残す（`av1_decoder_unavailable`。フェーズ0。HEVC も含む場合は既存の HEVC 保持判定を優先） |
  | AV1 | 互換変換 ON、8bit以下、SDR、色域がBT.709または未指定 | x264 で出力する。音声・字幕などを保持できるかの判定と、出力の検証は行う。**元より小さいかどうかの判定だけ省く** |
  | AV1 | 互換変換 ON、10bit SDR、色域がBT.709または未指定 | 10bitから8bitへディザを用いて変換し、x264で出力する。注記 `bit_depth_reduced=10->8` を記録する |
  | AV1 | 互換変換 ON、HDR / 色域がBT.2020等 / 12bit以上 | トーンマッピング等は行わず、元ファイルを残す |
  | AV1 | 互換変換 OFF | 選んだコーデックで、通常の圧縮として扱う |
  | AV1 以外 | 互換変換 OFF | 今までと同じ（通常の動画圧縮） |

- [ ] 6-3. `VideoStreamInfo` に `color_primaries`、`color_transfer`、`color_space` を追加し、10bit SDR の許可条件を実装する。互換変換が ON の場合に限り、ビット深度が10bitで、HDR（PQ / HLG / Dolby Vision等）ではなく、3つの色特性がいずれも `{'bt709', 'unknown', 'unspecified', None}` に収まる入力を8bit変換の対象にする。12bit以上、HDR、`bt2020nc` 等の広色域は `retention` とする。通常の圧縮とAV1出力では、従来どおり8bitを超える入力を許可しない。
- [ ] 6-4. 10bit SDRから8bitへの変換時は、`-vf` の scale にディザ方式を明示し（候補: `sws_dither=ed`）、`,format=yuv420p` を適用する。
  - `accurate_rnd` は丸め精度、`full_chroma_int` はクロマ補間の指定であり、ディザ方式の指定として扱わない（[FFmpeg scaler 公式仕様](https://ffmpeg.org/ffmpeg-scaler.html)）。
  - フェーズ4で固定したビルドで候補方式の対応状況と実際の画素変換を確認し、採用方式を確定する。既存のリサイズ・偶数丸めのフィルターと統合し、ディザを指定した変換より前に暗黙の8bit化が起きないようにする。
  - 出力引数に `-color_primaries bt709 -color_trc bt709 -colorspace bt709` を明示する。ffprobe（`verify_output()`）で出力の画素形式（`yuv420p`）と色特性（BT.709）を確認し、入力の色特性が未指定の場合のBT.709扱いもテストで固定する。
  - ffprobe の画素形式・色タグ検証はディザ実施の証明にはしない。10bit グラデーション素材を実変換し、エンコード前の8bit変換画素をディザ無効時と比較して、採用方式による量子化の違いを検証する。圧縮後の映像でも階調の見え方を確認する。
- [ ] 6-5. 動画の互換変換が OFF で画像の互換変換（`avif_to_jpeg_compat`）だけが ON のときは、動画ファイル自体を処理対象から外し、動画には一切触らないようにする。
- [ ] 6-6. 互換変換で出力したら、結果の注記に `compat_conversion` を入れる。容量が増えた場合は `size_increased` も入れる。10bit SDRを8bitにした場合は `bit_depth_reduced=10->8` も記録する。
- [ ] 6-7. テストを追加する: 容量が増えても出力されること、10bit SDRが8bitで変換されBT.709タグを持つこと、10bit HDR・BT.2020・12bit入力は互換変換 ON でも元ファイルが残ること、**互換変換 ON のとき AV1 以外の動画（H.264 等）には触れない（エンコードされない）こと**、互換変換 OFFでは従来どおり8bit超の入力が保持されること。
  - H.264、HEVC、主映像が非AV1で副映像だけが AV1、主映像なしの各入力で、保持処理も呼ばれず対象外になることを確認する。ミラー OFF ではファイルが出力されず、ON では対象外コピーになり、集計から除外されることまで検証する。

---

## フェーズ7: UI・CSV・翻訳文・配布・文書

### UI
- [ ] 7-1. 画像の設定に「出力形式」を追加する（元の形式 / AVIF）。AVIF を選んだときだけ、次の設定を押せるようにする。
  - AVIF の品質スライダー
  - 速度
  - PNG も対象にするか
  - 対象: [ui_tkinter_view.py](../../frontend/ui_tkinter_view.py)、[ui_tkinter_state.py](../../frontend/ui_tkinter_state.py)、[ui_contracts.py](../../frontend/ui_contracts.py)、[ui_tkinter_mapper.py](../../frontend/ui_tkinter_mapper.py)
- [ ] 7-2. 画像の設定にチェックボックス「AVIF を JPEG に変換（互換性優先・容量が増える場合あり）」を追加する。ON のときは画像の出力形式（AVIF出力）や PNG 圧縮設定をグレーアウトする。
  - D-13を先に確定し、「AVIF出力を選択 → 画像互換変換 ON」でも、無効化された値がそのまま request に残って2-2の契約違反にならないようにする。UI 表示値と実効値の変換は [ui_tkinter_mapper.py](../../frontend/ui_tkinter_mapper.py) の request 生成経路で整合させ、backend の契約検証は残す。
- [ ] 7-3. 動画の設定で、固定表示のコーデック欄（`video_codec_label`）を、H.264 / AV1 を選べるコンボボックスに変える。コーデックに合わせて、品質の目安表示（CRF）とプリセットの選択肢を切り替える。
- [ ] 7-4. 動画の設定にチェックボックス「AV1 動画を H.264 に変換（互換性優先・容量が増える場合あり）」を追加する。画像・動画の互換変換は別々に ON / OFF でき、いずれかの互換変換が ON のときは、非対象の通常圧縮設定（PDF 設定、互換変換 OFF 側のカテゴリ設定、AV1 出力コーデック選択など）をグレーアウトして「互換変換の対象ファイルのみ処理される」ことが分かるようにする。
  - D-14を先に確定し、動画の `enabled=False` または `video_config=None` と、動画互換変換 ON の関係を UI・mapper・backend 契約で揃える。互換変換を選んだのに mapper が設定を破棄して通常モードになる状態を作らない。
  - 互換変換の ON → OFF、画像・動画両方の切替、動画コーデック切替、利用不可環境、保存設定の読み込みについて、表示・操作可否・request の実効値が一致することをテストする。能力不足で要求を実行できない場合は、通常圧縮へ黙って切り替えず理由を通知する。
- [ ] 7-5. その環境で使えない機能は、押せないようにして理由をツールチップで示す。判定に使う項目は次のとおり。
  - `avif_available`
  - `libsvtav1` が使えるか（`av1_encode_available`）
  - `av1_decode_available`
- [ ] 7-6. コントローラーのジョブ開始ログ（[ui_tkinter_controller.py](../../frontend/ui_tkinter_controller.py)）に、出力形式と互換変換の設定を出す。
- [ ] 7-7. 設定の保存と読み込みがあれば、新しい項目を加え、古い設定ファイルを読んだときは既定値を使う。

### CSV・ログ・翻訳文
- [ ] 7-8. CSV の処理種別を追加する: `csv_action_avif`、`csv_action_compat_jpeg`、`csv_action_compat_h264`、`csv_action_image_kept_original`（画像 `no_gain` 用）、`csv_action_image_kept_retention`（画像 `retention` 用）、`csv_action_non_target_skip`。対象外コピーは既存の `csv_action_non_target_copy`、変換失敗時のコピーは `csv_action_fallback_copy` を使い分ける。
- [ ] 7-9. 完了画面の集計には、互換変換で出力したファイルも処理件数（`processed_files`）と前後サイズ（`orig_total`・`out_total`）に含める。互換変換によって合計サイズが増えた場合（`saved < 0`）は、完了ステータスや統計サマリーで「削減」ではなく既存の `worker_size_delta_grown` と同様に「増加」と分かる表示にする。
- [ ] 7-10. 追加したすべての文言を [ja.json](../../frontend/config_data/locales/ja.json) と [en.json](../../frontend/config_data/locales/en.json) の両方に入れる。

### 拡張子・配布
- [ ] 7-11. [frontend/settings.py](../../frontend/settings.py) のお掃除用の拡張子リスト（`INPUT_DIR_CLEANUP_EXTENSIONS` と `OUTPUT_DIR_CLEANUP_EXTENSIONS`）に `.avif` を加える。
- [ ] 7-12. PyInstaller で作った exe の中で、Pillow の AVIF の読み書きが動くことを確認する。必要なら [compressor_launcher_tkinter.spec](../../compressor_launcher_tkinter.spec) に hidden import やバイナリを追加する。手順は `.github/skills/plan-pyinstallerspecrecheck` に沿う。
- [ ] 7-13. インストーラーとバージョン番号を更新する（[pyproject.toml](../../pyproject.toml)、[pjp_compressor.iss](../../pjp_compressor.iss)）。

### 文書
- [ ] 7-14. [README.md](../README.md) に、対応する形式と、互換変換で容量が増える場合があることを追記する。
- [ ] 7-15. リリースノートを作る（`Documentation/release-notes-v2.8.0.md` など）。
- [ ] 7-16. [flow_sequence_and_class_diagrams.md](../flow_sequence_and_class_diagrams.md) の画像・動画の処理の流れを更新する。

---

## フェーズ8: 検証

- [ ] 8-1. `pytest tests/unit` がすべて通る。
- [ ] 8-2. `pytest tests/integration` がすべて通る（`-k "avif or av1 or compat"` を重点的に確認する）。
- [ ] 8-3. 外部ツールが必要なテスト（`requires_external`）が、新しい FFmpeg で通る。
- [ ] 8-4. `pytest tests/regression/test_tkinter_regression.py` が通る。新しい UI の表示と、使えない環境で押せなくなることを確認する。
- [ ] 8-5. 代表的なサンプル（写真、スクリーンショット、スマホで撮った動画、画面録画）で、従来の形式と AVIF / AV1 のサイズと処理時間を比べ、既定の品質値が妥当か確認する。
- [ ] 8-6. 配布用 exe で、次を手で確認する。
  - 出力した AVIF と AV1 の MP4 が、Windows のフォトアプリとブラウザーで開ける。
  - 互換変換で出力した JPEG と H.264 の MP4 が、古い端末で開ける。
- [ ] 8-7. インストーラーに、追加したライセンス文が入っていることを確認する。
- [ ] 8-8. 画像・動画の互換変換4状態 × ミラー ON / OFF の8通りで統合テストを行う。PDF・JPEG・PNG・AVIF・AV1動画・H.264動画・HEVC動画を混在させ、呼び出された処理、実際の出力ファイルと拡張子、CSV の処理種別・出力パス、処理件数・前後サイズ、進捗を検証する。通常設定に AVIF / AV1 出力が残っている場合も、互換変換中は通常圧縮が走らないことを確認する。
- [ ] 8-9. 新画像経路の失敗・停止・再実行テスト（1-9）を行い、過去の出力を今回の成功やサイズとして数えず、停止後に配置・フォールバックコピーされず、一時ファイルが安全に回収されることを確認する。
- [ ] 8-10. 新しい FFmpeg で10bit グラデーションの実変換テスト（6-4）を行う。ディザの画素検証と、ffprobe による8bit・BT.709タグ検証を別々の合格条件とし、固定ビルドと採用方式を記録する。
- [ ] 8-11. AVIF エンコードのCPU使用率・ピークメモリ・処理時間を、画像複数枚と画像/PDF/動画の混在入力で測定する。Pillow の AVIF エンコーダーも既定でCPU数相当のスレッドを使うため、画像 worker 数との積による過剰並列を確認し、必要なら保存時の `max_threads` または新経路の同時実行数を制限する。既存 JPEG / PNG の並列動作は不用意に変更しない。

---

## フェーズ9: リリース

- [ ] 9-1. D-13・D-14を含む実装前の決定事項が確定し、フェーズ0〜8の実装と検証が完了したら、アプリを v2.8.0 としてリリースする。

---

## Decisions（推奨。実装前に確認する）

- [x] D-1. 新しい経路はすべて既定で OFF にする。
- [x] D-2. 容量が増えても出力するのは、互換変換の2経路だけにする。AVIF 出力と AV1 出力では、容量が増えたら元ファイルを残す。
- [x] D-3. AVIF 出力の対象は、既定では JPEG だけにする。PNG（スクリーンショットや透過画像）は、AVIF にするとかえって大きくなることがあるため、利用者が選んだときだけ対象にする。
- [x] D-4. 動画の出力コーデックで AV1 を選んでいるときは、AV1→H.264 の互換変換を押せないようにする（互換変換 ON 時は `codec == 'libx264'` に固定し、契約でも検証する）。
- [x] D-5. 互換変換の ON / OFF は画像（AVIF→JPEG）と動画（AV1→H.264）で別々に設定できるようにする。いずれかの互換変換が ON の場合は「互換変換のみを行うモード」とし、ON にした互換変換の対象ファイル（画像の `.avif`、動画の AV1）以外には一切触らない（PDF・JPEG・PNG・AV1以外の動画の通常圧縮は行わない）。
- [x] D-6. AV1 の出力は 8bit（`yuv420p`）だけにする。10bit で出力する機能と、HDR を SDR に変換するトーンマッピングは今回のスコープ外とする。
- [x] D-7. 互換変換でも、音声・字幕などを保持できるかの判定と、出力の検証は省かない。
- [x] D-8. 同梱 FFmpeg のエンコーダーは SVT-AV1 にする。libaom（遅い）や、ハードウェアのエンコーダー（`av1_nvenc` など）は今回は使わない。
- [x] D-9. PDF の中の画像は、今までどおり JPEG / PNG のままにする（PDF の仕様上、AVIF は入れられない）。
- [x] D-10. 今回のスコープ外: AVIF→AVIF の再圧縮（リサイズだけする場合も含む）、WebP の出力、動く AVIF の変換。
- [x] D-11. AV1→H.264互換変換に限り、10bit SDRをディザ付きで8bitに変換する。HDR（PQ / HLG / Dolby Vision等）、BT.2020等の広色域、12bit以上はトーンマッピングや色変換を行わず元ファイルを残す。変換後は8bit `yuv420p` / BT.709とし、注記を記録する。
- [x] D-12. 完了画面の集計には互換変換で出力したファイルも件数・前後サイズともに含め、互換変換で合計サイズが増加した場合（`saved < 0`）は「削減」ではなく「増加」として表示する（A案）。
- [ ] D-13. 画像互換変換 ON 時の出力形式の正規化方法を確定する。候補は「UI の値自体を `original` に変更する」または「通常圧縮用の選択値を保持し、mapper で request の実効値だけ `original` にする」。OFF に戻したときの復元方針も合わせて決め、2-2・7-2の実装前に記録する。
- [ ] D-14. 動画互換変換と既存の動画有効設定の関係を確定する。候補は「動画が有効なときだけ互換変換を ON にでき、無効化時は互換変換も OFF にする」または「互換変換 ON の操作で動画も有効にする」。`enabled=False` / `video_config=None` との矛盾を request 生成時と backend 契約でどう防ぐかを含め、6-1・7-4の実装前に記録する。AV1出力選択時の排他条件はD-4を維持する。

## 未確定の論点

1. **AV1 の入力は、互換変換 ON でも元ファイルが残るケースがある。**
   - HDR、BT.2020等の広色域、12bit以上は今回の方針では対象外。
   - webm に入った WebVTT 字幕は、既存の保持判定で弾かれる場合がある。
   - 対象の10bit SDRは、色域がBT.709または未指定の入力に限る。
2. **SVT-AV1 の既定値（CRF、プリセット）は、フェーズ8-5 で測った結果を見て決める。** 現時点の値は仮置きとする。
3. **AV1 出力の処理時間が許容範囲かを確認する。** 動画は1本ずつ処理するので並列化による遅延は無いが、長い動画では数倍の時間がかかる可能性がある。
4. **UI のモード切替と request 正規化の仕様を実装前に確定する。** D-13・D-14が未確定のため、該当する契約・UI の実装にはまだ着手しない。
5. **ディザ方式と AVIF の並列度を実測で確定する。** ディザは6-4・8-10、AVIF のCPU・メモリ上限に関わる並列度は8-11で確認し、採用設定と測定結果を記録する。

## 変更履歴

| 日付 | 内容 |
|---|---|
| 2026-11-06 | 初版を作成 |
| 2026-11-06 | AV1→H.264互換変換では10bit SDRのみ8bit化して許可し、HDR・広色域・12bit以上は元ファイルを残す方針を反映 |
| 2026-11-06 | レビュー結果を反映: 互換変換ON時は対象ファイルのみ処理し対象外には触らない方針（画像・動画個別設定）、EXIF/ICC引き継ぎの安全化、完了画面集計のA案、FFmpegビルド要件（CMake/Meson/Ninja）と契約検証を明記 |
| 2026-11-06 | 追加レビューを反映: workerからCSV・コピー・集計までの対象外判定、動画の判定順序、画像失敗時の元拡張子コピーと停止・既存出力保護、明示的なディザ指定と画素検証を追加。UI設定正規化を実装前の未決事項D-13・D-14として整理し、互換変換8通りの統合テストとAVIFのCPU・メモリ測定を追記 |
| 2026-11-06 | フェーズ0を実装。デコーダー検出失敗時は詳細を通知し、AV1以外の動画処理を継続する方針を追加 |
