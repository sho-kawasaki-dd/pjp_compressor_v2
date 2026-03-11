from __future__ import annotations

import tkinter as tk

from shared.configs import (
    COPY_NON_TARGET_FILES_DEFAULT,
    GS_DEFAULT_PRESET,
    PDF_LOSSLESS_OPTIONS_DEFAULT,
    PDF_LOSSY_DPI_DEFAULT,
    PDF_LOSSY_JPEG_QUALITY_DEFAULT,
    PDF_LOSSY_PNG_TO_JPEG_DEFAULT,
)


class TkUiStateMixin:
    default_input_dir: str
    default_output_dir: str

    def initialize_ui_state(self) -> None:
        self.input_dir: tk.StringVar = tk.StringVar(value=self.default_input_dir)
        self.output_dir: tk.StringVar = tk.StringVar(value=self.default_output_dir)

        self.pdf_engine: tk.StringVar = tk.StringVar(value='native')
        self.pdf_mode: tk.StringVar = tk.StringVar(value='both')
        self.pdf_dpi: tk.IntVar = tk.IntVar(value=PDF_LOSSY_DPI_DEFAULT)
        self.pdf_jpeg_quality: tk.IntVar = tk.IntVar(value=PDF_LOSSY_JPEG_QUALITY_DEFAULT)
        self.pdf_png_to_jpeg: tk.BooleanVar = tk.BooleanVar(value=PDF_LOSSY_PNG_TO_JPEG_DEFAULT)

        defaults = PDF_LOSSLESS_OPTIONS_DEFAULT
        self.pdf_ll_linearize: tk.BooleanVar = tk.BooleanVar(value=defaults['linearize'])
        self.pdf_ll_object_streams: tk.BooleanVar = tk.BooleanVar(value=defaults['object_streams'])
        self.pdf_ll_clean_metadata: tk.BooleanVar = tk.BooleanVar(value=defaults['clean_metadata'])
        self.pdf_ll_recompress_streams: tk.BooleanVar = tk.BooleanVar(value=defaults['recompress_streams'])
        self.pdf_ll_remove_unreferenced: tk.BooleanVar = tk.BooleanVar(value=defaults['remove_unreferenced'])

        self.gs_preset: tk.StringVar = tk.StringVar(value=GS_DEFAULT_PRESET)
        self.gs_custom_dpi: tk.IntVar = tk.IntVar(value=PDF_LOSSY_DPI_DEFAULT)
        self.gs_use_lossless: tk.BooleanVar = tk.BooleanVar(value=True)

        self.jpg_quality: tk.IntVar = tk.IntVar(value=70)
        self.png_quality: tk.IntVar = tk.IntVar(value=70)
        self.use_pngquant: tk.BooleanVar = tk.BooleanVar(value=True)

        self.resize_enabled: tk.BooleanVar = tk.BooleanVar(value=False)
        self.resize_width: tk.StringVar = tk.StringVar(value='0')
        self.resize_height: tk.StringVar = tk.StringVar(value='0')
        self.resize_keep_aspect: tk.BooleanVar = tk.BooleanVar(value=True)
        self.resize_mode: tk.StringVar = tk.StringVar(value='manual')
        self.long_edge_value_str: tk.StringVar = tk.StringVar(value='1024')

        self.csv_enable: tk.BooleanVar = tk.BooleanVar(value=True)
        self.csv_path: tk.StringVar = tk.StringVar(value='')
        self.extract_zip: tk.BooleanVar = tk.BooleanVar(value=True)
        self.copy_non_target_files: tk.BooleanVar = tk.BooleanVar(value=COPY_NON_TARGET_FILES_DEFAULT)
        self.auto_switch_log_tab: tk.BooleanVar = tk.BooleanVar(value=True)

        self.status_var: tk.StringVar = tk.StringVar(value='待機中')
