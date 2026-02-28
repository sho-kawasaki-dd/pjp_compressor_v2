#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ui_app.py

Tkinter ベースの GUI を提供するモジュール。圧縮ロジックは `compressor_utils`
に委譲し、ユーザー操作（フォルダ選択、品質設定、プリセット、進捗表示、
CSV ログの有効化など）を受け付ける。

設計ポイント:
- 処理はスレッドで非同期化し、UI の応答性を保持。
- 入出力フォルダの重なり（同一・内包関係）を検出し、安全な既定値へ自動リセット。
- Ghostscript と pypdf の利用可能性を UI から確認できるヘルパー付き。
- ドラッグ＆ドロップは `tkinterdnd2` が存在する場合のみ有効化。
"""
import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import shutil

# 圧縮機能は compressor モジュールへ委譲
from compressor_utils import (
    compress_folder,
    cleanup_folder,
    count_target_files,
    human_readable,
    PYPDF_AVAILABLE
)
from sound_utils import init_mixer, play_sound
from configs import (
    GS_OPTIONS,
    GS_COMMAND,
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

# ------------- オプション・環境検出（ドラッグ＆ドロップ） -------------
try:
    # tkinterdnd2 があれば D&D を有効化
    from tkinterdnd2 import DND_FILES, TkinterDnD
    DND_AVAILABLE = True
except Exception:
    # 無ければ D&D を無効化して通常の Tk を使う
    DND_AVAILABLE = False

# ------------- pygame ミキサー初期化（アプリ起動前） -------------
init_mixer()

# ------------- アプリケーションデフォルト入出力フォルダが無ければ作成-------------
os.makedirs(APP_DEFAULT_INPUT_DIR, exist_ok=True)
os.makedirs(APP_DEFAULT_OUTPUT_DIR, exist_ok=True)

# ------------- デフォルト入出力フォルダの決定 -------------
def get_default_output_dir():
    """
    デフォルトの出力フォルダを返す。
    Windows の場合はデスクトップ配下に「圧縮済みファイル」フォルダを作成（ユーザー確認のうえ）。
    それ以外はローカル「./compressed_files」を使用。
    """
    if os.name == 'nt':  # Windows
        desktop = os.path.join(os.path.join(os.environ['USERPROFILE']), 'Desktop')
        output_dir = os.path.join(desktop, '圧縮済みファイル')
        # フォルダが存在しなければ作成（確認ダイアログ）
        if not os.path.exists(output_dir):
            play_sound(os.path.join(SOUNDS_DIR, 'notice.wav'))
            if messagebox.askquestion(
                "「圧縮済みファイル」フォルダ作成",
                "デスクトップに「圧縮済みファイル」フォルダを作成してよいですか？"
            ) == 'yes':
                try:
                    os.makedirs(output_dir, exist_ok=True)
                except Exception as e:
                    print(f"デフォルト出力フォルダの作成に失敗: {e}")
                    output_dir = APP_DEFAULT_OUTPUT_DIR
            else:
                output_dir = APP_DEFAULT_OUTPUT_DIR
        return output_dir
    else:
        return APP_DEFAULT_OUTPUT_DIR

DEFAULT_INPUT_DIR = APP_DEFAULT_INPUT_DIR
DEFAULT_OUTPUT_DIR = get_default_output_dir()

# ------------- App クラス定義 -------------
class App(tk.Tk if not DND_AVAILABLE else TkinterDnD.Tk):
    """
    フォルダ一括圧縮アプリケーションのメインウィンドウクラス。
    """

    # ------------- コンストラクタ -------------
    def __init__(self):
        super().__init__()
        self.title("フォルダ一括圧縮アプリ（PDF・JPG・PNG圧縮 / 並列処理 / 統計表示対応）")
        self.geometry(APP_DEFAULT_WINDOW_SIZE)

        # バックグラウンドスレッドの追跡用
        self.threads = []

        # GUI 変数（バインド用）
        self.input_dir = tk.StringVar(value=DEFAULT_INPUT_DIR)
        self.output_dir = tk.StringVar(value=DEFAULT_OUTPUT_DIR)
        self.gs_quality = tk.StringVar(value='/ebook')
        self.pdf_quality_enabled = tk.BooleanVar(value=False)
        self.pdf_quality = tk.IntVar(value=70)
        self.jpg_quality = tk.IntVar(value=70)
        self.png_quality = tk.IntVar(value=70)
        self.use_pngquant = tk.BooleanVar(value=True)
        self.resize_enabled = tk.BooleanVar(value=False)
        self.resize_width = tk.StringVar(value="0")
        self.resize_height = tk.StringVar(value="0")
        self.resize_keep_aspect = tk.BooleanVar(value=True)
        self.resize_mode = tk.StringVar(value='manual')
        self.long_edge_value_str = tk.StringVar(value="1024")

        # 入力欄（D&D 対応）
        # D&D が有効な場合、テキストボックスへフォルダ／ファイルを落とすと
        # 入力フォルダとして自動設定される。ファイルの場合は親フォルダを使用。
        row_input = tk.Frame(self)
        row_input.pack(anchor='w', padx=10, pady=(10, 0))
        tk.Label(row_input, text="入力フォルダ:").pack(side='left')
        self.input_entry = tk.Entry(row_input, textvariable=self.input_dir, width=40)
        self.input_entry.pack(side='left', padx=5)
        tk.Button(row_input, text="選択", command=self.choose_input).pack(side='left', padx=3)
        tk.Button(row_input, text="クリーンアップ", command=self.cleanup_input, bg='#d0f6ff').pack(side='left', padx=3)

        if DND_AVAILABLE:
            self.input_entry.drop_target_register(DND_FILES)
            self.input_entry.dnd_bind('<<Drop>>', self._on_drop_input)
            tk.Label(row_input, text="（D&D可）", foreground="gray").pack(side='left')
        else:
            tk.Label(row_input, text="（D&D無効: tkinterdnd2未インストール）", foreground="gray").pack(side='left')

        # 出力欄
        row_output = tk.Frame(self)
        row_output.pack(anchor='w', padx=10, pady=(10, 0))
        tk.Label(row_output, text="出力フォルダ:").pack(side='left')
        tk.Entry(row_output, textvariable=self.output_dir, width=40).pack(side='left', padx=5)
        tk.Button(row_output, text="選択", command=self.choose_output).pack(side='left', padx=3)
        tk.Button(row_output, text="クリーンアップ", command=self.cleanup_output, bg='#ffcaca').pack(side='left', padx=3)

        # PDF 圧縮エンジン表示（固定方針: Ghostscript優先、無ければpypdf、両方無ければ不可）
        status_frame = tk.Frame(self)
        status_frame.pack(anchor='w', padx=10, pady=(15, 0))
        tk.Label(status_frame, text="PDF圧縮エンジン:").pack(side='left')
        self.pdf_engine_status_var = tk.StringVar(value="判定中…")
        self.pdf_engine_status_label = tk.Label(status_frame, textvariable=self.pdf_engine_status_var, foreground="purple")
        self.pdf_engine_status_label.pack(side='left', padx=(8,0))
        # 再判定ボタンは不要（Ghostscript検出は再起動が確実）

        # PDF圧縮ツール確認ボタンは不要のため削除（ステータス表示と再判定で代替）

        tk.Label(self, text="PDF圧縮プリセット (Ghostscript):").pack(anchor='w', padx=10, pady=(10, 0))
        preset_frame_pdf = tk.Frame(self)
        preset_frame_pdf.pack(anchor='w', padx=25)
        self.gs_preset_radiobuttons = []
        for idx, (mode, desc) in enumerate(GS_OPTIONS.items()):
            rb = tk.Radiobutton(preset_frame_pdf, text=f"{mode}：{desc}", variable=self.gs_quality, value=mode)
            r = idx // 2
            c = idx % 2
            rb.grid(row=r, column=c, sticky='w', padx=(0,20), pady=2)
            self.gs_preset_radiobuttons.append(rb)

        # PDF 品質スライダー
        pdf_frame = tk.Frame(self)
        pdf_frame.pack(anchor='w', padx=10, pady=(10, 0))
        self.pdf_quality_check = tk.Checkbutton(pdf_frame, text="PDF 品質スライダーを有効にする", variable=self.pdf_quality_enabled,
                command=self._toggle_pdf_slider)
        self.pdf_quality_check.pack(side='left')
        self.pdf_quality_label = tk.Label(pdf_frame, text=str(self.pdf_quality.get()), width=4, anchor='e')
        self.pdf_quality_label.pack(side='left', padx=5)
        self.pdf_scale = tk.Scale(pdf_frame, from_=0, to=100, orient='horizontal', variable=self.pdf_quality,
                            command=self._update_pdf_label, length=300, showvalue=False, state='disabled')
        self.pdf_scale.pack(side='left')

        # JPG/PNG スライダーと pngquant フラグ
        # PNG は pngquant が導入されていれば量子化で高圧縮、未導入なら Pillow。
        jpg_frame = tk.Frame(self)
        jpg_frame.pack(anchor='w', padx=10, pady=(10, 0))
        tk.Label(jpg_frame, text="JPG 品質 (0-100):").pack(side='left')
        self.jpg_quality_label = tk.Label(jpg_frame, text=str(self.jpg_quality.get()), width=4, anchor='e')
        self.jpg_quality_label.pack(side='left', padx=5)
        jpg_scale = tk.Scale(jpg_frame, from_=0, to=100, orient='horizontal', variable=self.jpg_quality,
                            command=self._update_jpg_label, length=300, showvalue=False)
        jpg_scale.pack(side='left')

        png_frame = tk.Frame(self)
        png_frame.pack(anchor='w', padx=10, pady=(5, 0))
        tk.Label(png_frame, text="PNG 品質 (0-100):").pack(side='left')
        self.png_quality_label = tk.Label(png_frame, text=str(self.png_quality.get()), width=4, anchor='e')
        self.png_quality_label.pack(side='left', padx=5)
        png_scale = tk.Scale(png_frame, from_=0, to=100, orient='horizontal', variable=self.png_quality,
                            command=self._update_png_label, length=300, showvalue=False)
        png_scale.pack(side='left')

        pngquant_frame = tk.Frame(self)
        pngquant_frame.pack(anchor='w', padx=10, pady=(5, 0))
        self.pngquant_check = tk.Checkbutton(
            pngquant_frame,
            text="PNG を pngquant で圧縮する（パレット量子化・不可逆）",
            variable=self.use_pngquant
        )
        self.pngquant_check.pack(side='left')
        # pngquant 利用可否に応じてトグルの有効/無効を設定し、無効時は説明を表示
        try:
            pngquant_exe = shutil.which("pngquant")
        except Exception:
            pngquant_exe = None
        if not pngquant_exe:
            self.pngquant_check.config(state='disabled')
            tk.Label(pngquant_frame, text="（pngquant 未検出のため無効）", foreground='gray').pack(side='left', padx=10)

        # リサイズ設定
        # 手動（幅/高さ）と長辺指定。アスペクト比保持のチェックに対応。
        resize_frame = tk.Frame(self)
        resize_frame.pack(anchor='w', padx=10, pady=(10, 0))
        tk.Checkbutton(resize_frame, text="画像を一括リサイズする", variable=self.resize_enabled, command=self._update_resize_controls).pack(side='left')
        tk.Label(resize_frame, text="幅:").pack(side='left', padx=(10,2))
        # 入力時の逐次検証は行わず、開始時に一度だけ数値化（非数値は0）
        self.resize_width_entry = tk.Entry(resize_frame, textvariable=self.resize_width, width=6)
        self.resize_width_entry.pack(side='left')
        tk.Label(resize_frame, text="高さ:").pack(side='left', padx=(10,2))
        self.resize_height_entry = tk.Entry(resize_frame, textvariable=self.resize_height, width=6)
        self.resize_height_entry.pack(side='left')
        self.resize_keep_aspect_chk = tk.Checkbutton(resize_frame, text="アスペクト比を保持", variable=self.resize_keep_aspect)
        self.resize_keep_aspect_chk.pack(side='left', padx=(12,0))

        preset_frame = tk.Frame(self)
        preset_frame.pack(anchor='w', padx=10, pady=(5, 0))
        tk.Label(preset_frame, text="リサイズプリセット:").pack(side='left')
        self.resize_mode_manual_rb = tk.Radiobutton(preset_frame, text="手動", variable=self.resize_mode, value='manual', command=self._update_resize_controls)
        self.resize_mode_manual_rb.pack(side='left', padx=(10,0))
        self.resize_mode_long_rb = tk.Radiobutton(preset_frame, text="長辺指定", variable=self.resize_mode, value='long_edge', command=self._update_resize_controls)
        self.resize_mode_long_rb.pack(side='left', padx=(10,0))
        tk.Label(preset_frame, text="長辺(px):").pack(side='left', padx=(10,2))
        self.long_edge_combo = ttk.Combobox(preset_frame, textvariable=self.long_edge_value_str, values=LONG_EDGE_PRESETS, width=8)
        self.long_edge_combo.pack(side='left')

        # リサイズ値が非数値にならないよう監視; 違反時に即座に0にリセット
        # *** 別の方法を採用することにしました。下記はコメントアウト。***
        # self._updating_resize_vars = False
        # self.resize_width.trace_add('write', lambda *args: self.prohibit_non_float(self.resize_width))
        # self.resize_height.trace_add('write', lambda *args: self.prohibit_non_float(self.resize_height))
        
        # 初期状態で一括リサイズは無効なので、関連コントロールをグレーアウト
        self._update_resize_controls()

        # CSV
        # 1 ファイルごとの処理結果（サイズ変化など）を CSV に記録可能。
        csv_frame = tk.Frame(self)
        csv_frame.pack(anchor='w', padx=10, pady=(10, 0))
        self.csv_enable = tk.BooleanVar(value=True)
        self.csv_path = tk.StringVar(value="")
        tk.Checkbutton(csv_frame, text="CSV ログを出力する", variable=self.csv_enable).pack(side='left')
        tk.Label(csv_frame, text="保存先(任意):").pack(side='left', padx=(10,2))
        tk.Entry(csv_frame, textvariable=self.csv_path, width=40).pack(side='left', padx=5)
        tk.Button(csv_frame, text="参照", command=self._choose_csv_path).pack(side='left', padx=3)

        # 進捗・統計・操作ボタン・ログ
        self.progress = ttk.Progressbar(self, maximum=100, length=650, mode='determinate')
        self.progress.pack(padx=10, pady=(15, 10))
        stats_frame = tk.Frame(self)
        stats_frame.pack(fill=tk.X, padx=10, pady=(0, 5))
        self.stats_var = tk.StringVar(value="統計: 処理前")
        self.stats_label = tk.Label(stats_frame, textvariable=self.stats_var, foreground="blue", font=("Arial", 10, "bold"))
        self.stats_label.pack(side='left')
        frame_btn = tk.Frame(self)
        frame_btn.pack(pady=(5, 10))
        tk.Button(frame_btn, text="圧縮開始", command=self.start_compress, width=16, bg='#ccffcc').pack(side='left', padx=10)
        tk.Button(frame_btn, text="終了", command=self.on_exit, width=12, bg='#e6e6e6').pack(side='left', padx=10)

        log_frame = tk.Frame(self)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        scrollbar = tk.Scrollbar(log_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text = tk.Text(log_frame, height=10, width=85, yscrollcommand=scrollbar.set)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.log_text.yview)

        # 初期のPDFエンジン状態表示と、Ghostscript有無に応じたPDF関連UIの有効/無効化
        self._refresh_pdf_engine_status()
        self._apply_pdf_controls_availability()
        # ウィンドウ閉じるボタン対応
        self.protocol("WM_DELETE_WINDOW", self.on_exit)

# ------------- 内部メソッド群 -------------
    def _update_resize_controls(self):
        try:
            enabled = bool(self.resize_enabled.get())
            mode = self.resize_mode.get()
            manual_active = enabled and (mode == 'manual')
            long_edge_active = enabled and (mode == 'long_edge')
            for w in (self.resize_width_entry, self.resize_height_entry):
                if manual_active:
                    w.config(state='normal', disabledforeground='#9e9e9e')
                    try:
                        w.config(background='white', foreground='black')
                    except Exception:
                        pass
                else:
                    w.config(state='disabled', disabledforeground='#9e9e9e')
                    try:
                        w.config(background='#f0f0f0', foreground='#9e9e9e')
                    except Exception:
                        pass
            if manual_active:
                self.resize_keep_aspect_chk.config(state='normal')
            else:
                self.resize_keep_aspect_chk.config(state='disabled')
            rb_state = 'normal' if enabled else 'disabled'
            self.resize_mode_manual_rb.config(state=rb_state)
            self.resize_mode_long_rb.config(state=rb_state)
            if long_edge_active:
                # 任意入力を許可するため、コンボボックスを通常入力可能状態にする
                self.long_edge_combo.config(state='normal')
            else:
                self.long_edge_combo.config(state='disabled')
        except Exception:
            pass

    def _on_drop_input(self, event):
        try:
            paths = self.tk.splitlist(event.data)
        except Exception:
            paths = [event.data]
        picked = None
        for p in paths:
            p = p.strip('{}')
            if os.path.isdir(p):
                picked = p
                break
            elif os.path.isfile(p):
                picked = os.path.dirname(p)
                break
        if picked:
            self.input_dir.set(picked)
            self.log(f"ドラッグ＆ドロップで入力フォルダを設定: {picked}")

    def _toggle_pdf_slider(self):
        # Ghostscriptが無い場合は常に無効化
        gs_available = shutil.which(GS_COMMAND) is not None
        if not gs_available:
            try:
                self.pdf_quality_enabled.set(False)
            except Exception:
                pass
        state = 'normal' if (self.pdf_quality_enabled.get() and gs_available) else 'disabled'
        self.pdf_scale.configure(state=state)

    def _update_pdf_label(self, val):
        self.pdf_quality_label.config(text=str(int(float(val))))

    def _update_jpg_label(self, val):
        self.jpg_quality_label.config(text=str(int(float(val))))

    def _update_png_label(self, val):
        self.png_quality_label.config(text=str(int(float(val))))

    def _choose_csv_path(self):
        initialdir = self.output_dir.get() or os.getcwd()
        path = filedialog.asksaveasfilename(initialdir=initialdir, defaultextension='.csv', filetypes=[('CSV files','*.csv'),('All files','*.*')])
        if path:
            self.csv_path.set(path)

    def _to_non_negative_int(self, s: str) -> int:
        """文字列を非負整数へ変換。空欄や非数値は 0 を返す。"""
        try:
            # 小数入力も許容し、切り捨て。
            val = int(float(s.strip()))
            return val if val >= 0 else 0
        except Exception:
            return 0

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

    def log(self, msg):
        self.log_text.insert("end", msg + "\n")
        self.log_text.see("end")

    def update_progress(self, current, total):
        if total <= 0:
            self.progress["value"] = 100
        else:
            percent = int(current / total * 100)
            self.progress["value"] = percent
        self.update_idletasks()

    def update_stats(self, orig_total, out_total, saved, saved_pct):
        stats_msg = f"統計: 元合計={human_readable(orig_total)}, 出力合計={human_readable(out_total)}, 削減={human_readable(saved)} ({saved_pct:.1f}%)"
        self.stats_var.set(stats_msg)

    # pngquant 確認ボタンは不要のため削除済み（UIで自動判定表示）

    # check_pdf_tools は不要となったため削除済み

    def _refresh_pdf_engine_status(self):
        try:
            gs_exe = shutil.which(GS_COMMAND)
            if gs_exe:
                self.pdf_engine_status_var.set("Ghostscript（利用可能）")
            elif PYPDF_AVAILABLE:
                self.pdf_engine_status_var.set("pypdf（Ghostscript未検出）")
            else:
                self.pdf_engine_status_var.set("圧縮不可（Ghostscript/pypdf なし）")
        except Exception:
            self.pdf_engine_status_var.set("判定失敗")

    def _apply_pdf_controls_availability(self):
        """Ghostscriptが無い場合は、PDFプリセット選択とPDF品質スライダーUIを無効化する。"""
        try:
            gs_available = shutil.which(GS_COMMAND) is not None
            rb_state = 'normal' if gs_available else 'disabled'
            for rb in getattr(self, 'gs_preset_radiobuttons', []):
                try:
                    rb.config(state=rb_state)
                except Exception:
                    pass
            # 品質チェックボックスとスライダー
            try:
                self.pdf_quality_check.config(state=rb_state)
            except Exception:
                pass
            if not gs_available:
                # 強制的にスライダーを無効にし、チェックも外す
                try:
                    self.pdf_quality_enabled.set(False)
                except Exception:
                    pass
                try:
                    self.pdf_scale.configure(state='disabled')
                except Exception:
                    pass
        except Exception:
            pass

    def start_compress(self):
        input_ = self.input_dir.get()
        output_ = self.output_dir.get()
        fixed_in, fixed_out, conflict = self._check_overlap_and_fix(input_, output_)
        if conflict:
            self.input_dir.set(fixed_in)
            self.output_dir.set(fixed_out)
            input_ = fixed_in
            output_ = fixed_out
            self.log(f"入出力フォルダ重なり検出のためリセットしました → 入力: {fixed_in} / 出力: {fixed_out}")
            messagebox.showwarning(
                "入出力フォルダの重なり",
                "入力フォルダと出力フォルダが同一、または内包関係にあります。\n"
                "予期しない上書きや無限処理を防ぐため、両方ともデフォルトの\n"
                f"入力: {DEFAULT_INPUT_DIR}\n出力: {DEFAULT_OUTPUT_DIR} に戻しました。"
            )
        level = self.gs_quality.get()
        # PDFエンジンはシステムにGhostscriptがある場合はGhostscript固定、
        # Ghostscriptが無い場合のみ pypdf を使用（固定方針）
        gs_available = shutil.which(GS_COMMAND) is not None
        engine = 'ghostscript' if gs_available else ('pypdf' if PYPDF_AVAILABLE else 'none')
        jpg_q = self.jpg_quality.get()
        png_q = self.png_quality.get()
        use_pq = self.use_pngquant.get()
        if not input_ or not output_:
            messagebox.showerror("エラー", "両方のフォルダを選択してください")
            return
        os.makedirs(output_, exist_ok=True)
        self.log_text.delete(1.0, "end")
        self.progress["value"] = 0
        self.stats_var.set("統計: 処理中...")
        self.log(f"圧縮処理を開始します…")
        self.log(f"出力先: {output_}")
        if engine == 'ghostscript':
            if gs_available:
                self.log(f"PDF圧縮: Ghostscript使用（プリセット: {level}）")
            else:
                self.log("PDF圧縮: Ghostscript選択ですが未検出のため圧縮不可")
        elif engine == 'pypdf':
            if PYPDF_AVAILABLE:
                self.log("PDF圧縮: pypdf使用 ※Ghostscript推奨")
            else:
                self.log("PDF圧縮: pypdf選択ですが未インストールのため圧縮不可")
        else:
            if gs_available:
                self.log(f"PDF圧縮: Ghostscript使用（プリセット: {level}）")
            elif PYPDF_AVAILABLE:
                self.log("PDF圧縮: pypdf使用 ※Ghostscript推奨")
            else:
                self.log("警告: PDF圧縮ツールが利用できません（PDFは圧縮されません）")
        if self.pdf_quality_enabled.get():
            self.log(f"PDF品質: {self.pdf_quality.get()} (DPI上書き有効)")
        else:
            self.log("PDF品質: 無効（プリセットの既定設定を使用）")
        self.log(f"JPG品質: {jpg_q}, PNG品質: {png_q}, pngquant使用: {use_pq}")
        # 非数値・空欄は 0 にフォールバック（処理開始時に一度だけ）
        r_w = self._to_non_negative_int(self.resize_width.get())
        r_h = self._to_non_negative_int(self.resize_height.get())
        self._update_resize_controls()
        r_mode = self.resize_mode.get()
        try:
            r_le = int(self.long_edge_value_str.get().strip())
        except Exception:
            r_le = 0
        r_le = max(0, r_le)
        r_enabled = self.resize_enabled.get() and ((r_mode == 'manual' and (r_w > 0 or r_h > 0)) or (r_mode == 'long_edge' and r_le > 0))
        r_keep = self.resize_keep_aspect.get()
        resize_config = None
        if r_enabled:
            if r_mode == 'long_edge':
                resize_config = { 'enabled': True, 'mode': 'long_edge', 'long_edge': r_le, 'keep_aspect': True }
            else:
                resize_config = { 'enabled': True, 'mode': 'manual', 'width': r_w, 'height': r_h, 'keep_aspect': r_keep }
        thread = threading.Thread(
            target=compress_folder,
            args=(
                input_, output_, level, jpg_q, png_q, use_pq, engine,
                self.log, self.update_progress, self.update_stats,
                self.pdf_quality.get(), self.pdf_quality_enabled.get(),
                resize_config if resize_config else False, (r_w if r_mode=='manual' else 0), (r_h if r_mode=='manual' else 0),
                self.csv_enable.get(), (self.csv_path.get().strip() or None), True
            ),
            daemon=True
        )
        self.threads.append(thread)
        thread.start()

    def _paths_overlap(self, a, b):
        try:
            ra = os.path.abspath(a)
            rb = os.path.abspath(b)
            if ra == rb:
                return True
            common = os.path.commonpath([ra, rb])
            return common == ra or common == rb
        except Exception:
            return False

    def _check_overlap_and_fix(self, input_dir, output_dir):
        conflict = False
        if input_dir and output_dir and self._paths_overlap(input_dir, output_dir):
            conflict = True
            return DEFAULT_INPUT_DIR, DEFAULT_OUTPUT_DIR, conflict
        return input_dir, output_dir, conflict

    def _validate_and_fix_dirs(self):
        new_in, new_out, conflict = self._check_overlap_and_fix(self.input_dir.get(), self.output_dir.get())
        if conflict:
            self.input_dir.set(new_in)
            self.output_dir.set(new_out)
            self.log(f"入出力フォルダ重なり検出のためリセットしました → 入力: {new_in} / 出力: {new_out}")
            messagebox.showwarning(
                "入出力フォルダの重なり",
                "入力フォルダと出力フォルダが同一、または内包関係にあります。\n"
                "安全のため両方をデフォルトに戻しました。"
            )

    def cleanup_input(self):
        input_ = self.input_dir.get()
        if not input_ or not os.path.exists(input_):
            messagebox.showerror("エラー", "入力フォルダが未指定、または存在しません")
            return
        target_count = count_target_files(input_, INPUT_DIR_CLEANUP_EXTENSIONS)
        exts_str = ', '.join(sorted(INPUT_DIR_CLEANUP_EXTENSIONS))
        play_sound(os.path.join(SOUNDS_DIR, 'warning.wav'))
        confirm_msg = (
            f"入力フォルダ内の画像・PDFファイルを削除しますか？\n\n"
            f"【対象拡張子】\n{exts_str}\n\n"
            f"【削除対象ファイル数】\n約 {target_count} ファイル\n\n"
            f"【重要】\n"
            f"・サブフォルダ内のファイルも含めて削除されます\n"
            f"・この操作は取り消せません\n\n"
            f"本当に削除しますか？"
        )
        if messagebox.askyesno("クリーンアップ確認", confirm_msg):
            self.log(f"入力フォルダのクリーンアップ処理を開始します（対象: {exts_str}, サブフォルダ含む）…")
            thread = threading.Thread(
                target=cleanup_folder,
                args=(input_, self.log, "入力フォルダ", INPUT_DIR_CLEANUP_EXTENSIONS),
                daemon=True
            )
            self.threads.append(thread)
            thread.start()

    def cleanup_output(self):
        output_ = self.output_dir.get()
        if not output_ or not os.path.exists(output_):
            messagebox.showerror("エラー", "出力フォルダが未指定、または存在しません")
            return
        target_count = count_target_files(output_, OUTPUT_DIR_CLEANUP_EXTENSIONS)
        exts_str = ', '.join(sorted(OUTPUT_DIR_CLEANUP_EXTENSIONS))
        play_sound(os.path.join(SOUNDS_DIR, 'warning.wav'))
        confirm_msg = (
            f"出力フォルダ内の画像・PDFファイルを削除しますか？\n\n"
            f"【対象拡張子】\n{exts_str}\n\n"
            f"【削除対象ファイル数】\n約 {target_count} ファイル\n\n"
            f"【重要】\n"
            f"・サブフォルダ内のファイルも含めて削除されます\n"
            f"・この操作は取り消せません\n\n"
            f"本当に削除しますか？"
        )
        if messagebox.askyesno("クリーンアップ確認", confirm_msg):
            self.log(f"出力フォルダのクリーンアップ処理を開始します（対象: {exts_str}, サブフォルダ含む）…")
            thread = threading.Thread(
                target=cleanup_folder,
                args=(output_, self.log, "出力フォルダ", OUTPUT_DIR_CLEANUP_EXTENSIONS),
                daemon=True
            )
            self.threads.append(thread)
            thread.start()

    def on_exit(self):
        alive = any(t.is_alive() for t in self.threads)
        if alive:
            if not messagebox.askyesno("終了確認", "処理中のスレッドがあります。強制終了してもよろしいですか？"):
                return
        self.destroy()

    # ------------- 入力検証ヘルパー -------------

    # リサイズ値の空欄や非数値入力を防止するためのヘルパー
    # *** 別の方法を採用することにしました。下記はコメントアウト。***
    # def prohibit_non_float(self, str_var: tk.StringVar):
    #     if self._updating_resize_vars:
    #         return
    #     self._updating_resize_vars = True
    #     val = str_var.get()
    #     if not can_be_converted_to_float(val):
    #         str_var.set('0')
    #     self._updating_resize_vars = False
    
    # 新しい方法: 圧縮時にリサイズ値が非数値であるかどうかを判定 -> Falseならstart_compressメソッド内で0にリセット
    def is_convertible_to_float(self, str_var: tk.StringVar) -> bool:
        val = str_var.get()
        try:
            float(val)
            return True
        except ValueError:
            return False