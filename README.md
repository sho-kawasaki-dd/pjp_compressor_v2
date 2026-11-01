# PDF / JPG / PNG Compressor v2

**Batch-compress PDF, JPEG, PNG, and video files by folder — Windows GUI application.**
フォルダ単位で PDF・JPEG・PNG・動画ファイルを一括圧縮できる Windows GUI アプリケーションです。

> Video support described below is **unreleased development functionality**; existing releases may not include it.
> 以下の動画機能は**未リリースの開発版**の機能です。既存のリリースには含まれない場合があります。

[![License: AGPL-3.0-or-later](https://img.shields.io/badge/License-AGPL--3.0--or--later-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.13%2B-blue)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-Windows-lightgrey)](https://www.microsoft.com/windows)

---

## Features / 主な機能

**PDF Compression / PDF 圧縮**
- **Ghostscript engine** — Re-distills PDFs using Ghostscript presets (`/screen`, `/ebook`, `/printer`, `/prepress`, `/default`) or custom DPI. Optional lossless pikepdf structural optimization can be combined.
  Ghostscript プリセット（`/screen` ～ `/prepress`）またはカスタム DPI で PDF を再蒸留。pikepdf 可逆最適化との組み合わせも可能。
- **Native engine** — Lossy/lossless/both modes using PyMuPDF (image recompression) + pikepdf (lossless optimization). CMYK-to-RGB normalization, soft-mask transparency preservation, PNG quantization via pngquant.
  PyMuPDF + pikepdf によるネイティブ処理。CMYK → RGB 正規化、soft mask 透過保持、pngquant PNG 量子化に対応。

**Image Compression / 画像圧縮**
- JPEG / PNG quality-controlled compression via Pillow (quality 0–100).
  Pillow による品質指定圧縮（0–100）。
- Lossy PNG compression via pngquant when available.
  pngquant によるPNG不可逆圧縮（利用可能な場合）。
- Batch resizing: manual (width / height) or long-edge preset (640–3840 px) with aspect-ratio preservation.
  バッチリサイズ：手動（幅/高さ）または長辺プリセット（640〜3840 px）、アスペクト比保持対応。

**Video Compression / 動画圧縮**
- ffmpeg / ffprobe process `.mp4`, `.mov`, `.avi`, `.mkv`, `.webm`, `.wmv`, and `.m4v`; H.264 / H.265, quality, preset, audio mode, and long-edge resizing are selectable.
  ffmpeg / ffprobe で `.mp4`、`.mov`、`.avi`、`.mkv`、`.webm`、`.wmv`、`.m4v` を処理し、H.264 / H.265、品質、速度、音声処理、長辺リサイズを選択できます。
- The first non-cover video, all audio and subtitle tracks, and related language, selection, chapter, orientation, and metadata information are preserved where possible. Additional video and cover art are outside the preservation target.
  最初のカバーアート以外の本編映像、全音声・全字幕、および言語・選択状態・チャプター・表示向き・メタデータなどの関連情報を可能な限り保持します。追加映像とカバーアートは保持対象外です。
- Audio defaults to copying AAC, MP3, AC-3, E-AC-3, ALAC, and FLAC. Other codecs, including Opus, are converted to AAC per track with a log notice; explicit AAC changes audio quality, and **No audio** removes all audio. Container support does not guarantee playback on every device.
  音声の既定はコピーで、AAC / MP3 / AC-3 / E-AC-3 / ALAC / FLAC が対象です。Opus などそれ以外はトラックごとに AAC へ変換し、ログに通知します。AAC 指定は音質を変え、**音声なし**は全音声を削除します。MP4 に格納できても全機器で再生できるとは限りません。
- HDR (including iPhone HDR), video over 8-bit, audio-only files, subtitles needing conversion or forced-subtitle flags, attachments, and unsupported data streams keep the original file. When publishing MP4, `tmcd` / `mebx` data streams are dropped and recorded in CSV notes.
  HDR（iPhone の HDR 撮影を含む）、8bit 超、映像なし、字幕変換が必要な動画・強制字幕、添付ファイルや未対応データストリームを含む動画は元ファイルを維持します。MP4 出力時は `tmcd` / `mebx` を削除し、CSV の備考に記録します。
- Only a smaller, verified result is published as MP4. Otherwise the original is copied with its original extension regardless of the mirror setting; an ordinary processing failure is copied only when mirroring is enabled.
  検証済みかつ元より小さい場合のみ MP4 を出力します。保持条件を満たせない場合やサイズが減らない場合は、ミラー設定に関係なく元の拡張子のままコピーします。通常の処理失敗時のコピーはミラー設定に従います。
- Only one job and one video encode run at a time; images and PDFs use separate workers. This does **not** cap CPU usage. Stop or exit waits for active work and leaves completed results in place.
  ジョブは同時に1件、動画エンコードは同時に1件です。画像・PDF は別ワーカーで処理します。CPU使用率の上限は**保証しません**。停止・終了時は実行中の処理を待ち、配置済みの結果は残ります。
- Output names are stable across reruns and existing destinations are overwritten. If a previous run produced an MP4 but a later run keeps a `.mov` original, the older MP4 remains.
  再実行時も出力名は変わらず、同名の既存出力は上書きします。前回 MP4 を出力した入力が次回 `.mov` の元維持になっても、古い MP4 は残ります。

**Archive & Workflow / アーカイブとワークフロー**
- Auto-extract ZIP archives with security checks (path traversal prevention, 10,000-member / 1 GB limits).
  ZIP 自動展開（パストラバーサル防止、メンバー数・サイズ上限付き）。
- Parallel processing via `ThreadPoolExecutor` for large batches.
  `ThreadPoolExecutor` による並列処理で大量ファイルにも対応。
- Per-file statistics and CSV log export.
  ファイルごとの圧縮統計と CSV ログ出力。
- Graceful degradation — app remains functional even when Ghostscript or pngquant is absent.
  Ghostscript / pngquant が未導入でもアプリは起動を継続し、該当機能のみ無効化されます。

**UI Localization / UI 多言語対応**
- Japanese / English UI localization is built in. All visible labels, dialogs, logs, and startup text are routed through locale files under `frontend/config_data/locales/`.
  日本語 / English の UI 多言語対応を組み込み済みです。表示ラベル、ダイアログ、ログ、起動時メッセージは `frontend/config_data/locales/` 配下のロケールファイルで管理されます。
- The language can be selected in the App Settings tab and is saved to `ui_catalogs.json` (`app_settings.language`), then applied on the next launch.
  言語はアプリ設定タブで選択でき、`ui_catalogs.json` の `app_settings.language` に保存されて、次回起動時に反映されます。
- Default folders and the desktop folder creation flow also follow the selected UI language.
  既定フォルダ名やデスクトップフォルダ作成の確認文も、選択した UI 言語に追従します。
- Task L-N: controller の状態更新をログ本文依存から `ProgressEvent` ベースへ整理し、cleanup 呼び出し境界も安定したキー渡しに変更しました。
- Task L-N: cleanup / image / PDF / worker のログ処理と message 合成を整え、JA/EN のログ多言語化を維持しやすい構成にしました。
- Task L-N: 関連する unit / integration テストを更新し、ログ本文の自然言語変更でも UI 状態が壊れないことを確認しました。
---

## Requirements / 動作環境

| | |
|---|---|
| **OS** | Windows 10 / 11 (64-bit) |
| **Python** | Not required for the installer edition / インストーラー版は不要 |
| **Ghostscript** | Optional — bundled in installer / 任意（インストーラーにバンドル） |
| **pngquant** | Optional — bundled in installer / 任意（インストーラーにバンドル） |
| **ffmpeg / ffprobe** | Both required for video; missing tools disable video only / 動画には両方必要。未検出時は動画のみ無効 |

---

## Installation / インストール

### Installer (recommended) / インストーラー（推奨）

1. Download an installer (`.exe`) from the [Releases](https://github.com/sho-kawasaki-dd/pjp_compressor_v2/releases) page.
   [Releases](https://github.com/sho-kawasaki-dd/pjp_compressor_v2/releases) ページからインストーラー（`.exe`）をダウンロードします。
2. Run the installer and follow the on-screen instructions.
   インストーラーを実行し、画面の指示に従います。
3. Launch **PDF JPG PNG Compressor** from the Start menu or desktop shortcut.
   スタートメニューまたはデスクトップのショートカットからアプリを起動します。

> Ghostscript and pngquant are bundled with the installer and require no separate installation.
> Ghostscript および pngquant はインストーラーにバンドルされており、別途インストールは不要です。

---

## Usage / 使い方

1. **Select input folder / 入力フォルダを選択**
   Click "Browse" or drag-and-drop a folder onto the input field.
   「参照」ボタンをクリックするか、入力フィールドにフォルダをドラッグ＆ドロップします。

2. **Select output folder / 出力フォルダを選択**
   Choose a destination folder for compressed files.
   圧縮後のファイルを保存するフォルダを選択します。

3. **Configure settings / 設定を選択**
   Use the four tabs: Compression Settings, Output Settings, App Settings, and Log / Progress.
   「圧縮設定」「出力設定」「アプリ設定」「ログ・進捗」の4タブから設定します。

4. **Run / 実行**
   Click "Start" to begin, or "Stop" to cancel and display partial totals. A second job or cleanup cannot start while work is running.
   「開始」で処理を実行し、「停止」で中断して部分集計を表示します。実行中は別のジョブやクリーンアップを開始できません。

5. **Review results / 結果を確認**
   Total savings and per-file statistics are displayed after processing. Optionally export a CSV log.
   処理完了後、合計削減量とファイルごとの統計が表示されます。CSV ログのエクスポートも可能です。

The output folder contains a hidden `.pjp_work/` directory for the output lock and video work files; output cleanup excludes it. Compression and output cleanup cannot use the same output folder concurrently, even from different app instances.
出力フォルダ直下にはロックと動画作業用の隠しフォルダ `.pjp_work/` が作られ、出力クリーンアップから除外されます。別インスタンスを含め、同じ出力先への圧縮・出力クリーンアップは同時に実行できません。

**Warning / 注意:** Input cleanup now also permanently deletes the video extensions listed above, including files in subfolders, regardless of whether video compression is enabled. Check the target folder before confirming.
**注意:** 入力クリーンアップは動画圧縮の有効・無効に関係なく、上記の動画拡張子もサブフォルダを含めて**取り消し不可で削除**します。実行前に対象フォルダを確認してください。

---

## Architecture / アーキテクチャ

This project follows a frontend / backend separation pattern with contract-based communication (Pydantic-like data models).
フロントエンド / バックエンド分離構成で、契約ベースのデータモデルを通じて通信します。

For detailed flow, sequence, and class diagrams, see:
詳細なフロー・シーケンス・クラス図は以下を参照してください:

- [Documentation/flow_sequence_and_class_diagrams.md](Documentation/flow_sequence_and_class_diagrams.md)
- [Documentation/README.md](Documentation/README.md) *(Japanese / 日本語)*

---

## For Developers / 開発者向け

### Prerequisites / 前提条件

- Python 3.13+
- PowerShell (Windows)

### Setup from source / ソースからのセットアップ

```powershell
# Install uv if needed, then sync the project environment
# uv が未導入の場合は先にインストールし、プロジェクト環境を同期します

uv sync
.\.venv\Scripts\Activate.ps1
```

### Run / 起動

```powershell
uv run python compressor_launcher_tkinter.py
```

### Run tests / テスト実行

```powershell
uv run pytest
```

Available markers / 使用可能なマーカー:

| Marker | Description |
|---|---|
| `unit` | Fast isolated tests / 高速な単体テスト |
| `integration` | Multi-module tests with real files / 実ファイルを使う統合テスト |
| `regression` | Previously fragile scenarios / 過去に不安定だったシナリオ |
| `requires_tk` | Requires a Tk runtime / Tk ランタイムが必要 |
| `requires_external` | Requires external tools such as Ghostscript, pngquant, or ffmpeg / 外部ツールが必要 |

```powershell
# Run only unit tests / ユニットテストのみ実行
uv run pytest -m unit
```

### Build installer / インストーラービルド

```powershell
# Builds PyInstaller executable + Inno Setup installer
# PyInstaller 実行ファイル + Inno Setup インストーラーをビルド
.\compressor_launcher.ps1 -Mode Build
```

---

## License / ライセンス

This project is licensed under the [GNU Affero General Public License v3.0 or later](LICENSE) (AGPL-3.0-or-later).
本プロジェクトは [GNU Affero General Public License v3.0 以降](LICENSE)（AGPL-3.0-or-later）のもとで公開されています。

The development bundle uses gyan.dev FFmpeg `9.0.2-full_build` (GPL v3, static build; includes libx264 / libx265 and FFmpeg's AAC encoder). The binaries, license, and build information are under `vendor/ffmpeg-windows/`; a frozen build places them under `_internal/vendor/ffmpeg-windows/`. System `ffmpeg` / `ffprobe` take precedence over bundled tools, and detection is cached until the app restarts.
開発版の同梱候補は gyan.dev FFmpeg `9.0.2-full_build`（GPL v3、静的ビルド。libx264 / libx265 と FFmpeg の AAC エンコーダを含む）です。実行ファイル・ライセンス・ビルド情報は `vendor/ffmpeg-windows/`、凍結版では `_internal/vendor/ffmpeg-windows/` に配置されます。system の `ffmpeg` / `ffprobe` が優先され、検出結果はアプリ再起動までキャッシュされます。

**Distribution is not yet cleared:** the exact corresponding source, external-library revisions, patches, build scripts, and licensing compatibility still need to be obtained, retained, and reviewed. The [FFmpeg source commit](https://github.com/FFmpeg/FFmpeg/commit/946fcce07b) and [upstream builds](https://www.gyan.dev/ffmpeg/builds/) are references, not a complete corresponding-source offer. Do not redistribute the bundled binaries until these requirements are resolved.
**配布準備は未完了です。** 対応ソース一式、外部ライブラリのリビジョン、パッチ、ビルドスクリプトの確保・保管とライセンス互換性の確認が必要です。[FFmpeg のソースコミット](https://github.com/FFmpeg/FFmpeg/commit/946fcce07b) と[上流のビルド配布元](https://www.gyan.dev/ffmpeg/builds/)は参考情報であり、対応ソース一式の提供を意味しません。これらの条件が整うまで同梱バイナリを再配布しないでください。

See the [FFmpeg distribution audit](Documentation/ffmpeg-distribution-audit.md) for verified package facts and remaining checks.
確認できたパッケージ情報と未完了項目は[FFmpeg 配布物の調査記録](Documentation/ffmpeg-distribution-audit.md)を参照してください。
