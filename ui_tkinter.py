#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ui_tkinter.py

tkinter + ttk ベースの GUI を提供するモジュール。圧縮ロジックは `compressor_utils`
に委譲し、ユーザー操作（フォルダ選択、PDF エンジン切替、品質設定、プリセット、
進捗表示、CSV ログの有効化など）を受け付ける。

レイアウト構成:
- フォルダ選択行（常時表示、D&D 対応）
- タブ（圧縮設定 / ログ）
    - 圧縮設定: PDF操作エリア / 画像操作エリア（圧縮・リサイズ・出力）
    - ログ: 統計 / ログテキスト
- 進捗行（常時表示）: 状態文言 / プログレスバー
- アクションボタン行（常時表示）

設計ポイント:
- 処理はスレッドで非同期化し、UI の応答性を保持。
- PDF エンジン（ネイティブ / GhostScript）を UI から選択可能。
- エンジン未検出時は対応ラジオを自動的に無効化。
- ドラッグ＆ドロップは `tkinterdnd2` が存在する場合のみ有効化。
"""
import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import shutil

from compressor_utils import (
    compress_folder,
    cleanup_folder,
    count_target_files,
    human_readable,
    get_ghostscript_path,
)
from sound_utils import init_mixer, play_sound
from configs import (
    PDF_COMPRESS_MODES,
    PDF_LOSSY_DPI_DEFAULT,
    PDF_LOSSY_DPI_RANGE,
    PDF_LOSSY_JPEG_QUALITY_DEFAULT,
    PDF_LOSSY_PNG_TO_JPEG_DEFAULT,
    PDF_LOSSLESS_OPTIONS_DEFAULT,
    GS_PRESETS,
    GS_DEFAULT_PRESET,
    APP_DEFAULT_INPUT_DIR,
    APP_DEFAULT_OUTPUT_DIR,
    APP_DEFAULT_WINDOW_SIZE,
    SOUNDS_DIR,
    LONG_EDGE_PRESETS,
    INPUT_DIR_CLEANUP_EXTENSIONS,
    OUTPUT_DIR_CLEANUP_EXTENSIONS,
)

# ------------- 高DPI対応（Windowsのみ） -------------
if os.name == 'nt':
    import ctypes
    ctypes.windll.shcore.SetProcessDpiAwareness(1)

# ------------- fitz / pikepdf の利用可能性検出 -------------
try:
    import fitz  # noqa: F401
    FITZ_AVAILABLE = True
except ImportError:
    FITZ_AVAILABLE = False

try:
    import pikepdf  # noqa: F401
    PIKEPDF_AVAILABLE = True
except ImportError:
    PIKEPDF_AVAILABLE = False

# ------------- ドラッグ＆ドロップ検出 -------------
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    DND_AVAILABLE = True
except Exception:
    DND_AVAILABLE = False

# ------------- pygame ミキサー初期化 -------------
init_mixer()

# ------------- デフォルトフォルダ作成 -------------
os.makedirs(APP_DEFAULT_INPUT_DIR, exist_ok=True)
os.makedirs(APP_DEFAULT_OUTPUT_DIR, exist_ok=True)


def get_default_output_dir():
    """デフォルト出力フォルダを返す。Windows ならデスクトップ配下に作成を試みる。"""
    if os.name == 'nt':
        desktop = os.path.join(os.environ['USERPROFILE'], 'Desktop')
        output_dir = os.path.join(desktop, '圧縮済みファイル')
        if not os.path.exists(output_dir):
            play_sound(os.path.join(SOUNDS_DIR, 'notice.wav'))
            if messagebox.askquestion(
                "「圧縮済みファイル」フォルダ作成",
                "デスクトップに「圧縮済みファイル」フォルダを作成してよいですか？"
            ) == 'yes':
                try:
                    os.makedirs(output_dir, exist_ok=True)
                except Exception:
                    output_dir = APP_DEFAULT_OUTPUT_DIR
            else:
                output_dir = APP_DEFAULT_OUTPUT_DIR
        return output_dir
    else:
        return APP_DEFAULT_OUTPUT_DIR


DEFAULT_INPUT_DIR = APP_DEFAULT_INPUT_DIR
DEFAULT_OUTPUT_DIR = get_default_output_dir()


# =============================================================================
#  App クラス定義
# =============================================================================
class App(tk.Tk if not DND_AVAILABLE else TkinterDnD.Tk):
    """フォルダ一括圧縮アプリケーションのメインウィンドウクラス (tkinter 版)。"""

    # ------------------------------------------------------------------
    #  コンストラクタ
    # ------------------------------------------------------------------
    def __init__(self):
        super().__init__()
        self.title("フォルダ一括圧縮アプリ v2")
        self.geometry(self._expanded_window_size(APP_DEFAULT_WINDOW_SIZE, 60, 60))

        self.threads: list[threading.Thread] = []

        # ── GUI 変数 ──
        self.input_dir = tk.StringVar(value=DEFAULT_INPUT_DIR)
        self.output_dir = tk.StringVar(value=DEFAULT_OUTPUT_DIR)

        # PDF エンジン選択
        self.pdf_engine = tk.StringVar(value='native')

        # ネイティブ PDF コントロール
        self.pdf_mode = tk.StringVar(value='both')
        self.pdf_dpi = tk.IntVar(value=PDF_LOSSY_DPI_DEFAULT)
        self.pdf_jpeg_quality = tk.IntVar(value=PDF_LOSSY_JPEG_QUALITY_DEFAULT)
        self.pdf_png_to_jpeg = tk.BooleanVar(value=PDF_LOSSY_PNG_TO_JPEG_DEFAULT)

        # 可逆オプション（ネイティブ & GS 共通変数）
        _defaults = PDF_LOSSLESS_OPTIONS_DEFAULT
        self.pdf_ll_linearize = tk.BooleanVar(value=_defaults['linearize'])
        self.pdf_ll_object_streams = tk.BooleanVar(value=_defaults['object_streams'])
        self.pdf_ll_clean_metadata = tk.BooleanVar(value=_defaults['clean_metadata'])
        self.pdf_ll_recompress_streams = tk.BooleanVar(value=_defaults['recompress_streams'])
        self.pdf_ll_remove_unreferenced = tk.BooleanVar(value=_defaults['remove_unreferenced'])

        # GS コントロール
        self.gs_preset = tk.StringVar(value=GS_DEFAULT_PRESET)
        self.gs_custom_dpi = tk.IntVar(value=PDF_LOSSY_DPI_DEFAULT)
        self.gs_use_lossless = tk.BooleanVar(value=True)

        # 画像圧縮
        self.jpg_quality = tk.IntVar(value=70)
        self.png_quality = tk.IntVar(value=70)
        self.use_pngquant = tk.BooleanVar(value=True)

        # リサイズ
        self.resize_enabled = tk.BooleanVar(value=False)
        self.resize_width = tk.StringVar(value="0")
        self.resize_height = tk.StringVar(value="0")
        self.resize_keep_aspect = tk.BooleanVar(value=True)
        self.resize_mode = tk.StringVar(value='manual')
        self.long_edge_value_str = tk.StringVar(value="1024")

        # 出力設定
        self.csv_enable = tk.BooleanVar(value=True)
        self.csv_path = tk.StringVar(value="")
        self.extract_zip = tk.BooleanVar(value=True)
        self.auto_switch_log_tab = tk.BooleanVar(value=True)

        # 進捗状態
        self.status_var = tk.StringVar(value="待機中")

        # ── レイアウト構築 ──
        self._build_folder_section()
        self._build_notebook()
        self._build_progress_section()
        self._build_action_buttons()

        # ── 初期状態更新 ──
        self._refresh_pdf_engine_status()
        self._update_pdf_controls()
        self._update_resize_controls()

        self.protocol("WM_DELETE_WINDOW", self.on_exit)

    # ==================================================================
    #  レイアウト構築
    # ==================================================================

    def _build_folder_section(self):
        """フォルダ選択行（入力・出力）を構築。"""
        folder_frame = ttk.Frame(self)
        folder_frame.pack(fill='x', padx=14, pady=(12, 8))

        # ── 入力行 ──
        row_in = ttk.Frame(folder_frame)
        row_in.pack(fill='x', pady=4)
        ttk.Label(row_in, text="入力フォルダ:").pack(side='left')
        self.input_entry = ttk.Entry(row_in, textvariable=self.input_dir, width=45)
        self.input_entry.pack(side='left', padx=8)
        ttk.Button(row_in, text="選択", command=self.choose_input).pack(side='left', padx=4)
        tk.Button(row_in, text="クリーンアップ", command=self.cleanup_input,
              bg='#d0f6ff').pack(side='left', padx=4)

        if DND_AVAILABLE:
            self.input_entry.drop_target_register(DND_FILES)
            self.input_entry.dnd_bind('<<Drop>>', self._on_drop_input)
            ttk.Label(row_in, text="（D&D可）", foreground="gray").pack(side='left', padx=6)
        else:
            ttk.Label(row_in, text="（D&D無効: tkinterdnd2 未インストール）",
                      foreground="gray").pack(side='left', padx=6)

        # ── 出力行 ──
        row_out = ttk.Frame(folder_frame)
        row_out.pack(fill='x', pady=4)
        ttk.Label(row_out, text="出力フォルダ:").pack(side='left')
        ttk.Entry(row_out, textvariable=self.output_dir, width=45).pack(side='left', padx=8)
        ttk.Button(row_out, text="選択", command=self.choose_output).pack(side='left', padx=4)
        tk.Button(row_out, text="クリーンアップ", command=self.cleanup_output,
              bg='#ffcaca').pack(side='left', padx=4)

    def _build_notebook(self):
        """タブウィジェット（圧縮設定 / ログ）を構築。"""
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill='both', expand=True, padx=14, pady=8)

        self.settings_tab = ttk.Frame(self.notebook)
        self.log_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.settings_tab, text=" 圧縮設定 ")
        self.notebook.add(self.log_tab, text=" ログ ")

        self._build_settings_tab()
        self._build_log_tab()

    # ------------------------------------------------------------------
    #  圧縮設定タブ
    # ------------------------------------------------------------------

    def _build_settings_tab(self):
        """圧縮設定タブを PDF 操作 / 画像操作の 2 ブロックで構築。"""
        pdf_outer = tk.LabelFrame(
            self.settings_tab,
            text=" PDF圧縮設定（Pythonライブラリ / GhostScript） ",
            bg="#fff1f1",
            fg="black",
            bd=1,
            relief='solid')
        pdf_outer.pack(fill='x', padx=8, pady=(8, 5))
        pdf_container = ttk.Frame(pdf_outer)
        pdf_container.pack(fill='x', padx=8, pady=(5, 8))
        self._build_pdf_section(pdf_container)

        image_outer = tk.LabelFrame(
            self.settings_tab,
            text=" 画像ファイル圧縮設定（JPEG/PNG 圧縮・リサイズ） ",
            bg="#f1f6ff",
            fg="black",
            bd=1,
            relief='solid')
        image_outer.pack(fill='x', padx=8, pady=5)
        image_container = ttk.Frame(image_outer)
        image_container.pack(fill='x', padx=8, pady=(5, 8))
        self._build_image_section(image_container)
        self._build_resize_section(image_container)
        self._build_output_section(image_container)

    def _build_pdf_section(self, parent):
        """PDF 圧縮セクション。"""
        # pdf_lf = ttk.LabelFrame(parent, text=" PDF 圧縮 ")
        # pdf_lf.pack(fill='x', padx=5, pady=(5, 3))

        # ── エンジン選択 ──
        engine_frame = ttk.Frame(parent)
        engine_frame.pack(fill='x', padx=8, pady=(6, 4))

        ttk.Label(engine_frame, text="エンジン:").pack(side='left')
        self.native_rb = ttk.Radiobutton(
            engine_frame, text="ネイティブ (PyMuPDF + pikepdf)",
            variable=self.pdf_engine, value='native',
            command=self._update_pdf_controls)
        self.native_rb.pack(side='left', padx=(10, 5))
        self.gs_rb = ttk.Radiobutton(
            engine_frame, text="GhostScript",
            variable=self.pdf_engine, value='gs',
            command=self._update_pdf_controls)
        self.gs_rb.pack(side='left', padx=5)

        # エンジン状態表示
        self.pdf_engine_status_var = tk.StringVar(value="判定中…")
        ttk.Label(engine_frame, textvariable=self.pdf_engine_status_var,
                  foreground='purple').pack(side='left', padx=(10, 0))

        # ── ネイティブエンジンフレーム ──
        self.native_frame = ttk.Frame(parent)
        self._build_native_controls(self.native_frame)

        # ── GS エンジンフレーム ──
        self.gs_frame = ttk.Frame(parent)
        self._build_gs_controls(self.gs_frame)

    def _build_native_controls(self, parent):
        """ネイティブ PDF エンジン用コントロールを構築。"""

        # ── モード選択 ──
        mode_frame = ttk.Frame(parent)
        mode_frame.pack(fill='x', padx=5, pady=2)
        ttk.Label(mode_frame, text="モード:").pack(side='left')
        for val, label in PDF_COMPRESS_MODES.items():
            ttk.Radiobutton(
                mode_frame, text=label, variable=self.pdf_mode, value=val,
                command=self._update_pdf_controls
            ).pack(side='left', padx=(10, 3))

        # ── 非可逆オプション ──
        self.lossy_lf = ttk.LabelFrame(parent, text="非可逆オプション")
        self.lossy_lf.pack(fill='x', padx=8, pady=4)
        self._native_lossy_widgets: list = []

        # DPI スライダー
        dpi_row = ttk.Frame(self.lossy_lf)
        dpi_row.pack(fill='x', padx=5, pady=2)
        w = ttk.Label(dpi_row, text="DPI:")
        w.pack(side='left')
        self._native_lossy_widgets.append(w)
        self.dpi_val_label = ttk.Label(dpi_row, text=str(self.pdf_dpi.get()), width=4)
        self.dpi_val_label.pack(side='left', padx=5)
        self._native_lossy_widgets.append(self.dpi_val_label)
        self.dpi_scale = tk.Scale(
            dpi_row, from_=PDF_LOSSY_DPI_RANGE[0], to=PDF_LOSSY_DPI_RANGE[1],
            orient='horizontal', variable=self.pdf_dpi,
            command=lambda v: self.dpi_val_label.config(text=str(int(float(v)))),
            length=300, showvalue=False, resolution=1)
        self.dpi_scale.pack(side='left', padx=5)
        self._native_lossy_widgets.append(self.dpi_scale)

        # JPEG 品質スライダー
        jpeg_row = ttk.Frame(self.lossy_lf)
        jpeg_row.pack(fill='x', padx=5, pady=2)
        w = ttk.Label(jpeg_row, text="JPEG品質:")
        w.pack(side='left')
        self._native_lossy_widgets.append(w)
        self.jpeg_q_val_label = ttk.Label(jpeg_row, text=str(self.pdf_jpeg_quality.get()), width=4)
        self.jpeg_q_val_label.pack(side='left', padx=5)
        self._native_lossy_widgets.append(self.jpeg_q_val_label)
        self.jpeg_q_scale = tk.Scale(
            jpeg_row, from_=1, to=100,
            orient='horizontal', variable=self.pdf_jpeg_quality,
            command=lambda v: self.jpeg_q_val_label.config(text=str(int(float(v)))),
            length=300, showvalue=False, resolution=1)
        self.jpeg_q_scale.pack(side='left', padx=5)
        self._native_lossy_widgets.append(self.jpeg_q_scale)

        # JPEG 注記ラベル（png_to_jpeg OFF 時のみ表示）
        self.jpeg_note_label = ttk.Label(jpeg_row, text="※JPEG元画像にのみ適用", foreground="gray")
        # 表示/非表示は _update_pdf_controls で管理

        # PNG→JPEG チェック
        png_jpeg_row = ttk.Frame(self.lossy_lf)
        png_jpeg_row.pack(fill='x', padx=5, pady=2)
        self.png_to_jpeg_cb = ttk.Checkbutton(
            png_jpeg_row, text="PNG → JPEG 変換",
            variable=self.pdf_png_to_jpeg,
            command=self._update_pdf_controls)
        self.png_to_jpeg_cb.pack(side='left')
        self._native_lossy_widgets.append(self.png_to_jpeg_cb)

        # ── 可逆オプション ──
        self.native_lossless_lf = ttk.LabelFrame(parent, text="可逆オプション")
        self.native_lossless_lf.pack(fill='x', padx=8, pady=4)
        self._native_ll_frame, self._native_lossless_widgets = \
            self._create_lossless_controls(self.native_lossless_lf)
        self._native_ll_frame.pack(fill='x')

    def _build_gs_controls(self, parent):
        """GhostScript エンジン用コントロールを構築。"""

        # ── プリセット選択 ──
        preset_lf = ttk.LabelFrame(parent, text="プリセット")
        preset_lf.pack(fill='x', padx=8, pady=4)
        self._gs_preset_widgets: list = []

        preset_grid = ttk.Frame(preset_lf)
        preset_grid.pack(fill='x', padx=5, pady=2)
        all_presets = list(GS_PRESETS.items()) + [('custom', 'カスタム')]
        for idx, (key, label) in enumerate(all_presets):
            display = f"{label}" if key == 'custom' else f"{key}: {label}"
            rb = ttk.Radiobutton(
                preset_grid, text=display,
                variable=self.gs_preset, value=key,
                command=self._update_pdf_controls)
            r, c = divmod(idx, 2)
            rb.grid(row=r, column=c, sticky='w', padx=(0, 20), pady=2)
            self._gs_preset_widgets.append(rb)

        # ── カスタム DPI ──
        custom_row = ttk.Frame(parent)
        custom_row.pack(fill='x', padx=12, pady=4)
        lbl = ttk.Label(custom_row, text="カスタム DPI:")
        lbl.pack(side='left')
        self.gs_dpi_val_label = ttk.Label(
            custom_row, text=str(self.gs_custom_dpi.get()), width=4)
        self.gs_dpi_val_label.pack(side='left', padx=5)
        self.gs_dpi_scale = tk.Scale(
            custom_row, from_=PDF_LOSSY_DPI_RANGE[0], to=PDF_LOSSY_DPI_RANGE[1],
            orient='horizontal', variable=self.gs_custom_dpi,
            command=lambda v: self.gs_dpi_val_label.config(text=str(int(float(v)))),
            length=300, showvalue=False, resolution=1)
        self.gs_dpi_scale.pack(side='left', padx=5)
        self._gs_custom_dpi_widgets = [lbl, self.gs_dpi_val_label, self.gs_dpi_scale]

        # ── pikepdf 構造最適化チェック ──
        ll_check_row = ttk.Frame(parent)
        ll_check_row.pack(fill='x', padx=12, pady=4)
        self.gs_use_lossless_cb = ttk.Checkbutton(
            ll_check_row, text="pikepdf 構造最適化も適用",
            variable=self.gs_use_lossless,
            command=self._update_pdf_controls)
        self.gs_use_lossless_cb.pack(side='left')

        # ── GS 用可逆オプション ──
        self.gs_lossless_lf = ttk.LabelFrame(parent, text="可逆オプション（pikepdf）")
        self.gs_lossless_lf.pack(fill='x', padx=8, pady=4)
        self._gs_ll_frame, self._gs_lossless_widgets = \
            self._create_lossless_controls(self.gs_lossless_lf)
        self._gs_ll_frame.pack(fill='x')

    def _build_image_section(self, parent):
        """画像圧縮セクション。"""
        img_lf = ttk.LabelFrame(parent, text=" 画像圧縮 ")
        img_lf.pack(fill='x', padx=8, pady=5)

        # JPG 品質
        jpg_row = ttk.Frame(img_lf)
        jpg_row.pack(fill='x', padx=5, pady=2)
        ttk.Label(jpg_row, text="JPG 品質 (0-100):").pack(side='left')
        self.jpg_quality_label = ttk.Label(
            jpg_row, text=str(self.jpg_quality.get()), width=4)
        self.jpg_quality_label.pack(side='left', padx=5)
        tk.Scale(
            jpg_row, from_=0, to=100, orient='horizontal',
            variable=self.jpg_quality,
            command=lambda v: self.jpg_quality_label.config(text=str(int(float(v)))),
            length=300, showvalue=False
        ).pack(side='left')

        # PNG 品質
        png_row = ttk.Frame(img_lf)
        png_row.pack(fill='x', padx=5, pady=2)
        ttk.Label(png_row, text="PNG 品質 (0-100):").pack(side='left')
        self.png_quality_label = ttk.Label(
            png_row, text=str(self.png_quality.get()), width=4)
        self.png_quality_label.pack(side='left', padx=5)
        tk.Scale(
            png_row, from_=0, to=100, orient='horizontal',
            variable=self.png_quality,
            command=lambda v: self.png_quality_label.config(text=str(int(float(v)))),
            length=300, showvalue=False
        ).pack(side='left')

        # pngquant
        pq_row = ttk.Frame(img_lf)
        pq_row.pack(fill='x', padx=5, pady=2)
        self.pngquant_check = ttk.Checkbutton(
            pq_row, text="pngquant 使用（パレット量子化・不可逆）",
            variable=self.use_pngquant)
        self.pngquant_check.pack(side='left')
        if not shutil.which("pngquant"):
            self.pngquant_check.config(state='disabled')
            ttk.Label(pq_row, text="（pngquant 未検出のため無効）",
                      foreground='gray').pack(side='left', padx=10)

    def _build_resize_section(self, parent):
        """リサイズセクション。"""
        resize_lf = ttk.LabelFrame(parent, text=" リサイズ ")
        resize_lf.pack(fill='x', padx=8, pady=5)

        # 有効化チェック
        enable_row = ttk.Frame(resize_lf)
        enable_row.pack(fill='x', padx=5, pady=2)
        ttk.Checkbutton(
            enable_row, text="画像を一括リサイズする",
            variable=self.resize_enabled,
            command=self._update_resize_controls
        ).pack(side='left')

        # 手動リサイズ
        ctrl_row = ttk.Frame(resize_lf)
        ctrl_row.pack(fill='x', padx=5, pady=2)
        self.resize_mode_manual_rb = ttk.Radiobutton(
            ctrl_row, text="手動", variable=self.resize_mode, value='manual',
            command=self._update_resize_controls)
        self.resize_mode_manual_rb.pack(side='left')
        ttk.Label(ctrl_row, text="幅:").pack(side='left', padx=(10, 2))
        self.resize_width_entry = ttk.Entry(
            ctrl_row, textvariable=self.resize_width, width=6)
        self.resize_width_entry.pack(side='left')
        ttk.Label(ctrl_row, text="高さ:").pack(side='left', padx=(10, 2))
        self.resize_height_entry = ttk.Entry(
            ctrl_row, textvariable=self.resize_height, width=6)
        self.resize_height_entry.pack(side='left')
        self.resize_keep_aspect_chk = ttk.Checkbutton(
            ctrl_row, text="アスペクト比保持", variable=self.resize_keep_aspect)
        self.resize_keep_aspect_chk.pack(side='left', padx=(12, 0))

        # 長辺指定
        long_row = ttk.Frame(resize_lf)
        long_row.pack(fill='x', padx=5, pady=2)
        self.resize_mode_long_rb = ttk.Radiobutton(
            long_row, text="長辺指定", variable=self.resize_mode, value='long_edge',
            command=self._update_resize_controls)
        self.resize_mode_long_rb.pack(side='left')
        ttk.Label(long_row, text="長辺(px):").pack(side='left', padx=(10, 2))
        self.long_edge_combo = ttk.Combobox(
            long_row, textvariable=self.long_edge_value_str,
            values=LONG_EDGE_PRESETS, width=8)
        self.long_edge_combo.pack(side='left')

    def _build_output_section(self, parent):
        """出力設定セクション。"""
        out_lf = ttk.LabelFrame(parent, text=" 出力設定 ")
        out_lf.pack(fill='x', padx=8, pady=5)

        # CSV
        csv_row = ttk.Frame(out_lf)
        csv_row.pack(fill='x', padx=5, pady=2)
        ttk.Checkbutton(csv_row, text="CSV ログを出力する",
                        variable=self.csv_enable).pack(side='left')
        ttk.Label(csv_row, text="保存先(任意):").pack(side='left', padx=(10, 2))
        ttk.Entry(csv_row, textvariable=self.csv_path, width=35).pack(side='left', padx=5)
        ttk.Button(csv_row, text="参照",
                   command=self._choose_csv_path).pack(side='left', padx=2)

        # ZIP 展開
        zip_row = ttk.Frame(out_lf)
        zip_row.pack(fill='x', padx=5, pady=2)
        ttk.Checkbutton(zip_row, text="ZIP 展開してから圧縮",
                        variable=self.extract_zip).pack(side='left')

        # ログタブ自動切替
        log_row = ttk.Frame(out_lf)
        log_row.pack(fill='x', padx=5, pady=2)
        ttk.Checkbutton(
            log_row,
            text="圧縮開始時にログタブへ自動切替",
            variable=self.auto_switch_log_tab).pack(side='left')

    def _build_progress_section(self):
        """進捗表示（常時表示）を構築。"""
        progress_lf = ttk.LabelFrame(self, text=" 進捗 ")
        progress_lf.pack(fill='x', padx=14, pady=(0, 8))

        status_row = ttk.Frame(progress_lf)
        status_row.pack(fill='x', padx=10, pady=(8, 4))
        ttk.Label(status_row, text="状態:").pack(side='left')
        ttk.Label(status_row, textvariable=self.status_var,
                  foreground='purple').pack(side='left', padx=(8, 0))

        self.progress = ttk.Progressbar(
            progress_lf, maximum=100, mode='determinate')
        self.progress.pack(fill='x', padx=10, pady=(0, 10))

    # ------------------------------------------------------------------
    #  ログ・進捗タブ
    # ------------------------------------------------------------------

    def _build_log_tab(self):
        """ログタブを構築。"""

        # 統計
        stats_frame = ttk.Frame(self.log_tab)
        stats_frame.pack(fill='x', padx=14, pady=(12, 8))
        self.stats_var = tk.StringVar(value="統計: 処理前")
        ttk.Label(stats_frame, textvariable=self.stats_var,
                  foreground="blue",
                  font=("Arial", 10, "bold")).pack(side='left')

        # ログテキスト
        log_frame = ttk.Frame(self.log_tab)
        log_frame.pack(fill='both', expand=True, padx=14, pady=(0, 12))
        scrollbar = ttk.Scrollbar(log_frame)
        scrollbar.pack(side='right', fill='y')
        self.log_text = tk.Text(
            log_frame, height=15, width=85, yscrollcommand=scrollbar.set)
        self.log_text.pack(side='left', fill='both', expand=True)
        scrollbar.config(command=self.log_text.yview)

    # ------------------------------------------------------------------
    #  アクションボタン
    # ------------------------------------------------------------------

    def _build_action_buttons(self):
        """アクションボタン行を構築。"""
        frame = ttk.Frame(self)
        frame.pack(fill='x', padx=14, pady=(6, 12))
        # 中央寄せのために内部フレーム
        inner = ttk.Frame(frame)
        inner.pack(anchor='center')
        tk.Button(inner, text="圧縮開始", command=self.start_compress,
                  width=16, bg='#ccffcc').pack(side='left', padx=14)
        tk.Button(inner, text="終了", command=self.on_exit,
                  width=12, bg='#e6e6e6').pack(side='left', padx=14)

    # ==================================================================
    #  ヘルパー: 可逆チェックボックス生成
    # ==================================================================

    def _create_lossless_controls(self, parent):
        """可逆オプションのチェックボックス群を生成。

        Returns:
            (frame, list[widget]) — 外側フレームとウィジェットリスト
        """
        frame = ttk.Frame(parent)
        widgets: list = []

        row1 = ttk.Frame(frame)
        row1.pack(fill='x', padx=5, pady=2)
        for text, var in [
            ("Linearize", self.pdf_ll_linearize),
            ("ObjStream圧縮", self.pdf_ll_object_streams),
            ("メタデータ除去", self.pdf_ll_clean_metadata),
        ]:
            cb = ttk.Checkbutton(row1, text=text, variable=var)
            cb.pack(side='left', padx=(0, 12))
            widgets.append(cb)

        row2 = ttk.Frame(frame)
        row2.pack(fill='x', padx=5, pady=2)
        for text, var in [
            ("Flate再圧縮", self.pdf_ll_recompress_streams),
            ("孤立リソース削除", self.pdf_ll_remove_unreferenced),
        ]:
            cb = ttk.Checkbutton(row2, text=text, variable=var)
            cb.pack(side='left', padx=(0, 12))
            widgets.append(cb)

        return frame, widgets

    # ==================================================================
    #  コントロール状態更新
    # ==================================================================

    def _update_pdf_controls(self):
        """エンジン・モード選択に連動して PDF コントロールの表示/状態を更新する。"""
        engine = self.pdf_engine.get()

        if engine == 'native':
            # --- ネイティブ表示 ---
            self.gs_frame.pack_forget()
            self.native_frame.pack(fill='x', padx=5, pady=(2, 5))

            mode = self.pdf_mode.get()
            lossy_active = mode in ('lossy', 'both')
            lossless_active = mode in ('lossless', 'both')

            # 非可逆コントロール
            lossy_st = 'normal' if lossy_active else 'disabled'
            for w in self._native_lossy_widgets:
                try:
                    w.config(state=lossy_st)
                except Exception:
                    pass
            try:
                self.dpi_scale.config(state=lossy_st)
                self.jpeg_q_scale.config(state=lossy_st)
            except Exception:
                pass

            # JPEG 注記ラベル表示切替
            if lossy_active and not self.pdf_png_to_jpeg.get():
                self.jpeg_note_label.pack(side='left', padx=(5, 0))
            else:
                self.jpeg_note_label.pack_forget()

            # 可逆コントロール
            ll_st = 'normal' if lossless_active else 'disabled'
            for w in self._native_lossless_widgets:
                try:
                    w.config(state=ll_st)
                except Exception:
                    pass
        else:
            # --- GS 表示 ---
            self.native_frame.pack_forget()
            self.gs_frame.pack(fill='x', padx=5, pady=(2, 5))

            # カスタム DPI 有効/無効
            custom = self.gs_preset.get() == 'custom'
            for w in self._gs_custom_dpi_widgets:
                try:
                    w.config(state='normal' if custom else 'disabled')
                except Exception:
                    pass

            # 可逆オプション有効/無効
            gs_ll = self.gs_use_lossless.get()
            for w in self._gs_lossless_widgets:
                try:
                    w.config(state='normal' if gs_ll else 'disabled')
                except Exception:
                    pass

    def _refresh_pdf_engine_status(self):
        """PDF エンジンの利用可能性を確認し、UI に反映する。"""
        gs_path = get_ghostscript_path()
        parts = []

        if FITZ_AVAILABLE:
            parts.append("PyMuPDF:OK")
        else:
            parts.append("PyMuPDF:なし")

        if PIKEPDF_AVAILABLE:
            parts.append("pikepdf:OK")
        else:
            parts.append("pikepdf:なし")

        if gs_path:
            parts.append("GS:OK")
        else:
            parts.append("GS:未検出")
            # GS ラジオを無効化
            try:
                self.gs_rb.config(state='disabled')
            except Exception:
                pass
            # GS が選択されていた場合はネイティブに切り替え
            if self.pdf_engine.get() == 'gs':
                self.pdf_engine.set('native')

        # ネイティブエンジンも使えない場合
        if not FITZ_AVAILABLE and not PIKEPDF_AVAILABLE:
            try:
                self.native_rb.config(state='disabled')
            except Exception:
                pass

        self.pdf_engine_status_var.set(f"（{', '.join(parts)}）")

    def _update_resize_controls(self):
        """リサイズ関連コントロールの有効/無効を更新する。"""
        try:
            enabled = self.resize_enabled.get()
            mode = self.resize_mode.get()
            is_manual = enabled and mode == 'manual'
            is_long = enabled and mode == 'long_edge'

            for w in (self.resize_width_entry, self.resize_height_entry):
                w.config(state='normal' if is_manual else 'disabled')
            self.resize_keep_aspect_chk.config(state='normal' if is_manual else 'disabled')
            self.resize_mode_manual_rb.config(state='normal' if enabled else 'disabled')
            self.resize_mode_long_rb.config(state='normal' if enabled else 'disabled')
            self.long_edge_combo.config(state='normal' if is_long else 'disabled')
        except Exception:
            pass

    # ==================================================================
    #  フォルダ操作
    # ==================================================================

    def choose_input(self):
        folder = filedialog.askdirectory(initialdir=self.input_dir.get() or None)
        if folder:
            self.input_dir.set(folder)
            self._validate_and_fix_dirs()

    def choose_output(self):
        folder = filedialog.askdirectory(initialdir=self.output_dir.get() or None)
        if folder:
            self.output_dir.set(folder)
            self._validate_and_fix_dirs()

    def _on_drop_input(self, event):
        """D&D で入力フォルダを設定する。"""
        try:
            paths = self.tk.splitlist(event.data)
        except Exception:
            paths = [event.data]
        for p in paths:
            p = p.strip('{}')
            if os.path.isdir(p):
                self.input_dir.set(p)
                self.log(f"D&D で入力フォルダ設定: {p}")
                break
            elif os.path.isfile(p):
                d = os.path.dirname(p)
                self.input_dir.set(d)
                self.log(f"D&D で入力フォルダ設定: {d}")
                break

    def _validate_and_fix_dirs(self):
        new_in, new_out, conflict = self._check_overlap_and_fix(
            self.input_dir.get(), self.output_dir.get())
        if conflict:
            self.input_dir.set(new_in)
            self.output_dir.set(new_out)
            self.log(f"入出力フォルダ重なり → リセット 入力:{new_in} 出力:{new_out}")
            messagebox.showwarning(
                "入出力フォルダの重なり",
                "入力/出力フォルダが同一または内包関係にあるためデフォルトに戻しました。")

    def _paths_overlap(self, a, b):
        try:
            ra, rb = os.path.abspath(a), os.path.abspath(b)
            if ra == rb:
                return True
            common = os.path.commonpath([ra, rb])
            return common == ra or common == rb
        except Exception:
            return False

    def _check_overlap_and_fix(self, input_dir, output_dir):
        if input_dir and output_dir and self._paths_overlap(input_dir, output_dir):
            return DEFAULT_INPUT_DIR, DEFAULT_OUTPUT_DIR, True
        return input_dir, output_dir, False

    # ==================================================================
    #  CSV パス選択
    # ==================================================================

    def _choose_csv_path(self):
        path = filedialog.asksaveasfilename(
            initialdir=self.output_dir.get() or os.getcwd(),
            defaultextension='.csv',
            filetypes=[('CSV files', '*.csv'), ('All files', '*.*')])
        if path:
            self.csv_path.set(path)

    # ==================================================================
    #  ログ・進捗・統計
    # ==================================================================

    def _set_status(self, text):
        if threading.current_thread() is threading.main_thread():
            self.status_var.set(text)
            return
        self.after(0, lambda: self.status_var.set(text))

    def _append_log(self, msg):
        self.log_text.insert("end", msg + "\n")
        self.log_text.see("end")

        if "完了！" in msg:
            current = self.progress["value"]
            self.status_var.set(f"完了（進捗 {int(current)}%）")
        elif "処理中にエラー発生" in msg:
            self.status_var.set("失敗（詳細はログ）")

    def log(self, msg):
        if threading.current_thread() is threading.main_thread():
            self._append_log(msg)
            return
        self.after(0, lambda: self._append_log(msg))

    def _update_progress_ui(self, current, total):
        if total <= 0:
            pct = 100
        else:
            pct = int(current / total * 100)
        self.progress["value"] = pct
        self.status_var.set(f"処理中 {pct}% ({current}/{total})")
        self.update_idletasks()

    def update_progress(self, current, total):
        if threading.current_thread() is threading.main_thread():
            self._update_progress_ui(current, total)
            return
        self.after(0, lambda: self._update_progress_ui(current, total))

    def _update_stats_ui(self, orig_total, out_total, saved, saved_pct):
        self.stats_var.set(
            f"統計: 元合計={human_readable(orig_total)}, "
            f"出力合計={human_readable(out_total)}, "
            f"削減={human_readable(saved)} ({saved_pct:.1f}%)")
        self.status_var.set(f"完了（削減率 {saved_pct:.1f}%）")

    def update_stats(self, orig_total, out_total, saved, saved_pct):
        if threading.current_thread() is threading.main_thread():
            self._update_stats_ui(orig_total, out_total, saved, saved_pct)
            return
        self.after(
            0,
            lambda: self._update_stats_ui(orig_total, out_total, saved, saved_pct),
        )

    # ==================================================================
    #  圧縮開始
    # ==================================================================

    def start_compress(self):
        input_ = self.input_dir.get()
        output_ = self.output_dir.get()

        # 入出力フォルダ重なりチェック
        fixed_in, fixed_out, conflict = self._check_overlap_and_fix(input_, output_)
        if conflict:
            self.input_dir.set(fixed_in)
            self.output_dir.set(fixed_out)
            input_, output_ = fixed_in, fixed_out
            self.log(f"入出力フォルダ重なり → リセット 入力:{fixed_in} 出力:{fixed_out}")
            messagebox.showwarning(
                "入出力フォルダの重なり",
                f"デフォルトに戻しました。\n"
                f"入力: {DEFAULT_INPUT_DIR}\n出力: {DEFAULT_OUTPUT_DIR}")

        if not input_ or not output_:
            self._set_status("失敗（入力/出力フォルダ未指定）")
            messagebox.showerror("エラー", "両方のフォルダを選択してください")
            return
        if not os.path.isdir(input_):
            self._set_status("失敗（入力フォルダを確認）")
            messagebox.showerror("エラー", "入力フォルダが存在しません")
            return
        os.makedirs(output_, exist_ok=True)

        # ── リサイズ設定構築 ──
        r_mode = self.resize_mode.get()
        r_w = self._to_non_negative_int(self.resize_width.get())
        r_h = self._to_non_negative_int(self.resize_height.get())
        try:
            r_le = max(0, int(self.long_edge_value_str.get().strip()))
        except Exception:
            r_le = 0

        resize_config = False
        if self.resize_enabled.get():
            if r_mode == 'long_edge' and r_le > 0:
                resize_config = {
                    'enabled': True, 'mode': 'long_edge',
                    'long_edge': r_le, 'keep_aspect': True}
            elif r_mode == 'manual' and (r_w > 0 or r_h > 0):
                resize_config = {
                    'enabled': True, 'mode': 'manual',
                    'width': r_w, 'height': r_h,
                    'keep_aspect': self.resize_keep_aspect.get()}

        # ── 可逆オプション構築 ──
        lossless_opts = {
            'linearize': self.pdf_ll_linearize.get(),
            'object_streams': self.pdf_ll_object_streams.get(),
            'clean_metadata': self.pdf_ll_clean_metadata.get(),
            'recompress_streams': self.pdf_ll_recompress_streams.get(),
            'remove_unreferenced': self.pdf_ll_remove_unreferenced.get(),
        }

        engine = self.pdf_engine.get()
        if engine == 'gs':
            pdf_lossless_options = lossless_opts if self.gs_use_lossless.get() else None
        else:
            mode = self.pdf_mode.get()
            pdf_lossless_options = lossless_opts if mode in ('lossless', 'both') else None

        # ── ログタブに切り替え（設定ON時） ──
        if self.auto_switch_log_tab.get():
            self.notebook.select(self.log_tab)

        # UI リセット
        self.log_text.delete(1.0, "end")
        self.progress["value"] = 0
        self.stats_var.set("統計: 処理中...")
        self.status_var.set("圧縮開始準備中…")

        # ── ログ出力 ──
        self.log(f"圧縮開始: 入力={input_}")
        self.log(f"出力先: {output_}")
        if engine == 'native':
            self.log(
                f"PDF: ネイティブ モード={self.pdf_mode.get()}, DPI={self.pdf_dpi.get()}, "
                f"JPEG品質={self.pdf_jpeg_quality.get()}, PNG→JPEG={self.pdf_png_to_jpeg.get()}")
        else:
            preset = self.gs_preset.get()
            if preset == 'custom':
                self.log(
                    f"PDF: GhostScript カスタムDPI={self.gs_custom_dpi.get()}, "
                    f"pikepdf併用={self.gs_use_lossless.get()}")
            else:
                self.log(
                    f"PDF: GhostScript プリセット={preset}, "
                    f"pikepdf併用={self.gs_use_lossless.get()}")
        self.log(
            f"画像: JPG={self.jpg_quality.get()}, PNG={self.png_quality.get()}, "
            f"pngquant={self.use_pngquant.get()}")
        if self.resize_enabled.get():
            self.log(f"リサイズ: {resize_config}")
        self._set_status("処理中 0% (0/0)")

        # ── スレッド開始 ──
        thread = threading.Thread(
            target=compress_folder,
            kwargs={
                'input_dir': input_,
                'output_dir': output_,
                'jpg_quality': self.jpg_quality.get(),
                'png_quality': self.png_quality.get(),
                'use_pngquant': self.use_pngquant.get(),
                'log_func': self.log,
                'progress_func': self.update_progress,
                'stats_func': self.update_stats,
                'pdf_engine': engine,
                'pdf_mode': self.pdf_mode.get(),
                'pdf_dpi': self.pdf_dpi.get(),
                'pdf_jpeg_quality': self.pdf_jpeg_quality.get(),
                'pdf_png_to_jpeg': self.pdf_png_to_jpeg.get(),
                'pdf_lossless_options': pdf_lossless_options,
                'gs_preset': self.gs_preset.get(),
                'gs_custom_dpi': (self.gs_custom_dpi.get()
                                  if self.gs_preset.get() == 'custom' else None),
                'resize_enabled': resize_config,
                'resize_width': r_w,
                'resize_height': r_h,
                'csv_enable': self.csv_enable.get(),
                'csv_path': self.csv_path.get().strip() or None,
                'extract_zip': self.extract_zip.get(),
            },
            daemon=True,
        )
        self.threads.append(thread)
        thread.start()

    # ==================================================================
    #  クリーンアップ
    # ==================================================================

    def cleanup_input(self):
        input_ = self.input_dir.get()
        if not input_ or not os.path.exists(input_):
            messagebox.showerror("エラー", "入力フォルダが未指定、または存在しません")
            return
        count = count_target_files(input_, INPUT_DIR_CLEANUP_EXTENSIONS)
        exts = ', '.join(sorted(INPUT_DIR_CLEANUP_EXTENSIONS))
        play_sound(os.path.join(SOUNDS_DIR, 'warning.wav'))
        if messagebox.askyesno(
            "クリーンアップ確認",
            f"入力フォルダ内の対象ファイルを削除しますか？\n\n"
            f"【対象拡張子】\n{exts}\n\n"
            f"【削除対象ファイル数】\n約 {count} ファイル\n\n"
            f"サブフォルダ含め削除されます。取り消し不可。"
        ):
            self.log(f"入力フォルダクリーンアップ開始（{exts}）…")
            t = threading.Thread(
                target=cleanup_folder,
                args=(input_, self.log, "入力フォルダ", INPUT_DIR_CLEANUP_EXTENSIONS),
                daemon=True)
            self.threads.append(t)
            t.start()

    def cleanup_output(self):
        output_ = self.output_dir.get()
        if not output_ or not os.path.exists(output_):
            messagebox.showerror("エラー", "出力フォルダが未指定、または存在しません")
            return
        count = count_target_files(output_, OUTPUT_DIR_CLEANUP_EXTENSIONS)
        exts = ', '.join(sorted(OUTPUT_DIR_CLEANUP_EXTENSIONS))
        play_sound(os.path.join(SOUNDS_DIR, 'warning.wav'))
        if messagebox.askyesno(
            "クリーンアップ確認",
            f"出力フォルダ内の対象ファイルを削除しますか？\n\n"
            f"【対象拡張子】\n{exts}\n\n"
            f"【削除対象ファイル数】\n約 {count} ファイル\n\n"
            f"サブフォルダ含め削除されます。取り消し不可。"
        ):
            self.log(f"出力フォルダクリーンアップ開始（{exts}）…")
            t = threading.Thread(
                target=cleanup_folder,
                args=(output_, self.log, "出力フォルダ", OUTPUT_DIR_CLEANUP_EXTENSIONS),
                daemon=True)
            self.threads.append(t)
            t.start()

    # ==================================================================
    #  終了
    # ==================================================================

    def on_exit(self):
        if any(t.is_alive() for t in self.threads):
            if not messagebox.askyesno(
                "終了確認", "処理中のスレッドがあります。終了しますか？"):
                return
        self.destroy()

    # ==================================================================
    #  ヘルパー
    # ==================================================================

    @staticmethod
    def _expanded_window_size(base_size: str, add_width: int, add_height: int) -> str:
        """既定ウィンドウサイズ文字列を少し拡張した geometry 文字列へ変換する。"""
        try:
            size_part = base_size.split('+', 1)[0]
            w_str, h_str = size_part.lower().split('x', 1)
            width = max(640, int(w_str) + int(add_width))
            height = max(520, int(h_str) + int(add_height))
            return f"{width}x{height}"
        except Exception:
            return "1200x980"

    @staticmethod
    def _to_non_negative_int(s: str) -> int:
        """文字列を非負整数へ変換。空欄や非数値は 0 を返す。"""
        try:
            val = int(float(s.strip()))
            return val if val >= 0 else 0
        except Exception:
            return 0
