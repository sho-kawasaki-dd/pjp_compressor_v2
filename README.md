# PDF / JPG / PNG Compressor v2

**Batch-compress PDF, JPEG, and PNG files by folder — Windows GUI application.**
フォルダ単位で PDF・JPEG・PNG ファイルを一括圧縮できる Windows GUI アプリケーションです。

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

**Archive & Workflow / アーカイブとワークフロー**
- Auto-extract ZIP archives with security checks (path traversal prevention, 10,000-member / 1 GB limits).
  ZIP 自動展開（パストラバーサル防止、メンバー数・サイズ上限付き）。
- Parallel processing via `ThreadPoolExecutor` for large batches.
  `ThreadPoolExecutor` による並列処理で大量ファイルにも対応。
- Per-file statistics and CSV log export.
  ファイルごとの圧縮統計と CSV ログ出力。
- Graceful degradation — app remains functional even when Ghostscript or pngquant is absent.
  Ghostscript / pngquant が未導入でもアプリは起動を継続し、該当機能のみ無効化されます。

---

## Requirements / 動作環境

| | |
|---|---|
| **OS** | Windows 10 / 11 (64-bit) |
| **Python** | Not required for the installer edition / インストーラー版は不要 |
| **Ghostscript** | Optional — bundled in installer / 任意（インストーラーにバンドル） |
| **pngquant** | Optional — bundled in installer / 任意（インストーラーにバンドル） |

---

## Installation / インストール

### Installer (recommended) / インストーラー（推奨）

1. Download the latest installer (`.exe`) from the [Releases](../../releases) page.
   [Releases](../../releases) ページから最新のインストーラー（`.exe`）をダウンロードします。
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
   Choose the compression engine, quality, resize options, and other preferences from the tabs.
   タブからエンジン・品質・リサイズオプションなどを設定します。

4. **Run / 実行**
   Click "Start" to begin batch compression. Progress is shown in the log area.
   「開始」をクリックしてバッチ圧縮を実行します。ログエリアに進捗が表示されます。

5. **Review results / 結果を確認**
   Total savings and per-file statistics are displayed after processing. Optionally export a CSV log.
   処理完了後、合計削減量とファイルごとの統計が表示されます。CSV ログのエクスポートも可能です。

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
# Clone the repository and navigate to the project folder
# リポジトリをクローンしてプロジェクトフォルダへ移動

python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### Run / 起動

```powershell
python compressor_launcher_tkinter.py
```

### Run tests / テスト実行

```powershell
pytest
```

Available markers / 使用可能なマーカー:

| Marker | Description |
|---|---|
| `unit` | Fast isolated tests / 高速な単体テスト |
| `integration` | Multi-module tests with real files / 実ファイルを使う統合テスト |
| `regression` | Previously fragile scenarios / 過去に不安定だったシナリオ |
| `requires_tk` | Requires a Tk runtime / Tk ランタイムが必要 |
| `requires_external` | Requires Ghostscript or pngquant / 外部ツールが必要 |

```powershell
# Run only unit tests / ユニットテストのみ実行
pytest -m unit
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
