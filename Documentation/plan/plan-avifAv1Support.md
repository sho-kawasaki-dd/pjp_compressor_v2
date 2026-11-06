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

---

## フェーズ0: AV1 入力の事前判定（今起きている失敗への対策）

AV1 を読めない環境では、変換を始める前に AV1 の入力を見つけて元ファイルを残す。

- [ ] 0-1. [capabilities.py](../../backend/capabilities.py) で、`-decoders` の一覧から `libdav1d` か `libaom-av1` を探すようにする。結果は [contracts.py](../../backend/contracts.py) の `CapabilityReport` に `av1_decode_available: bool` として追加する。
- [ ] 0-2. [video_utils.py](../../backend/core/video_utils.py) の `_compress()` で、HEVC の判定のすぐ後に AV1 の判定を入れる。入力が AV1 で、かつ `av1_decode_available` が False なら `keep('retention', ['av1_decoder_unavailable'])` を返す。
- [ ] 0-3. `parse_probe_json()` の `MediaInfo` に、`contains_hevc` と同じ形で `contains_av1` を追加する。
- [ ] 0-4. 元ファイルを残した理由 `av1_decoder_unavailable` の表示文言を [ja.json](../../frontend/config_data/locales/ja.json) と [en.json](../../frontend/config_data/locales/en.json) に追加する。
- [ ] 0-5. テストを追加する: `test_capabilities.py`（デコーダーの検出）、`test_video_utils.py`（AV1 入力で元ファイルが残る）、`test_video_ffmpeg.py`（同梱 FFmpeg で、理由が `av1_decoder_unavailable` になる）。

---

## フェーズ1: 画像の共通基盤（拡張子が変わる出力に対応する）

AVIF 出力と AVIF→JPEG はどちらも拡張子が変わり、「元ファイルを残す」場合もある。動画にしか無いこの仕組みを、画像にも使えるようにする。

- [ ] 1-1. [image_utils.py](../../backend/core/image_utils.py) で、`compress_image_pillow()` と `compress_png_pngquant()` に重複しているリサイズ処理を、helper 関数 `_apply_resize(img, resize_cfg)` に切り出す。動作は変えない。
- [ ] 1-2. EXIF・ICC プロファイル・画像の向きを引き継ぐ helper を追加する。保存時に `exif` と `icc_profile` を渡す。
- [ ] 1-3. 画像処理の戻り値に、実際に書き出したパス（`final_outpath`）と元ファイルを残した理由（`kept_original_reason`）を持てるようにする。動画の `VideoCompressResult` と同じ考え方にする。既存の `(ok, message)` を返す関数は、互換のため残す。
- [ ] 1-4. [worker_ops.py](../../backend/core/worker_ops.py) で、画像の結果からも `final_outpath` と `kept_original_reason` を受け取り、出力サイズと CSV に反映する。
- [ ] 1-5. [job_runner.py](../../backend/orchestrator/job_runner.py) の `_plan_video_outputs()` を、拡張子が変わるファイルなら何でも扱える `_plan_converted_outputs()` に一般化する。
  - 変換後の拡張子は、入力の拡張子と設定から決める関数で返す（例: `.jpg→.avif`、`.avif→.jpg`、動画 `→.mp4`）。
  - 名前が衝突したら回避する。例: 入力に `photo.jpg` と `photo.avif` が両方あり、AVIF 出力も ON の場合。
  - 元ファイルを残す場合に備えて、元と同じ拡張子の出力パス（`original_outpath`）も画像のタスクに持たせる。
- [ ] 1-6. 「容量が増えたら元ファイルを残す」画像用の共通処理を追加する。一時ファイルに書き出し、サイズを比べてから正式な場所に置く。動画の `_publish()` と同じ流れにする。
- [ ] 1-7. テストを追加する: リサイズ helper の切り出しで動作が変わらないこと、拡張子が変わる出力名の計画、名前の衝突回避。

---

## フェーズ2: AVIF 出力（JPEG / PNG → AVIF）

