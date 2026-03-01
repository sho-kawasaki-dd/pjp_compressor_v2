#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ui_pyside.py

PySide6 ベースの GUI を提供するモジュール。圧縮ロジックは `compressor_utils`
に委譲し、ユーザー操作（フォルダ選択、PDF エンジン切替、品質設定、プリセット、
進捗表示、CSV ログの有効化など）を受け付ける。

レイアウト構成:
- フォルダ選択行（常時表示、ネイティブ D&D 対応）
- タブ（圧縮設定 / ログ・進捗）
  - 圧縮設定: PDF圧縮 / 画像圧縮 / リサイズ / 出力設定 の 4 セクション
  - ログ・進捗: プログレスバー / 統計 / ログテキスト
- アクションボタン行（常時表示）

設計ポイント:
- 処理は QThread + Signal で非同期化し、スレッド安全性を確保。
- PDF エンジン（ネイティブ / GhostScript）を UI から選択可能。
- エンジン未検出時は対応ラジオを自動的に無効化。
- ドラッグ＆ドロップは Qt ネイティブ対応（外部ライブラリ不要）。
"""
import os
import sys
import shutil

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QGroupBox, QTabWidget, QLabel, QLineEdit, QPushButton,
    QRadioButton, QCheckBox, QSlider, QComboBox, QTextEdit, QProgressBar,
    QFileDialog, QMessageBox, QButtonGroup, QScrollArea, QSizePolicy,
)
from PySide6.QtCore import Qt, QThread, Signal, QUrl

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
            reply = QMessageBox.question(
                None, "「圧縮済みファイル」フォルダ作成",
                "デスクトップに「圧縮済みファイル」フォルダを作成してよいですか？")
            if reply == QMessageBox.Yes:
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
# DEFAULT_OUTPUT_DIR は App.__init__ 内で遅延取得する（QApplication 起動後に QMessageBox を使うため）


# =============================================================================
#  ワーカースレッド
# =============================================================================
class CompressWorker(QThread):
    """compress_folder を別スレッドで実行し、Signal でログ・進捗・統計を送信する。"""
    log_signal = Signal(str)
    progress_signal = Signal(int, int)
    stats_signal = Signal(float, float, float, float)
    finished_signal = Signal()

    def __init__(self, kwargs: dict, parent=None):
        super().__init__(parent)
        self._kwargs = kwargs

    def run(self):
        self._kwargs['log_func'] = self.log_signal.emit
        self._kwargs['progress_func'] = lambda c, t: self.progress_signal.emit(c, t)
        self._kwargs['stats_func'] = lambda o, out, s, sp: self.stats_signal.emit(o, out, s, sp)
        try:
            compress_folder(**self._kwargs)
        except Exception as e:
            self.log_signal.emit(f"圧縮中にエラー: {e}")
        finally:
            self.finished_signal.emit()


class CleanupWorker(QThread):
    """cleanup_folder を別スレッドで実行する。"""
    log_signal = Signal(str)
    finished_signal = Signal()

    def __init__(self, folder, folder_type, extensions, parent=None):
        super().__init__(parent)
        self._folder = folder
        self._folder_type = folder_type
        self._extensions = extensions

    def run(self):
        try:
            cleanup_folder(self._folder, self.log_signal.emit,
                           self._folder_type, self._extensions)
        except Exception as e:
            self.log_signal.emit(f"クリーンアップ中にエラー: {e}")
        finally:
            self.finished_signal.emit()


# =============================================================================
#  App クラス定義
# =============================================================================
class App(QMainWindow):
    """フォルダ一括圧縮アプリケーションのメインウィンドウクラス (PySide6 版)。"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("フォルダ一括圧縮アプリ v2 (Qt)")
        w, h = APP_DEFAULT_WINDOW_SIZE.split('x')
        self.resize(int(w), int(h))
        self.setAcceptDrops(True)

        self._workers: list = []

        # 出力フォルダ（QApplication 起動後に取得）
        self._default_output_dir = get_default_output_dir()

        # ── 状態変数 ──
        self._pdf_engine = 'native'
        self._pdf_mode = 'both'
        self._gs_preset = GS_DEFAULT_PRESET

        # ── UI 構築 ──
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(10, 10, 10, 10)

        self._build_folder_section(main_layout)
        self._build_notebook(main_layout)
        self._build_action_buttons(main_layout)

        # 初期状態更新
        self._refresh_pdf_engine_status()
        self._update_pdf_controls()
        self._update_resize_controls()

    # ==================================================================
    #  D&D（ネイティブ）
    # ==================================================================

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if os.path.isdir(path):
                self.input_dir_edit.setText(path)
                self.log(f"D&D で入力フォルダ設定: {path}")
                break
            elif os.path.isfile(path):
                d = os.path.dirname(path)
                self.input_dir_edit.setText(d)
                self.log(f"D&D で入力フォルダ設定: {d}")
                break

    # ==================================================================
    #  レイアウト構築
    # ==================================================================

    def _build_folder_section(self, parent_layout):
        """フォルダ選択行。"""
        group = QGroupBox("フォルダ選択（D&D 対応）")
        layout = QVBoxLayout(group)

        # 入力行
        row_in = QHBoxLayout()
        row_in.addWidget(QLabel("入力フォルダ:"))
        self.input_dir_edit = QLineEdit(DEFAULT_INPUT_DIR)
        row_in.addWidget(self.input_dir_edit, 1)
        btn_in = QPushButton("選択")
        btn_in.clicked.connect(self.choose_input)
        row_in.addWidget(btn_in)
        btn_clean_in = QPushButton("クリーンアップ")
        btn_clean_in.setStyleSheet("background-color: #d0f6ff;")
        btn_clean_in.clicked.connect(self.cleanup_input)
        row_in.addWidget(btn_clean_in)
        layout.addLayout(row_in)

        # 出力行
        row_out = QHBoxLayout()
        row_out.addWidget(QLabel("出力フォルダ:"))
        self.output_dir_edit = QLineEdit(self._default_output_dir)
        row_out.addWidget(self.output_dir_edit, 1)
        btn_out = QPushButton("選択")
        btn_out.clicked.connect(self.choose_output)
        row_out.addWidget(btn_out)
        btn_clean_out = QPushButton("クリーンアップ")
        btn_clean_out.setStyleSheet("background-color: #ffcaca;")
        btn_clean_out.clicked.connect(self.cleanup_output)
        row_out.addWidget(btn_clean_out)
        layout.addLayout(row_out)

        parent_layout.addWidget(group)

    def _build_notebook(self, parent_layout):
        """タブウィジェット。"""
        self.tabs = QTabWidget()
        parent_layout.addWidget(self.tabs, 1)

        # 圧縮設定タブ（スクロール可能）
        settings_widget = QWidget()
        settings_layout = QVBoxLayout(settings_widget)
        settings_layout.setContentsMargins(5, 5, 5, 5)
        self._build_pdf_section(settings_layout)
        self._build_image_section(settings_layout)
        self._build_resize_section(settings_layout)
        self._build_output_section(settings_layout)
        settings_layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(settings_widget)
        self.tabs.addTab(scroll, " 圧縮設定 ")

        # ログ・進捗タブ
        log_widget = QWidget()
        self._build_log_tab(log_widget)
        self.tabs.addTab(log_widget, " ログ / 進捗 ")

    # ------------------------------------------------------------------
    #  PDF 圧縮セクション
    # ------------------------------------------------------------------

    def _build_pdf_section(self, parent_layout):
        group = QGroupBox("PDF 圧縮")
        layout = QVBoxLayout(group)

        # ── エンジン選択 ──
        engine_row = QHBoxLayout()
        engine_row.addWidget(QLabel("エンジン:"))
        self.engine_group = QButtonGroup(self)
        self.native_rb = QRadioButton("ネイティブ (PyMuPDF + pikepdf)")
        self.native_rb.setChecked(True)
        self.gs_rb = QRadioButton("GhostScript")
        self.engine_group.addButton(self.native_rb, 0)
        self.engine_group.addButton(self.gs_rb, 1)
        self.engine_group.buttonClicked.connect(self._on_engine_changed)
        engine_row.addWidget(self.native_rb)
        engine_row.addWidget(self.gs_rb)
        self.engine_status_label = QLabel("判定中…")
        self.engine_status_label.setStyleSheet("color: purple;")
        engine_row.addWidget(self.engine_status_label)
        engine_row.addStretch()
        layout.addLayout(engine_row)

        # ── ネイティブフレーム ──
        self.native_widget = QWidget()
        self._build_native_controls(self.native_widget)
        layout.addWidget(self.native_widget)

        # ── GS フレーム ──
        self.gs_widget = QWidget()
        self._build_gs_controls(self.gs_widget)
        layout.addWidget(self.gs_widget)

        parent_layout.addWidget(group)

    def _build_native_controls(self, parent):
        layout = QVBoxLayout(parent)
        layout.setContentsMargins(0, 0, 0, 0)

        # モード選択
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("モード:"))
        self.mode_group = QButtonGroup(self)
        self._mode_radios = {}
        for val, label in PDF_COMPRESS_MODES.items():
            rb = QRadioButton(label)
            self.mode_group.addButton(rb)
            self._mode_radios[val] = rb
            mode_row.addWidget(rb)
        self._mode_radios['both'].setChecked(True)
        self.mode_group.buttonClicked.connect(self._on_mode_changed)
        mode_row.addStretch()
        layout.addLayout(mode_row)

        # ── 非可逆オプション ──
        lossy_group = QGroupBox("非可逆オプション")
        lossy_layout = QVBoxLayout(lossy_group)
        self._native_lossy_widgets: list = []

        # DPI
        dpi_row = QHBoxLayout()
        w = QLabel("DPI:")
        dpi_row.addWidget(w)
        self._native_lossy_widgets.append(w)
        self.dpi_label = QLabel(str(PDF_LOSSY_DPI_DEFAULT))
        self.dpi_label.setMinimumWidth(30)
        dpi_row.addWidget(self.dpi_label)
        self._native_lossy_widgets.append(self.dpi_label)
        self.dpi_slider = QSlider(Qt.Horizontal)
        self.dpi_slider.setRange(*PDF_LOSSY_DPI_RANGE)
        self.dpi_slider.setValue(PDF_LOSSY_DPI_DEFAULT)
        self.dpi_slider.valueChanged.connect(
            lambda v: self.dpi_label.setText(str(v)))
        dpi_row.addWidget(self.dpi_slider, 1)
        self._native_lossy_widgets.append(self.dpi_slider)
        lossy_layout.addLayout(dpi_row)

        # JPEG 品質
        jpeg_row = QHBoxLayout()
        w = QLabel("JPEG品質:")
        jpeg_row.addWidget(w)
        self._native_lossy_widgets.append(w)
        self.jpeg_q_label = QLabel(str(PDF_LOSSY_JPEG_QUALITY_DEFAULT))
        self.jpeg_q_label.setMinimumWidth(30)
        jpeg_row.addWidget(self.jpeg_q_label)
        self._native_lossy_widgets.append(self.jpeg_q_label)
        self.jpeg_q_slider = QSlider(Qt.Horizontal)
        self.jpeg_q_slider.setRange(1, 100)
        self.jpeg_q_slider.setValue(PDF_LOSSY_JPEG_QUALITY_DEFAULT)
        self.jpeg_q_slider.valueChanged.connect(
            lambda v: self.jpeg_q_label.setText(str(v)))
        jpeg_row.addWidget(self.jpeg_q_slider, 1)
        self._native_lossy_widgets.append(self.jpeg_q_slider)
        self.jpeg_note = QLabel("※JPEG元画像にのみ適用")
        self.jpeg_note.setStyleSheet("color: gray;")
        jpeg_row.addWidget(self.jpeg_note)
        lossy_layout.addLayout(jpeg_row)

        # PNG→JPEG
        self.png_to_jpeg_cb = QCheckBox("PNG → JPEG 変換")
        self.png_to_jpeg_cb.setChecked(PDF_LOSSY_PNG_TO_JPEG_DEFAULT)
        self.png_to_jpeg_cb.stateChanged.connect(self._update_pdf_controls)
        lossy_layout.addWidget(self.png_to_jpeg_cb)
        self._native_lossy_widgets.append(self.png_to_jpeg_cb)

        layout.addWidget(lossy_group)
        self._lossy_group = lossy_group

        # ── 可逆オプション ──
        lossless_group = QGroupBox("可逆オプション")
        ll_layout = QVBoxLayout(lossless_group)
        self._native_ll_cbs = self._create_lossless_controls(ll_layout)
        layout.addWidget(lossless_group)
        self._native_lossless_group = lossless_group

    def _build_gs_controls(self, parent):
        layout = QVBoxLayout(parent)
        layout.setContentsMargins(0, 0, 0, 0)

        # プリセット
        preset_group = QGroupBox("プリセット")
        preset_layout = QGridLayout(preset_group)
        self.preset_group_btn = QButtonGroup(self)
        self._gs_preset_radios: dict = {}
        all_presets = list(GS_PRESETS.items()) + [('custom', 'カスタム')]
        for idx, (key, label) in enumerate(all_presets):
            display = label if key == 'custom' else f"{key}: {label}"
            rb = QRadioButton(display)
            self.preset_group_btn.addButton(rb)
            self._gs_preset_radios[key] = rb
            r, c = divmod(idx, 2)
            preset_layout.addWidget(rb, r, c)
        self._gs_preset_radios[GS_DEFAULT_PRESET].setChecked(True)
        self.preset_group_btn.buttonClicked.connect(self._on_gs_preset_changed)
        layout.addWidget(preset_group)

        # カスタム DPI
        custom_row = QHBoxLayout()
        self.gs_dpi_lbl_static = QLabel("カスタム DPI:")
        custom_row.addWidget(self.gs_dpi_lbl_static)
        self.gs_dpi_label = QLabel(str(PDF_LOSSY_DPI_DEFAULT))
        self.gs_dpi_label.setMinimumWidth(30)
        custom_row.addWidget(self.gs_dpi_label)
        self.gs_dpi_slider = QSlider(Qt.Horizontal)
        self.gs_dpi_slider.setRange(*PDF_LOSSY_DPI_RANGE)
        self.gs_dpi_slider.setValue(PDF_LOSSY_DPI_DEFAULT)
        self.gs_dpi_slider.valueChanged.connect(
            lambda v: self.gs_dpi_label.setText(str(v)))
        custom_row.addWidget(self.gs_dpi_slider, 1)
        layout.addLayout(custom_row)
        self._gs_custom_widgets = [
            self.gs_dpi_lbl_static, self.gs_dpi_label, self.gs_dpi_slider]

        # pikepdf チェック
        self.gs_use_lossless_cb = QCheckBox("pikepdf 構造最適化も適用")
        self.gs_use_lossless_cb.setChecked(True)
        self.gs_use_lossless_cb.stateChanged.connect(self._update_pdf_controls)
        layout.addWidget(self.gs_use_lossless_cb)

        # GS 用可逆オプション
        gs_ll_group = QGroupBox("可逆オプション（pikepdf）")
        gs_ll_layout = QVBoxLayout(gs_ll_group)
        self._gs_ll_cbs = self._create_lossless_controls(gs_ll_layout)
        layout.addWidget(gs_ll_group)
        self._gs_lossless_group = gs_ll_group

    # ------------------------------------------------------------------
    #  画像圧縮セクション
    # ------------------------------------------------------------------

    def _build_image_section(self, parent_layout):
        group = QGroupBox("画像圧縮")
        layout = QVBoxLayout(group)

        # JPG
        jpg_row = QHBoxLayout()
        jpg_row.addWidget(QLabel("JPG 品質 (0-100):"))
        self.jpg_q_label = QLabel("70")
        self.jpg_q_label.setMinimumWidth(30)
        jpg_row.addWidget(self.jpg_q_label)
        self.jpg_slider = QSlider(Qt.Horizontal)
        self.jpg_slider.setRange(0, 100)
        self.jpg_slider.setValue(70)
        self.jpg_slider.valueChanged.connect(
            lambda v: self.jpg_q_label.setText(str(v)))
        jpg_row.addWidget(self.jpg_slider, 1)
        layout.addLayout(jpg_row)

        # PNG
        png_row = QHBoxLayout()
        png_row.addWidget(QLabel("PNG 品質 (0-100):"))
        self.png_q_label = QLabel("70")
        self.png_q_label.setMinimumWidth(30)
        png_row.addWidget(self.png_q_label)
        self.png_slider = QSlider(Qt.Horizontal)
        self.png_slider.setRange(0, 100)
        self.png_slider.setValue(70)
        self.png_slider.valueChanged.connect(
            lambda v: self.png_q_label.setText(str(v)))
        png_row.addWidget(self.png_slider, 1)
        layout.addLayout(png_row)

        # pngquant
        self.pngquant_cb = QCheckBox("pngquant 使用（パレット量子化・不可逆）")
        self.pngquant_cb.setChecked(True)
        if not shutil.which("pngquant"):
            self.pngquant_cb.setEnabled(False)
            self.pngquant_cb.setText("pngquant 使用（未検出のため無効）")
        layout.addWidget(self.pngquant_cb)

        parent_layout.addWidget(group)

    # ------------------------------------------------------------------
    #  リサイズセクション
    # ------------------------------------------------------------------

    def _build_resize_section(self, parent_layout):
        group = QGroupBox("リサイズ")
        layout = QVBoxLayout(group)

        # 有効化
        self.resize_enable_cb = QCheckBox("画像を一括リサイズする")
        self.resize_enable_cb.stateChanged.connect(self._update_resize_controls)
        layout.addWidget(self.resize_enable_cb)

        # 手動
        manual_row = QHBoxLayout()
        self.resize_manual_rb = QRadioButton("手動")
        self.resize_manual_rb.setChecked(True)
        self.resize_manual_rb.toggled.connect(self._update_resize_controls)
        manual_row.addWidget(self.resize_manual_rb)
        manual_row.addWidget(QLabel("幅:"))
        self.resize_w_edit = QLineEdit("0")
        self.resize_w_edit.setMaximumWidth(60)
        manual_row.addWidget(self.resize_w_edit)
        manual_row.addWidget(QLabel("高さ:"))
        self.resize_h_edit = QLineEdit("0")
        self.resize_h_edit.setMaximumWidth(60)
        manual_row.addWidget(self.resize_h_edit)
        self.resize_aspect_cb = QCheckBox("アスペクト比保持")
        self.resize_aspect_cb.setChecked(True)
        manual_row.addWidget(self.resize_aspect_cb)
        manual_row.addStretch()
        layout.addLayout(manual_row)

        # 長辺指定
        long_row = QHBoxLayout()
        self.resize_long_rb = QRadioButton("長辺指定")
        self.resize_long_rb.toggled.connect(self._update_resize_controls)
        long_row.addWidget(self.resize_long_rb)
        long_row.addWidget(QLabel("長辺(px):"))
        self.long_edge_combo = QComboBox()
        self.long_edge_combo.setEditable(True)
        self.long_edge_combo.addItems(LONG_EDGE_PRESETS)
        self.long_edge_combo.setCurrentText("1024")
        self.long_edge_combo.setMaximumWidth(100)
        long_row.addWidget(self.long_edge_combo)
        long_row.addStretch()
        layout.addLayout(long_row)

        # ラジオグループ
        self.resize_mode_group = QButtonGroup(self)
        self.resize_mode_group.addButton(self.resize_manual_rb, 0)
        self.resize_mode_group.addButton(self.resize_long_rb, 1)

        parent_layout.addWidget(group)

    # ------------------------------------------------------------------
    #  出力設定セクション
    # ------------------------------------------------------------------

    def _build_output_section(self, parent_layout):
        group = QGroupBox("出力設定")
        layout = QVBoxLayout(group)

        # CSV
        csv_row = QHBoxLayout()
        self.csv_enable_cb = QCheckBox("CSV ログを出力する")
        self.csv_enable_cb.setChecked(True)
        csv_row.addWidget(self.csv_enable_cb)
        csv_row.addWidget(QLabel("保存先(任意):"))
        self.csv_path_edit = QLineEdit()
        csv_row.addWidget(self.csv_path_edit, 1)
        btn_csv = QPushButton("参照")
        btn_csv.clicked.connect(self._choose_csv_path)
        csv_row.addWidget(btn_csv)
        layout.addLayout(csv_row)

        # ZIP
        self.extract_zip_cb = QCheckBox("ZIP 展開してから圧縮")
        self.extract_zip_cb.setChecked(True)
        layout.addWidget(self.extract_zip_cb)

        parent_layout.addWidget(group)

    # ------------------------------------------------------------------
    #  ログ・進捗タブ
    # ------------------------------------------------------------------

    def _build_log_tab(self, parent):
        layout = QVBoxLayout(parent)

        # プログレスバー
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        # 統計
        self.stats_label = QLabel("統計: 処理前")
        self.stats_label.setStyleSheet("color: blue; font-weight: bold; font-size: 11px;")
        layout.addWidget(self.stats_label)

        # ログテキスト
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        layout.addWidget(self.log_text, 1)

    # ------------------------------------------------------------------
    #  アクションボタン
    # ------------------------------------------------------------------

    def _build_action_buttons(self, parent_layout):
        row = QHBoxLayout()
        row.addStretch()
        btn_start = QPushButton("圧縮開始")
        btn_start.setMinimumWidth(140)
        btn_start.setStyleSheet("background-color: #ccffcc; font-weight: bold;")
        btn_start.clicked.connect(self.start_compress)
        row.addWidget(btn_start)
        btn_exit = QPushButton("終了")
        btn_exit.setMinimumWidth(100)
        btn_exit.setStyleSheet("background-color: #e6e6e6;")
        btn_exit.clicked.connect(self.on_exit)
        row.addWidget(btn_exit)
        row.addStretch()
        parent_layout.addLayout(row)

    # ==================================================================
    #  ヘルパー: 可逆チェックボックス生成
    # ==================================================================

    def _create_lossless_controls(self, parent_layout):
        """可逆オプションのチェックボックス群を生成。dict[str, QCheckBox] を返す。"""
        _defaults = PDF_LOSSLESS_OPTIONS_DEFAULT
        cbs = {}

        row1 = QHBoxLayout()
        for key, label in [
            ('linearize', 'Linearize'),
            ('object_streams', 'ObjStream圧縮'),
            ('clean_metadata', 'メタデータ除去'),
        ]:
            cb = QCheckBox(label)
            cb.setChecked(_defaults[key])
            cbs[key] = cb
            row1.addWidget(cb)
        row1.addStretch()
        parent_layout.addLayout(row1)

        row2 = QHBoxLayout()
        for key, label in [
            ('recompress_streams', 'Flate再圧縮'),
            ('remove_unreferenced', '孤立リソース削除'),
        ]:
            cb = QCheckBox(label)
            cb.setChecked(_defaults[key])
            cbs[key] = cb
            row2.addWidget(cb)
        row2.addStretch()
        parent_layout.addLayout(row2)

        return cbs

    # ==================================================================
    #  コントロール更新
    # ==================================================================

    def _on_engine_changed(self, btn):
        self._pdf_engine = 'native' if btn is self.native_rb else 'gs'
        self._update_pdf_controls()

    def _on_mode_changed(self, btn):
        for val, rb in self._mode_radios.items():
            if rb is btn:
                self._pdf_mode = val
                break
        self._update_pdf_controls()

    def _on_gs_preset_changed(self, btn):
        for key, rb in self._gs_preset_radios.items():
            if rb is btn:
                self._gs_preset = key
                break
        self._update_pdf_controls()

    def _update_pdf_controls(self):
        """エンジン・モード選択に連動して PDF コントロールの表示/状態を更新する。"""
        is_native = self._pdf_engine == 'native'
        self.native_widget.setVisible(is_native)
        self.gs_widget.setVisible(not is_native)

        if is_native:
            lossy_active = self._pdf_mode in ('lossy', 'both')
            lossless_active = self._pdf_mode in ('lossless', 'both')

            for w in self._native_lossy_widgets:
                w.setEnabled(lossy_active)
            self.dpi_slider.setEnabled(lossy_active)
            self.jpeg_q_slider.setEnabled(lossy_active)
            self.png_to_jpeg_cb.setEnabled(lossy_active)

            # JPEG 注記
            self.jpeg_note.setVisible(
                lossy_active and not self.png_to_jpeg_cb.isChecked())

            for cb in self._native_ll_cbs.values():
                cb.setEnabled(lossless_active)
        else:
            custom = self._gs_preset == 'custom'
            for w in self._gs_custom_widgets:
                w.setEnabled(custom)

            gs_ll = self.gs_use_lossless_cb.isChecked()
            for cb in self._gs_ll_cbs.values():
                cb.setEnabled(gs_ll)

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
            self.gs_rb.setEnabled(False)
            if self._pdf_engine == 'gs':
                self._pdf_engine = 'native'
                self.native_rb.setChecked(True)

        if not FITZ_AVAILABLE and not PIKEPDF_AVAILABLE:
            self.native_rb.setEnabled(False)

        self.engine_status_label.setText(f"（{', '.join(parts)}）")

    def _update_resize_controls(self):
        """リサイズ関連コントロールの有効/無効を更新する。"""
        enabled = self.resize_enable_cb.isChecked()
        is_manual = enabled and self.resize_manual_rb.isChecked()
        is_long = enabled and self.resize_long_rb.isChecked()

        self.resize_manual_rb.setEnabled(enabled)
        self.resize_long_rb.setEnabled(enabled)
        self.resize_w_edit.setEnabled(is_manual)
        self.resize_h_edit.setEnabled(is_manual)
        self.resize_aspect_cb.setEnabled(is_manual)
        self.long_edge_combo.setEnabled(is_long)

    # ==================================================================
    #  フォルダ操作
    # ==================================================================

    def choose_input(self):
        folder = QFileDialog.getExistingDirectory(
            self, "入力フォルダを選択", self.input_dir_edit.text())
        if folder:
            self.input_dir_edit.setText(folder)
            self._validate_and_fix_dirs()

    def choose_output(self):
        folder = QFileDialog.getExistingDirectory(
            self, "出力フォルダを選択", self.output_dir_edit.text())
        if folder:
            self.output_dir_edit.setText(folder)
            self._validate_and_fix_dirs()

    def _validate_and_fix_dirs(self):
        new_in, new_out, conflict = self._check_overlap_and_fix(
            self.input_dir_edit.text(), self.output_dir_edit.text())
        if conflict:
            self.input_dir_edit.setText(new_in)
            self.output_dir_edit.setText(new_out)
            self.log(f"入出力フォルダ重なり → リセット 入力:{new_in} 出力:{new_out}")
            QMessageBox.warning(
                self, "入出力フォルダの重なり",
                "入力/出力フォルダが同一または内包関係にあるためデフォルトに戻しました。")

    @staticmethod
    def _paths_overlap(a, b):
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
            return DEFAULT_INPUT_DIR, self._default_output_dir, True
        return input_dir, output_dir, False

    # ==================================================================
    #  CSV パス選択
    # ==================================================================

    def _choose_csv_path(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "CSV 保存先",
            self.output_dir_edit.text() or os.getcwd(),
            "CSV files (*.csv);;All files (*.*)")
        if path:
            self.csv_path_edit.setText(path)

    # ==================================================================
    #  ログ・進捗・統計（Signal 経由でスレッド安全）
    # ==================================================================

    def log(self, msg):
        self.log_text.append(msg)

    def update_progress(self, current, total):
        if total <= 0:
            self.progress_bar.setValue(100)
        else:
            self.progress_bar.setValue(int(current / total * 100))

    def update_stats(self, orig_total, out_total, saved, saved_pct):
        self.stats_label.setText(
            f"統計: 元合計={human_readable(orig_total)}, "
            f"出力合計={human_readable(out_total)}, "
            f"削減={human_readable(saved)} ({saved_pct:.1f}%)")

    # ==================================================================
    #  圧縮開始
    # ==================================================================

    def start_compress(self):
        input_ = self.input_dir_edit.text().strip()
        output_ = self.output_dir_edit.text().strip()

        # 入出力フォルダ重なりチェック
        fixed_in, fixed_out, conflict = self._check_overlap_and_fix(input_, output_)
        if conflict:
            self.input_dir_edit.setText(fixed_in)
            self.output_dir_edit.setText(fixed_out)
            input_, output_ = fixed_in, fixed_out
            self.log(f"入出力フォルダ重なり → リセット 入力:{fixed_in} 出力:{fixed_out}")
            QMessageBox.warning(
                self, "入出力フォルダの重なり",
                f"デフォルトに戻しました。\n"
                f"入力: {DEFAULT_INPUT_DIR}\n出力: {self._default_output_dir}")

        if not input_ or not output_:
            QMessageBox.critical(self, "エラー", "両方のフォルダを選択してください")
            return
        os.makedirs(output_, exist_ok=True)

        # ── リサイズ設定構築 ──
        resize_config = False
        if self.resize_enable_cb.isChecked():
            if self.resize_long_rb.isChecked():
                try:
                    r_le = max(0, int(self.long_edge_combo.currentText().strip()))
                except Exception:
                    r_le = 0
                if r_le > 0:
                    resize_config = {
                        'enabled': True, 'mode': 'long_edge',
                        'long_edge': r_le, 'keep_aspect': True}
            else:
                r_w = self._to_non_negative_int(self.resize_w_edit.text())
                r_h = self._to_non_negative_int(self.resize_h_edit.text())
                if r_w > 0 or r_h > 0:
                    resize_config = {
                        'enabled': True, 'mode': 'manual',
                        'width': r_w, 'height': r_h,
                        'keep_aspect': self.resize_aspect_cb.isChecked()}

        # ── 可逆オプション構築 ──
        # ネイティブと GS で共通の変数をマージ
        native_ll_cbs = self._native_ll_cbs
        gs_ll_cbs = self._gs_ll_cbs

        engine = self._pdf_engine
        if engine == 'native':
            lossless_opts = {k: cb.isChecked() for k, cb in native_ll_cbs.items()}
            mode = self._pdf_mode
            pdf_lossless_options = lossless_opts if mode in ('lossless', 'both') else None
        else:
            lossless_opts = {k: cb.isChecked() for k, cb in gs_ll_cbs.items()}
            pdf_lossless_options = lossless_opts if self.gs_use_lossless_cb.isChecked() else None

        # ── ログタブに切り替え ──
        self.tabs.setCurrentIndex(1)

        # UI リセット
        self.log_text.clear()
        self.progress_bar.setValue(0)
        self.stats_label.setText("統計: 処理中...")

        # ── ログ出力 ──
        self.log(f"圧縮開始: 入力={input_}")
        self.log(f"出力先: {output_}")
        if engine == 'native':
            self.log(
                f"PDF: ネイティブ モード={self._pdf_mode}, "
                f"DPI={self.dpi_slider.value()}, "
                f"JPEG品質={self.jpeg_q_slider.value()}, "
                f"PNG→JPEG={self.png_to_jpeg_cb.isChecked()}")
        else:
            preset = self._gs_preset
            if preset == 'custom':
                self.log(
                    f"PDF: GhostScript カスタムDPI={self.gs_dpi_slider.value()}, "
                    f"pikepdf併用={self.gs_use_lossless_cb.isChecked()}")
            else:
                self.log(
                    f"PDF: GhostScript プリセット={preset}, "
                    f"pikepdf併用={self.gs_use_lossless_cb.isChecked()}")
        self.log(
            f"画像: JPG={self.jpg_slider.value()}, PNG={self.png_slider.value()}, "
            f"pngquant={self.pngquant_cb.isChecked()}")
        if resize_config:
            self.log(f"リサイズ: {resize_config}")

        # ── ワーカースレッド開始 ──
        r_w = self._to_non_negative_int(self.resize_w_edit.text())
        r_h = self._to_non_negative_int(self.resize_h_edit.text())

        kwargs = {
            'input_dir': input_,
            'output_dir': output_,
            'jpg_quality': self.jpg_slider.value(),
            'png_quality': self.png_slider.value(),
            'use_pngquant': self.pngquant_cb.isChecked(),
            # log_func, progress_func, stats_func は Worker.run 内で設定
            'log_func': None,
            'progress_func': None,
            'stats_func': None,
            'pdf_engine': engine,
            'pdf_mode': self._pdf_mode,
            'pdf_dpi': self.dpi_slider.value(),
            'pdf_jpeg_quality': self.jpeg_q_slider.value(),
            'pdf_png_to_jpeg': self.png_to_jpeg_cb.isChecked(),
            'pdf_lossless_options': pdf_lossless_options,
            'gs_preset': self._gs_preset,
            'gs_custom_dpi': (self.gs_dpi_slider.value()
                              if self._gs_preset == 'custom' else None),
            'resize_enabled': resize_config,
            'resize_width': r_w,
            'resize_height': r_h,
            'csv_enable': self.csv_enable_cb.isChecked(),
            'csv_path': self.csv_path_edit.text().strip() or None,
            'extract_zip': self.extract_zip_cb.isChecked(),
        }

        worker = CompressWorker(kwargs, parent=self)
        worker.log_signal.connect(self.log)
        worker.progress_signal.connect(self.update_progress)
        worker.stats_signal.connect(self.update_stats)
        worker.finished_signal.connect(lambda: None)
        self._workers.append(worker)
        worker.start()

    # ==================================================================
    #  クリーンアップ
    # ==================================================================

    def cleanup_input(self):
        input_ = self.input_dir_edit.text().strip()
        if not input_ or not os.path.exists(input_):
            QMessageBox.critical(self, "エラー", "入力フォルダが未指定、または存在しません")
            return
        count = count_target_files(input_, INPUT_DIR_CLEANUP_EXTENSIONS)
        exts = ', '.join(sorted(INPUT_DIR_CLEANUP_EXTENSIONS))
        play_sound(os.path.join(SOUNDS_DIR, 'warning.wav'))
        reply = QMessageBox.question(
            self, "クリーンアップ確認",
            f"入力フォルダ内の対象ファイルを削除しますか？\n\n"
            f"【対象拡張子】\n{exts}\n\n"
            f"【削除対象ファイル数】\n約 {count} ファイル\n\n"
            f"サブフォルダ含め削除されます。取り消し不可。")
        if reply == QMessageBox.Yes:
            self.log(f"入力フォルダクリーンアップ開始（{exts}）…")
            w = CleanupWorker(input_, "入力フォルダ", INPUT_DIR_CLEANUP_EXTENSIONS, self)
            w.log_signal.connect(self.log)
            self._workers.append(w)
            w.start()

    def cleanup_output(self):
        output_ = self.output_dir_edit.text().strip()
        if not output_ or not os.path.exists(output_):
            QMessageBox.critical(self, "エラー", "出力フォルダが未指定、または存在しません")
            return
        count = count_target_files(output_, OUTPUT_DIR_CLEANUP_EXTENSIONS)
        exts = ', '.join(sorted(OUTPUT_DIR_CLEANUP_EXTENSIONS))
        play_sound(os.path.join(SOUNDS_DIR, 'warning.wav'))
        reply = QMessageBox.question(
            self, "クリーンアップ確認",
            f"出力フォルダ内の対象ファイルを削除しますか？\n\n"
            f"【対象拡張子】\n{exts}\n\n"
            f"【削除対象ファイル数】\n約 {count} ファイル\n\n"
            f"サブフォルダ含め削除されます。取り消し不可。")
        if reply == QMessageBox.Yes:
            self.log(f"出力フォルダクリーンアップ開始（{exts}）…")
            w = CleanupWorker(output_, "出力フォルダ", OUTPUT_DIR_CLEANUP_EXTENSIONS, self)
            w.log_signal.connect(self.log)
            self._workers.append(w)
            w.start()

    # ==================================================================
    #  終了
    # ==================================================================

    def on_exit(self):
        alive = any(w.isRunning() for w in self._workers)
        if alive:
            reply = QMessageBox.question(
                self, "終了確認", "処理中のスレッドがあります。終了しますか？")
            if reply != QMessageBox.Yes:
                return
        self.close()

    def closeEvent(self, event):
        alive = any(w.isRunning() for w in self._workers)
        if alive:
            reply = QMessageBox.question(
                self, "終了確認", "処理中のスレッドがあります。終了しますか？")
            if reply != QMessageBox.Yes:
                event.ignore()
                return
        event.accept()

    # ==================================================================
    #  ヘルパー
    # ==================================================================

    @staticmethod
    def _to_non_negative_int(s: str) -> int:
        try:
            val = int(float(s.strip()))
            return val if val >= 0 else 0
        except Exception:
            return 0
