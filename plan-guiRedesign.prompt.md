## Plan: GUI リデザイン — tkinter版 + PySide6版 並行作成

**TL;DR**
現行 `ui_app.py` を全面リデザインし、タブ構成・LabelFrame/GroupBox セクション分け・新 PDF エンジン UI を備えた2つの GUI スクリプトを並行作成する。`ui_tkinter.py` (tkinter+ttk) と `ui_pyside.py` (PySide6) は同一の機能・レイアウト構造を持ち、バックエンドは共通の `compressor_utils.py` を呼ぶ。比較検討後にどちらを採用するか決定。

---

**Steps**

### Step 1: `ui_tkinter.py` 新規作成（tkinter + ttk版）

1. インポートを刷新: `GS_OPTIONS`, `GS_COMMAND`, `PYPDF_AVAILABLE` を削除。新定数 `PDF_COMPRESS_MODES`, `PDF_LOSSY_DPI_DEFAULT`, `PDF_LOSSY_DPI_RANGE`, `PDF_LOSSY_JPEG_QUALITY_DEFAULT`, `PDF_LOSSY_PNG_TO_JPEG_DEFAULT`, `PDF_LOSSLESS_OPTIONS_DEFAULT`, `GS_PRESETS`, `GS_DEFAULT_PRESET` をインポート
2. `App` クラス `__init__` で新 tkinter 変数群を定義:
   - `self.pdf_engine` (StringVar `'native'`), `self.pdf_mode` (StringVar `'both'`), `self.pdf_dpi` (IntVar 150), `self.pdf_jpeg_quality` (IntVar 75), `self.pdf_png_to_jpeg` (BooleanVar False)
   - `self.pdf_ll_linearize`, `self.pdf_ll_object_streams`, `self.pdf_ll_clean_metadata`, `self.pdf_ll_recompress_streams`, `self.pdf_ll_remove_unreferenced` (各 BooleanVar)
   - `self.gs_preset` (StringVar `'ebook'`), `self.gs_custom_dpi` (IntVar 150), `self.gs_use_lossless` (BooleanVar True)
   - 従来: `self.jpg_quality`, `self.png_quality`, `self.use_pngquant`, リサイズ系, CSV 系はそのまま
3. `ttk.Notebook` でタブ構成（圧縮設定 / ログ進捗）、タブ外にフォルダ選択行 + アクションボタン + D&D 対応
4. 圧縮設定タブ内に `ttk.LabelFrame` × 4（PDF圧縮 / 画像圧縮 / リサイズ / 出力設定）
5. PDF圧縮 LabelFrame 内: エンジン選択ラジオ2個 → ネイティブ/GS コントロール群を `tk.Frame` で切り替え表示。GS カスタムは6番目のラジオ「カスタム」+ DPI スライダー（36-600）
6. `_update_pdf_controls()`: エンジン選択 + モード選択に応じてウィジェットの `state` と表示/非表示を制御。`png_to_jpeg` OFF 時に JPEG 品質スライダー横に「※JPEG元画像にのみ適用」表示
7. `_refresh_pdf_engine_status()`: `get_ghostscript_path()` (compressor_utils 由来) の結果 + fitz/pikepdf インポート可否を確認、GS 未検出時は GS ラジオを `state='disabled'`
8. `start_compress()`: 新シグネチャの `compress_folder()` を keyword 引数で呼び出し。`pdf_engine` に応じて native/gs パラメータを構築
9. D&D: `tkinterdnd2` の try/except パターンは現行踏襲
10. 音声再生: `sound_utils` から `init_mixer`, `play_sound` を現行通り利用
11. 旧 `ui_app.py` の非 PDF 機能（cleanup, resize, CSV, log, progress, stats）は構造を維持して移植

### Step 2: `ui_pyside.py` 新規作成（PySide6版）

1. `from PySide6.QtWidgets import ...`, `from PySide6.QtCore import ...` で構築
2. `QMainWindow` ベースの `App` クラス。`QTabWidget` でタブ構成
3. レイアウトは `QVBoxLayout`, `QHBoxLayout`, `QGroupBox`（≒ LabelFrame）, `QGridLayout`
4. PDF 圧縮セクション: `QRadioButton` × 2（エンジン）、`QRadioButton` × 3（モード）、`QSlider`（DPI, JPEG品質）、`QCheckBox` 群、`QStackedWidget` or 表示切替でネイティブ/GS パネル切替
5. GS カスタム DPI: 6番目のラジオ + `QSlider`(36-600)
6. D&D: `QWidget.setAcceptDrops(True)` + `dragEnterEvent`/`dropEvent` オーバーライド（ネイティブ対応、外部ライブラリ不要）
7. スレッド: `QThread` + `Signal` でログ・進捗・統計を GUI スレッドに安全に送信（tkinter 版の `self.log` 直接呼び出しパターンとは異なるスレッド安全設計）
8. 音声再生: `sound_utils` を同様に利用（pygame は Qt とは独立）
9. `compress_folder()` 呼び出しは keyword 引数で tkinter 版と同一
10. `pyproject.toml` に PySide6 をオプショナル依存として追加（`[project.optional-dependencies]` の `qt` グループ）