- [ ] 2-1. [backend/settings.py](../../backend/settings.py) に次の既定値を追加する。
  - `IMAGE_OUTPUT_FORMAT_DEFAULT = 'original'`（選択肢は `'original'` と `'avif'`）
  - `AVIF_QUALITY_DEFAULT`（候補: 60）、`AVIF_SPEED_DEFAULT`（候補: 6、範囲は 0〜10）
  - `AVIF_TARGET_PNG_DEFAULT = False`
- [ ] 2-2. [contracts.py](../../backend/contracts.py) の `CompressionRequest` と `to_legacy_kwargs()` に、`image_output_format`、`avif_quality`、`avif_speed`、`avif_include_png` を追加し、範囲を検証する。
- [ ] 2-3. [image_utils.py](../../backend/core/image_utils.py) に `compress_image_to_avif()` を追加する。
  - CMYK を RGB に変換する。リサイズする。EXIF と ICC を引き継ぐ。
  - Pillow の `save(format='AVIF', quality=..., speed=...)` で保存する。
  - 透過（アルファ）は残す。
  - **出力が元以上の大きさなら元ファイルを残す**（理由: `no_gain`）。
- [ ] 2-4. [worker_ops.py](../../backend/core/worker_ops.py) で、`image_output_format == 'avif'` のとき、`jpg` と `jpeg` を AVIF の経路に回す。`png` は `avif_include_png` が True のときだけ回し、False なら今までどおり pngquant / Pillow で処理する。
- [ ] 2-5. AVIF が使えない環境（`features.check('avif')` が False）を検出する。
  - `CapabilityReport` に `avif_available` を追加する。
  - 使えない環境で AVIF が指定されたら、ジョブ開始前の検証でエラーにする。今の圧縮経路に黙って戻すことはしない。
- [ ] 2-6. テストを追加する: AVIF で出力されること、容量が増えたら元ファイルが残ること、透過・EXIF・ICC が残ること、PNG を対象にするかどうかの切り替え。

---

## フェーズ3: 互換変換 AVIF → JPEG

- [ ] 3-1. `CompressionRequest` に `avif_to_jpeg_compat: bool` を追加する。既定は False。JPEG の品質は既存の `jpg_quality` を使う。
- [ ] 3-2. [image_utils.py](../../backend/core/image_utils.py) に `convert_avif_to_jpeg()` を追加する。
  - 透過部分は白で塗りつぶす。CMYK を RGB に変換する。リサイズする。EXIF と ICC を引き継ぐ。
  - 動く AVIF（複数フレーム）は変換せず、元ファイルを残す（理由: `animated_avif`）。
  - 10bit や HDR の AVIF は 8bit の sRGB に変換して出力し、注記 `hdr_or_high_bitdepth_flattened` を残す。
  - **元より大きくても出力する**。容量が増えた場合は注記 `size_increased` を残す。
- [ ] 3-3. [worker_ops.py](../../backend/core/worker_ops.py) に `avif` の分岐を追加する。`avif_to_jpeg_compat` が ON のときだけ処理し、OFF なら今までどおり対象外のファイルとして扱う。
- [ ] 3-4. [job_runner.py](../../backend/orchestrator/job_runner.py) で、互換変換が ON のときだけ処理対象の拡張子（`compressible_extensions`）に `avif` を加える。
- [ ] 3-5. テストを追加する: 容量が増えても出力されること、動く AVIF は元ファイルが残ること、透過が白になること、OFF のとき対象外のファイルとして扱われること。

---

## フェーズ4: FFmpeg の作り直しと配布の再承認（フェーズ5・6 の前提）

- [ ] 4-1. ビルドスクリプトを作る。[build_ffmpeg_x264.sh](../../scripts/build_ffmpeg_x264.sh) を元に `build_ffmpeg_x264_av1.sh` を作り、`--enable-libsvtav1 --enable-libdav1d` を追加する。x264 は残す（ライセンスは GPLv3 のまま）。
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
- [ ] 5-2. [contracts.py](../../backend/contracts.py) の `VideoCompressionConfig` で、`codec` の型（`Literal`）を広げ、コーデックごとの範囲で検証する。
- [ ] 5-3. [capabilities.py](../../backend/capabilities.py) で、確認するエンコーダーに `libsvtav1` を加える（`_TRACKED_ENCODERS`）。動画が使えるかの判定は、`libx264` 固定ではなく、選んだコーデックが使えるかで決める。
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

