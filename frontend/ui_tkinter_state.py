from __future__ import annotations

"""Tkinter の状態変数を初期化する mixin。

Tk 変数の宣言を 1 箇所へ集めることで、view と controller の両方が同じ状態名を前提に
動けるようにする。初期値の責務をここへ寄せ、widget 生成側で既定値を重複定義しない。
"""

import tkinter as tk

from backend.settings import (
    GS_DEFAULT_PRESET,
    PDF_LOSSLESS_OPTIONS_DEFAULT,
    PDF_LOSSY_DPI_DEFAULT,
    PDF_LOSSY_JPEG_QUALITY_DEFAULT,
    PDF_LOSSY_PNG_QUALITY_DEFAULT,
)
from frontend.settings import (
    APP_SETTINGS_DEFAULTS,
    COPY_NON_TARGET_FILES_DEFAULT,
    DEBUG_MODE_DEFAULT,
)


class TkUiStateMixin:
    default_input_dir: str
    default_output_dir: str
    app_settings: dict[str, bool]

    def initialize_ui_state(self) -> None:
        """画面全体で共有する Tk 変数を用途別に初期化する。

        アプリ設定 JSON の永続値を取り込みつつ、backend 既定値と frontend 既定値を 1 回で
        結合する初期化ポイントでもある。
        """
        app_settings = dict(APP_SETTINGS_DEFAULTS)
        app_settings.update(getattr(self, 'app_settings', {}))

        # 入出力フォルダ関連。
        self.input_dir: tk.StringVar = tk.StringVar(value=self.default_input_dir)
        self.output_dir: tk.StringVar = tk.StringVar(value=self.default_output_dir)

        # PDF エンジンと非可逆設定。
        self.pdf_engine: tk.StringVar = tk.StringVar(value='native')
        self.pdf_mode: tk.StringVar = tk.StringVar(value='both')
        self.pdf_dpi: tk.IntVar = tk.IntVar(value=PDF_LOSSY_DPI_DEFAULT)
        self.pdf_jpeg_quality: tk.IntVar = tk.IntVar(value=PDF_LOSSY_JPEG_QUALITY_DEFAULT)
        self.pdf_png_quality: tk.IntVar = tk.IntVar(value=PDF_LOSSY_PNG_QUALITY_DEFAULT)

        # pikepdf の可逆最適化オプション。
        defaults = PDF_LOSSLESS_OPTIONS_DEFAULT
        self.pdf_ll_linearize: tk.BooleanVar = tk.BooleanVar(value=defaults['linearize'])
        self.pdf_ll_object_streams: tk.BooleanVar = tk.BooleanVar(value=defaults['object_streams'])
        self.pdf_ll_clean_metadata: tk.BooleanVar = tk.BooleanVar(value=defaults['clean_metadata'])
        self.pdf_ll_recompress_streams: tk.BooleanVar = tk.BooleanVar(value=defaults['recompress_streams'])
        self.pdf_ll_remove_unreferenced: tk.BooleanVar = tk.BooleanVar(value=defaults['remove_unreferenced'])

        self.gs_preset: tk.StringVar = tk.StringVar(value=GS_DEFAULT_PRESET)
        self.gs_custom_dpi: tk.IntVar = tk.IntVar(value=PDF_LOSSY_DPI_DEFAULT)
        self.gs_use_lossless: tk.BooleanVar = tk.BooleanVar(value=True)

        # 画像圧縮設定。
        self.jpg_quality: tk.IntVar = tk.IntVar(value=70)
        self.png_quality: tk.IntVar = tk.IntVar(value=70)
        self.use_pngquant: tk.BooleanVar = tk.BooleanVar(value=True)

        # リサイズ設定。
        self.resize_enabled: tk.BooleanVar = tk.BooleanVar(value=False)
        self.resize_width: tk.StringVar = tk.StringVar(value='0')
        self.resize_height: tk.StringVar = tk.StringVar(value='0')
        self.resize_keep_aspect: tk.BooleanVar = tk.BooleanVar(value=True)
        self.resize_mode: tk.StringVar = tk.StringVar(value='manual')
        self.long_edge_value_str: tk.StringVar = tk.StringVar(value='1024')

        # 出力・ログまわりの補助設定。
        self.csv_enable: tk.BooleanVar = tk.BooleanVar(value=True)
        self.csv_path: tk.StringVar = tk.StringVar(value='')
        self.extract_zip: tk.BooleanVar = tk.BooleanVar(value=True)
        self.debug_mode: tk.BooleanVar = tk.BooleanVar(value=DEBUG_MODE_DEFAULT)
        self.copy_non_target_files: tk.BooleanVar = tk.BooleanVar(value=COPY_NON_TARGET_FILES_DEFAULT)
        self.auto_switch_log_tab: tk.BooleanVar = tk.BooleanVar(value=True)
        self.play_startup_sound: tk.BooleanVar = tk.BooleanVar(value=app_settings['play_startup_sound'])
        self.play_cleanup_sound: tk.BooleanVar = tk.BooleanVar(value=app_settings['play_cleanup_sound'])

        # 画面下部の状態表示。
        self.status_var: tk.StringVar = tk.StringVar(value='待機中')