### Step 3: エントリポイント更新

1. `compressor_launcher.py` を更新し、引数 or 環境変数で `ui_tkinter` / `ui_pyside` を切り替え可能に。デフォルトは `ui_tkinter`
2. `compressor_utils.py` の `get_ghostscript_path()` を GUI 側でも呼べるように公開関数として活用（既に公開済み）

### Step 4: `compressor_launcher.spec` 更新

1. PySide6 の hidden imports を追加（オプショナル）

---

**共通レイアウト設計**

```
┌─ フォルダ選択（常時表示）─────────────────────┐
│ 入力: [________] [選択] [クリーンアップ]  D&D ▼ │
│ 出力: [________] [選択] [クリーンアップ]        │
└───────────────────────────────────────────────┘
┌─ タブ ─────────────────────────────────────────┐
│ [圧縮設定]  [ログ/進捗]                         │
│                                                 │
│  ◆ 圧縮設定タブ:                                │
│  ┌─ PDF圧縮 ───────────────────────────────┐    │
│  │ エンジン: ◉ ネイティブ ○ GhostScript     │    │
│  │                                          │    │
│  │ ── ネイティブ時 ──                        │    │
│  │ モード: ◉ 両方 ○ 非可逆 ○ 可逆           │    │
│  │ [非可逆] DPIスライダー / JPEG品質スライダー│    │
│  │          ☐ PNG→JPEG変換                   │    │
│  │ [可逆]   ☐ Linearize  ☐ ObjStream       │    │
│  │          ☐ メタデータ除去 ☐ Flate再圧縮   │    │
│  │          ☐ 孤立リソース削除               │    │
│  │                                          │    │
│  │ ── GS時 ──                                │    │
│  │ プリセット: ◉ebook ○screen ○printer ...   │    │
│  │            ○ カスタム [DPIスライダー]       │    │
│  │ ☐ pikepdf構造最適化も適用                  │    │
│  │   └ (可逆オプション群 — 上記と共通)        │    │
│  └──────────────────────────────────────────┘    │
│  ┌─ 画像圧縮 ──────────────────────────────┐    │
│  │ JPG品質: [スライダー]  値ラベル           │    │
│  │ PNG品質: [スライダー]  値ラベル           │    │
│  │ ☐ pngquant使用                           │    │
│  └──────────────────────────────────────────┘    │
│  ┌─ リサイズ ──────────────────────────────┐    │
│  │ ☐ リサイズ有効                           │    │
│  │ ◉ 手動 幅[__] 高さ[__] ☐ アスペクト維持  │    │
│  │ ○ 長辺指定 [コンボボックス]               │    │
│  └──────────────────────────────────────────┘    │
│  ┌─ 出力設定 ──────────────────────────────┐    │
│  │ ☐ CSVログ出力 [パス入力] [参照]           │    │
│  │ ☐ ZIP展開してから圧縮                     │    │
│  └──────────────────────────────────────────┘    │
│                                                 │
│  ◆ ログ/進捗タブ:                               │
│  [プログレスバー]                                │
│  統計: 処理前                                    │
│  ┌─ ログ ──────────────────────────────────┐    │
│  │ (スクロール可能テキストエリア)             │    │
│  └──────────────────────────────────────────┘    │
└───────────────────────────────────────────────┘
┌─ アクション（常時表示）───────────────────────┐
│        [圧縮開始]   [終了]                      │
└───────────────────────────────────────────────┘
```

---

**Verification**

- 両バージョンで全機能（PDF 非可逆/可逆/両方、GS モード、JPG/PNG 圧縮、リサイズ、CSV、ZIP 展開、クリーンアップ、D&D、音声再生）が動作すること
- エンジン切替・モード切替で UI コントロールの有効化/無効化が正しく連動すること
- GS 未インストール環境で GS ラジオが無効化されること
- `compress_folder()` の呼び出しが keyword 引数で正しくマッピングされること
- PySide6 版のスレッド安全性（Signal/Slot 経由のログ更新）が正しく動作すること

---

**Decisions**

- **タブ構成**: [圧縮設定] [ログ/進捗] の2タブ。フォルダ選択とアクションボタンはタブ外に常時表示
- **LabelFrame/GroupBox**: PDF圧縮 / 画像圧縮 / リサイズ / 出力設定の4セクション
- **GS カスタム DPI**: 5プリセット + 6番目の「カスタム」ラジオ → DPI スライダー（36-600, デフォルト150）
- **ファイル名**: `ui_tkinter.py` / `ui_pyside.py`
- **比較検討用**: 両方完成後にどちらを採用するか決定。旧 `ui_app.py` は参照用に残す
- **D&D**: tkinter 版は tkinterdnd2、PySide6 版はネイティブ D&D
- **音声**: 両方で pygame 経由の `sound_utils` を維持
- **スレッド安全性**: tkinter 版は従来通り直接呼び出し（tkinter は `after()` 不使用でも概ね安全）、PySide6 版は `Signal` 経由