- [ ] 6-1. `VideoCompressionConfig` に `av1_to_h264_compat: bool` を追加する。既定は False。エンコードには既存の x264 の CRF とプリセットを使う。
- [ ] 6-2. [video_utils.py](../../backend/core/video_utils.py) の `_compress()` で、入力ごとに次のとおり処理する。

  | 入力 | 条件 | 動作 |
  |---|---|---|
  | AV1 | AV1 を読めない | 元ファイルを残す（`av1_decoder_unavailable`。フェーズ0） |
  | AV1 | 互換変換 ON、8bit以下、SDR、色域がBT.709または未指定 | x264 で出力する。音声・字幕などを保持できるかの判定と、出力の検証は行う。**元より小さいかどうかの判定だけ省く** |
  | AV1 | 互換変換 ON、10bit SDR、色域がBT.709または未指定 | 10bitから8bitへディザを用いて変換し、x264で出力する。注記 `bit_depth_reduced=10->8` を記録する |
  | AV1 | 互換変換 ON、HDR / 色域がBT.2020等 / 12bit以上 | トーンマッピング等は行わず、元ファイルを残す |
  | AV1 | 互換変換 OFF | 選んだコーデックで、通常の圧縮として扱う |
  | AV1 以外 | — | 今までと同じ |

- [ ] 6-3. 10bit SDR の許可条件を実装する。互換変換が ON の場合に限り、ビット深度が10bitで、HDR（PQ / HLG / Dolby Vision等）ではなく、色域がBT.709または未指定の入力を8bit変換の対象にする。12bit以上、HDR、BT.2020等の広色域は `retention` とする。通常の圧縮とAV1出力では、従来どおり8bitを超える入力を許可しない。
- [ ] 6-4. 10bit SDRから8bitへの変換時はディザを適用し、出力を `yuv420p` / BT.709として明示する。ffprobeで出力の画素形式と色特性を確認し、出力検証に含める。入力の色特性が未指定の場合のBT.709扱いもテストで固定する。
- [ ] 6-5. 互換変換では、選んだコーデックに関係なく、映像のエンコーダーを `libx264` に固定する。そのため `build_ffmpeg_command()` に、コーデックを上書きする手段を用意する。
- [ ] 6-6. 互換変換で出力したら、結果の注記に `compat_conversion` を入れる。容量が増えた場合は `size_increased` も入れる。10bit SDRを8bitにした場合は `bit_depth_reduced=10->8` も記録する。
- [ ] 6-7. テストを追加する: 容量が増えても出力されること、10bit SDRが8bitで変換されBT.709タグを持つこと、10bit HDR・BT.2020・12bit入力は互換変換 ON でも元ファイルが残ること、互換変換 OFFでは従来どおり8bit超の入力が保持されること。

---

## フェーズ7: UI・CSV・翻訳文・配布・文書

### UI
- [ ] 7-1. 画像の設定に「出力形式」を追加する（元の形式 / AVIF）。AVIF を選んだときだけ、次の設定を押せるようにする。
  - AVIF の品質スライダー
  - 速度
  - PNG も対象にするか
  - 対象: [ui_tkinter_view.py](../../frontend/ui_tkinter_view.py)、[ui_tkinter_state.py](../../frontend/ui_tkinter_state.py)、[ui_contracts.py](../../frontend/ui_contracts.py)、[ui_tkinter_mapper.py](../../frontend/ui_tkinter_mapper.py)
- [ ] 7-2. 画像の設定にチェックボックス「AVIF を JPEG に変換（互換性優先・容量が増える場合あり）」を追加する。
- [ ] 7-3. 動画の設定で、固定表示のコーデック欄（`video_codec_label`）を、H.264 / AV1 を選べるコンボボックスに変える。コーデックに合わせて、品質の目安表示（CRF）とプリセットの選択肢を切り替える。
- [ ] 7-4. 動画の設定にチェックボックス「AV1 動画を H.264 に変換（互換性優先・容量が増える場合あり）」を追加する。
- [ ] 7-5. その環境で使えない機能は、押せないようにして理由をツールチップで示す。判定に使う項目は次のとおり。
  - `avif_available`
  - `libsvtav1` が使えるか
  - `av1_decode_available`
