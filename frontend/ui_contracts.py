from __future__ import annotations

"""frontend の mixin 間で共有する Protocol を定義する。

実体クラス `App` は複数 mixin を合成して構築されるため、各 mixin が必要とする属性を
Protocol で明示しておくと、責務境界と型補完の両方を保ちやすい。
"""

import threading
import tkinter as tk
from tkinter import ttk
from typing import Any, Callable, Protocol

from backend.contracts import CapabilityReport


class CompressionRequestAppProtocol(Protocol):
    """圧縮 request 生成に必要な UI 状態だけを切り出した Protocol。"""

    input_dir: tk.StringVar
    output_dir: tk.StringVar
    jpg_quality: tk.IntVar
    png_quality: tk.IntVar
    use_pngquant: tk.BooleanVar
    pdf_engine: tk.StringVar
    pdf_mode: tk.StringVar
    pdf_dpi: tk.IntVar
    pdf_jpeg_quality: tk.IntVar
    pdf_png_to_jpeg: tk.BooleanVar
    pdf_ll_linearize: tk.BooleanVar
    pdf_ll_object_streams: tk.BooleanVar
    pdf_ll_clean_metadata: tk.BooleanVar
    pdf_ll_recompress_streams: tk.BooleanVar
    pdf_ll_remove_unreferenced: tk.BooleanVar
    gs_preset: tk.StringVar
    gs_custom_dpi: tk.IntVar
    gs_use_lossless: tk.BooleanVar
    resize_enabled: tk.BooleanVar
    resize_mode: tk.StringVar
    resize_width: tk.StringVar
    resize_height: tk.StringVar
    resize_keep_aspect: tk.BooleanVar
    long_edge_value_str: tk.StringVar
    csv_enable: tk.BooleanVar
    csv_path: tk.StringVar
    extract_zip: tk.BooleanVar
    copy_non_target_files: tk.BooleanVar


class DropEventProtocol(Protocol):
    """tkinterdnd2 のイベントから利用する最小属性だけを表す Protocol。"""

    data: str


class TkUiControllerHostProtocol(CompressionRequestAppProtocol, Protocol):
    """controller mixin が依存する `App` 側の属性群。"""

    capabilities: CapabilityReport
    threads: list[threading.Thread]
    default_input_dir: str
    default_output_dir: str
    auto_switch_log_tab: tk.BooleanVar
    status_var: tk.StringVar
    stats_var: tk.StringVar
    pdf_engine_status_var: tk.StringVar
    notebook: ttk.Notebook
    log_tab: ttk.Frame
    native_rb: ttk.Radiobutton
    gs_rb: ttk.Radiobutton
    native_frame: ttk.Frame
    gs_frame: ttk.Frame
    _native_lossy_widgets: list[tk.Misc]
    dpi_scale: tk.Scale
    jpeg_q_scale: tk.Scale
    jpeg_note_label: ttk.Label
    _native_lossless_widgets: list[ttk.Checkbutton]
    _gs_custom_dpi_widgets: list[tk.Misc]
    _gs_lossless_widgets: list[ttk.Checkbutton]
    resize_width_entry: ttk.Entry
    resize_height_entry: ttk.Entry
    resize_keep_aspect_chk: ttk.Checkbutton
    resize_mode_manual_rb: ttk.Radiobutton
    resize_mode_long_rb: ttk.Radiobutton
    long_edge_combo: ttk.Combobox
    progress: ttk.Progressbar
    log_text: tk.Text
    tk: Any

    def after(self, ms: int, func: Callable[[], object] | None = None, *args: object) -> str | None:
        ...

    def update_idletasks(self) -> None:
        ...

    def destroy(self) -> None:
        ...