- [ ] 7-6. コントローラーのジョブ開始ログ（[ui_tkinter_controller.py](../../frontend/ui_tkinter_controller.py)）に、出力形式と互換変換の設定を出す。
- [ ] 7-7. 設定の保存と読み込みがあれば、新しい項目を加え、古い設定ファイルを読んだときは既定値を使う。

### CSV・ログ・翻訳文
- [ ] 7-8. CSV の処理種別を追加する: `csv_action_avif`、`csv_action_compat_jpeg`、`csv_action_compat_h264`、`csv_action_kept_no_gain`（画像用）。
- [ ] 7-9. 完了画面の削減量の集計から、互換変換で出力したファイルを除外する（CSV には記録する）。
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

---

## フェーズ9: リリース

- [ ] 9-1. フェーズ0〜8の実装と検証が完了したら、アプリを v2.8.0 としてリリースする。

---

## Decisions（推奨。実装前に確認する）

- [ ] D-1. 新しい経路はすべて既定で OFF にする。
- [ ] D-2. 容量が増えても出力するのは、互換変換の2経路だけにする。AVIF 出力と AV1 出力では、容量が増えたら元ファイルを残す。
- [ ] D-3. AVIF 出力の対象は、既定では JPEG だけにする。PNG（スクリーンショットや透過画像）は、AVIF にするとかえって大きくなることがあるため、利用者が選んだときだけ対象にする。
- [ ] D-4. 動画の出力コーデックで AV1 を選んでいるときは、AV1→H.264 の互換変換を押せないようにする。AV1 を選ぶのに AV1 を H.264 に戻すという、矛盾した指定を防ぐため。
- [ ] D-5. AVIF 出力の ON と AVIF→JPEG の ON は同時に選べるようにする。どちらも入力の種類が違うので干渉しない。
- [ ] D-6. AV1 の出力は 8bit（`yuv420p`）だけにする。10bit で出力する機能と、HDR を SDR に変換するトーンマッピングは今回のスコープ外とする。
- [ ] D-7. 互換変換でも、音声・字幕などを保持できるかの判定と、出力の検証は省かない。
- [ ] D-8. 同梱 FFmpeg のエンコーダーは SVT-AV1 にする。libaom（遅い）や、ハードウェアのエンコーダー（`av1_nvenc` など）は今回は使わない。
- [ ] D-9. PDF の中の画像は、今までどおり JPEG / PNG のままにする（PDF の仕様上、AVIF は入れられない）。
- [ ] D-10. 今回のスコープ外: AVIF→AVIF の再圧縮（リサイズだけする場合も含む）、WebP の出力、動く AVIF の変換。
- [x] D-11. AV1→H.264互換変換に限り、10bit SDRをディザ付きで8bitに変換する。HDR（PQ / HLG / Dolby Vision等）、BT.2020等の広色域、12bit以上はトーンマッピングや色変換を行わず元ファイルを残す。変換後は8bit `yuv420p` / BT.709とし、注記を記録する。

## 未確定の論点

1. **AV1 の入力は、互換変換 ON でも元ファイルが残るケースがある。**
   - HDR、BT.2020等の広色域、12bit以上は今回の方針では対象外。
   - webm に入った WebVTT 字幕は、既存の保持判定で弾かれる場合がある。
   - 対象の10bit SDRは、色域がBT.709または未指定の入力に限る。
2. **SVT-AV1 の既定値（CRF、プリセット）は、フェーズ8-5 で測った結果を見て決める。** 現時点の値は仮置きとする。
3. **AV1 出力の処理時間が許容範囲かを確認する。** 動画は1本ずつ処理するので並列化による遅延は無いが、長い動画では数倍の時間がかかる可能性がある。

## 変更履歴

| 日付 | 内容 |
|---|---|
| 2026-11-06 | 初版を作成 |
| 2026-11-06 | AV1→H.264互換変換では10bit SDRのみ8bit化して許可し、HDR・広色域・12bit以上は元ファイルを残す方針を反映 |
