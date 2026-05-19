from __future__ import annotations

"""Tkinter 画面のレイアウト構築を担当する mixin。

この mixin は widget の生成順序とレイアウト構造だけを持ち、イベント判断や backend
 連携は controller へ委ねる。表示ロジックをここへ閉じ込めることで、controller が
 「どの widget をどう並べるか」まで知る必要をなくしている。
"""

import tkinter as tk
from tkinter import ttk
from typing import Callable, Protocol, cast

from backend.contracts import CapabilityReport
from frontend.i18n import t
from frontend.settings import LONG_EDGE_PRESETS, PDF_LOSSY_DPI_RANGE


class _DndEntryProtocol(Protocol):
    """D&D 対応 Entry が持つ最小 API を表す Protocol。"""

    def drop_target_register(self, *dnd_types: object) -> object:
        ...

    def dnd_bind(self, sequence: str, func: Callable[..., object]) -> object:
        ...


class TkUiViewMixin:
    dnd_available: bool
    DND_FILES: str
    capabilities: CapabilityReport

    input_dir: tk.StringVar
    output_dir: tk.StringVar
    pdf_engine: tk.StringVar
    pdf_mode: tk.StringVar
    pdf_dpi: tk.IntVar
    pdf_jpeg_quality: tk.IntVar
    pdf_png_quality: tk.IntVar
    gs_preset: tk.StringVar
    gs_custom_dpi: tk.IntVar
    gs_use_lossless: tk.BooleanVar
    jpg_quality: tk.IntVar
    png_quality: tk.IntVar
    use_pngquant: tk.BooleanVar
    resize_enabled: tk.BooleanVar
    resize_mode: tk.StringVar
    resize_width: tk.StringVar
    resize_height: tk.StringVar
    resize_keep_aspect: tk.BooleanVar
    long_edge_value_str: tk.StringVar
    csv_enable: tk.BooleanVar
    csv_path: tk.StringVar
    extract_zip: tk.BooleanVar
    zip_output_enabled: tk.BooleanVar
    copy_non_target_files: tk.BooleanVar
    auto_switch_log_tab: tk.BooleanVar
    play_startup_sound: tk.BooleanVar
    play_cleanup_sound: tk.BooleanVar
    status_var: tk.StringVar
    pdf_ll_linearize: tk.BooleanVar
    pdf_ll_object_streams: tk.BooleanVar
    pdf_ll_clean_metadata: tk.BooleanVar
    pdf_ll_recompress_streams: tk.BooleanVar
    pdf_ll_remove_unreferenced: tk.BooleanVar

    choose_input: Callable[[], None]
    cleanup_input: Callable[[], None]
    choose_output: Callable[[], None]
    cleanup_output: Callable[[], None]
    _on_drop_input: Callable[[object], None]
    _update_pdf_controls: Callable[[], None]
    _update_resize_controls: Callable[[], None]
    _update_zip_output_controls: Callable[[], None]
    _save_app_settings: Callable[[], bool]
    _choose_csv_path: Callable[[], None]
    start_compress: Callable[[], None]
    on_exit: Callable[[], None]

    main_canvas: tk.Canvas
    main_scrollbar: ttk.Scrollbar
    main_container: ttk.Frame
    main_container_window: int
    input_entry: ttk.Entry
    notebook: ttk.Notebook
    settings_tab: ttk.Frame
    log_tab: ttk.Frame
    app_settings_tab: ttk.Frame
    native_rb: ttk.Radiobutton
    gs_rb: ttk.Radiobutton
    pdf_engine_status_var: tk.StringVar
    native_frame: ttk.Frame
    gs_frame: ttk.Frame
    lossy_lf: ttk.LabelFrame
    native_lossless_lf: ttk.LabelFrame
    gs_lossless_lf: ttk.LabelFrame
    _native_lossy_widgets: list[tk.Widget]
    _native_png_quality_widgets: list[tk.Widget]
    dpi_val_label: ttk.Label
    dpi_scale: tk.Scale
    jpeg_q_val_label: ttk.Label
    jpeg_q_scale: tk.Scale
    pdf_png_q_val_label: ttk.Label
    pdf_png_q_scale: tk.Scale
    jpeg_note_label: ttk.Label
    pdf_png_fallback_note_label: ttk.Label
    _native_ll_frame: ttk.Frame
    _native_lossless_widgets: list[ttk.Checkbutton]
    _gs_preset_widgets: list[ttk.Radiobutton]
    gs_dpi_val_label: ttk.Label
    gs_dpi_scale: tk.Scale
    _gs_custom_dpi_widgets: list[tk.Widget]
    gs_use_lossless_cb: ttk.Checkbutton
    _gs_ll_frame: ttk.Frame
    _gs_lossless_widgets: list[ttk.Checkbutton]
    jpg_quality_label: ttk.Label
    png_quality_label: ttk.Label
    pngquant_check: ttk.Checkbutton
    resize_mode_manual_rb: ttk.Radiobutton
    resize_width_entry: ttk.Entry
    resize_height_entry: ttk.Entry
    resize_keep_aspect_chk: ttk.Checkbutton
    resize_mode_long_rb: ttk.Radiobutton
    long_edge_combo: ttk.Combobox
    zip_output_check: ttk.Checkbutton
    stats_var: tk.StringVar
    progress: ttk.Progressbar
    log_text: tk.Text

    def build_layout(self) -> None:
        """メイン画面全体を上から順に組み立てる。"""
        self._build_root_scroll_container()
        self._build_folder_section()
        self._build_notebook()
        self._build_action_buttons()
        self._bind_root_mousewheel()

    def _as_tk_master(self) -> tk.Misc:
        """複数継承された `self` を Tk の親 widget として扱うための型補助。"""
        return cast(tk.Misc, self)

    def _build_root_scroll_container(self):
        """縦長レイアウトでも扱いやすいスクロール可能コンテナを作る。

        Notebook と複数の設定セクションを 1 画面へ収めるため、root 直下を Canvas + Frame
        構成にして全体スクロールを実現する。個々の子 widget へ個別スクロールを持たせる
        より、状態管理が単純になる。
        """
        root_frame = ttk.Frame(self._as_tk_master())
        root_frame.pack(fill='both', expand=True)

        self.main_canvas = tk.Canvas(root_frame, highlightthickness=0)
        self.main_canvas.pack(side='left', fill='both', expand=True)

        self.main_scrollbar = ttk.Scrollbar(root_frame, orient='vertical', command=self.main_canvas.yview)
        self.main_scrollbar.pack(side='right', fill='y')
        self.main_canvas.configure(yscrollcommand=self.main_scrollbar.set)

        self.main_container = ttk.Frame(self.main_canvas)
        self.main_container_window = self.main_canvas.create_window((0, 0), window=self.main_container, anchor='nw')

        self.main_container.bind('<Configure>', self._on_main_container_configure)
        self.main_canvas.bind('<Configure>', self._on_main_canvas_configure)

    def _on_main_container_configure(self, _event):
        """内部フレームの実サイズ変化に追随して scrollregion を更新する。"""
        self.main_canvas.configure(scrollregion=self.main_canvas.bbox('all'))

    def _on_main_canvas_configure(self, event):
        """Canvas 幅に合わせて内部コンテナ幅を同期し、横方向の崩れを防ぐ。"""
        self.main_canvas.itemconfigure(self.main_container_window, width=event.width)

    def _bind_root_mousewheel(self):
        """どの子 widget 上にいても画面全体をスクロールできるようにする。"""
        self._as_tk_master().bind_all('<MouseWheel>', self._on_root_mousewheel, add='+')

    def _on_root_mousewheel(self, event):
        """ルート全体のマウスホイールをスクロールコンテナへ中継する。

        ログ Text は独自スクロールを持つため、そこだけは root 側のホイール処理から除外し、
        画面全体スクロールと干渉しないようにする。
        """
        # Keep Text widget wheel behavior unchanged (log area scrolls itself).
        target = self._as_tk_master().winfo_containing(event.x_root, event.y_root)
        if target is not None and self._is_inside_widget(target, self.log_text):
            return

        delta = event.delta
        if delta == 0:
            return
        steps = int(-delta / 120)
        if steps == 0:
            steps = -1 if delta > 0 else 1
        self.main_canvas.yview_scroll(steps, 'units')

    def _is_inside_widget(self, child, parent) -> bool:
        """widget 親子関係をたどって、対象 widget 配下かどうかを判定する。"""
        widget = child
        while widget is not None:
            if widget == parent:
                return True
            try:
                parent_name = widget.winfo_parent()
            except Exception:
                return False
            if not parent_name:
                return False
            try:
                widget = widget.nametowidget(parent_name)
            except Exception:
                return False
        return False

    def _build_folder_section(self):
        """入出力フォルダ選択と D&D 導線をまとめて配置する。"""
        folder_frame = ttk.Frame(self.main_container)
        folder_frame.pack(fill='x', padx=14, pady=(12, 8))

        row_in = ttk.Frame(folder_frame)
        row_in.pack(fill='x', pady=4)
        ttk.Label(row_in, text=t('label_input_folder')).pack(side='left')
        self.input_entry = ttk.Entry(row_in, textvariable=self.input_dir, width=45)
        self.input_entry.pack(side='left', padx=8)
        ttk.Button(row_in, text=t('btn_select'), command=self.choose_input).pack(side='left', padx=4)
        tk.Button(row_in, text=t('btn_cleanup'), command=self.cleanup_input, bg='#d0f6ff').pack(side='left', padx=4)

        if self.dnd_available:
            dnd_input_entry = cast(_DndEntryProtocol, self.input_entry)
            dnd_input_entry.drop_target_register(self.DND_FILES)
            dnd_input_entry.dnd_bind('<<Drop>>', self._on_drop_input)
            ttk.Label(row_in, text=t('folder_dnd_available'), foreground='gray').pack(side='left', padx=6)
        else:
            ttk.Label(row_in, text=t('folder_dnd_unavailable'), foreground='gray').pack(side='left', padx=6)

        row_out = ttk.Frame(folder_frame)
        row_out.pack(fill='x', pady=4)
        ttk.Label(row_out, text=t('label_output_folder')).pack(side='left')
        ttk.Entry(row_out, textvariable=self.output_dir, width=45).pack(side='left', padx=8)
        ttk.Button(row_out, text=t('btn_select'), command=self.choose_output).pack(side='left', padx=4)
        tk.Button(row_out, text=t('btn_cleanup'), command=self.cleanup_output, bg='#ffcaca').pack(side='left', padx=4)

    def _build_notebook(self):
        """設定タブ、アプリ設定タブ、ログタブを作成する。"""
        self.notebook = ttk.Notebook(self.main_container)
        self.notebook.pack(fill='both', expand=True, padx=14, pady=8)

        self.settings_tab = ttk.Frame(self.notebook)
        self.app_settings_tab = ttk.Frame(self.notebook)
        self.log_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.settings_tab, text=f' {t("tab_compression")} ')
        self.notebook.add(self.app_settings_tab, text=f' {t("tab_settings")} ')
        self.notebook.add(self.log_tab, text=f' {t("tab_log")} ')

        self._build_settings_tab()
        self._build_app_settings_tab()
        self._build_log_tab()

    def _build_app_settings_tab(self):
        """アプリ全体の動作設定を構築する。"""
        app_outer = tk.LabelFrame(
            self.app_settings_tab,
            text=f' {t("section_app_settings")} ',
            bg='#f8f7ef',
            fg='black',
            bd=1,
            relief='solid',
        )
        app_outer.pack(fill='x', padx=8, pady=(8, 5))
        app_container = ttk.Frame(app_outer)
        app_container.pack(fill='x', padx=8, pady=(5, 8))

        startup_row = ttk.Frame(app_container)
        startup_row.pack(fill='x', padx=5, pady=4)
        ttk.Checkbutton(
            startup_row,
            text=t('app_settings_startup_sound'),
            variable=self.play_startup_sound,
            command=self._save_app_settings,
        ).pack(side='left')
        ttk.Label(
            startup_row,
            text=t('app_settings_startup_sound_note'),
            foreground='gray',
        ).pack(side='left', padx=(8, 0))

        cleanup_row = ttk.Frame(app_container)
        cleanup_row.pack(fill='x', padx=5, pady=4)
        ttk.Checkbutton(
            cleanup_row,
            text=t('app_settings_cleanup_sound'),
            variable=self.play_cleanup_sound,
            command=self._save_app_settings,
        ).pack(side='left')
        ttk.Label(
            cleanup_row,
            text=t('app_settings_cleanup_sound_note'),
            foreground='gray',
        ).pack(side='left', padx=(8, 0))

    def _build_settings_tab(self):
        """設定タブ内に PDF・画像・出力設定の 3 セクションを並べる。"""
        pdf_outer = tk.LabelFrame(
            self.settings_tab,
            text=f' {t("section_pdf_settings")} ',
            bg='#fff1f1',
            fg='black',
            bd=1,
            relief='solid',
        )
        pdf_outer.pack(fill='x', padx=8, pady=(8, 5))
        pdf_container = ttk.Frame(pdf_outer)
        pdf_container.pack(fill='x', padx=8, pady=(5, 8))
        self._build_pdf_section(pdf_container)

        image_outer = tk.LabelFrame(
            self.settings_tab,
            text=f' {t("section_image_settings")} ',
            bg='#f1f6ff',
            fg='black',
            bd=1,
            relief='solid',
        )
        image_outer.pack(fill='x', padx=8, pady=5)
        image_container = ttk.Frame(image_outer)
        image_container.pack(fill='x', padx=8, pady=(5, 8))
        self._build_image_section(image_container)
        self._build_resize_section(image_container)
        self._build_output_section(self.settings_tab)

    def _build_pdf_section(self, parent):
        """PDF エンジン選択とエンジン別詳細設定を構築する。

        native/GS の詳細フレームはここで両方生成しておき、実際に見せる側を controller が
        pack/forget で切り替える。毎回再生成しないことで、選択状態を保持しやすくする。
        """
        engine_frame = ttk.Frame(parent)
        engine_frame.pack(fill='x', padx=8, pady=(6, 4))

        ttk.Label(engine_frame, text=t('label_engine')).pack(side='left')
        self.native_rb = ttk.Radiobutton(
            engine_frame,
            text=t('engine_native'),
            variable=self.pdf_engine,
            value='native',
            command=self._update_pdf_controls,
        )
        self.native_rb.pack(side='left', padx=(10, 5))
        self.gs_rb = ttk.Radiobutton(
            engine_frame,
            text=t('engine_ghostscript'),
            variable=self.pdf_engine,
            value='gs',
            command=self._update_pdf_controls,
        )
        self.gs_rb.pack(side='left', padx=5)

        self.pdf_engine_status_var = tk.StringVar(value=t('engine_detecting'))
        ttk.Label(engine_frame, textvariable=self.pdf_engine_status_var, foreground='purple').pack(side='left', padx=(10, 0))

        self.native_frame = ttk.Frame(parent)
        self._build_native_controls(self.native_frame)

        self.gs_frame = ttk.Frame(parent)
        self._build_gs_controls(self.gs_frame)

    def _build_native_controls(self, parent):
        """PyMuPDF + pikepdf を使うネイティブ圧縮設定を構築する。

        controller が一括で enable/disable しやすいよう、非可逆系 widget と PNG 品質用
        widget をリストへ収集しながら生成する。
        """
        mode_frame = ttk.Frame(parent)
        mode_frame.pack(fill='x', padx=5, pady=2)
        ttk.Label(mode_frame, text=t('label_mode')).pack(side='left')
        for value in ('lossy', 'lossless', 'both'):
            ttk.Radiobutton(
                mode_frame,
                text=t(f'pdf_mode.{value}'),
                variable=self.pdf_mode,
                value=value,
                command=self._update_pdf_controls,
            ).pack(side='left', padx=(10, 3))

        self.lossy_lf = ttk.LabelFrame(parent, text=t('section_pdf_lossy_options'))
        self.lossy_lf.pack(fill='x', padx=8, pady=4)
        self._native_lossy_widgets = []
        self._native_png_quality_widgets = []

        dpi_row = ttk.Frame(self.lossy_lf)
        dpi_row.pack(fill='x', padx=5, pady=2)
        dpi_label = ttk.Label(dpi_row, text=t('label_dpi'))
        dpi_label.pack(side='left')
        self._native_lossy_widgets.append(dpi_label)
        self.dpi_val_label = ttk.Label(dpi_row, text=str(self.pdf_dpi.get()), width=4)
        self.dpi_val_label.pack(side='left', padx=5)
        self._native_lossy_widgets.append(self.dpi_val_label)
        self.dpi_scale = tk.Scale(
            dpi_row,
            from_=PDF_LOSSY_DPI_RANGE[0],
            to=PDF_LOSSY_DPI_RANGE[1],
            orient='horizontal',
            variable=self.pdf_dpi,
            command=lambda v: self.dpi_val_label.config(text=str(int(float(v)))),
            length=300,
            showvalue=False,
            resolution=1,
        )
        self.dpi_scale.pack(side='left', padx=5)
        self._native_lossy_widgets.append(self.dpi_scale)

        jpeg_row = ttk.Frame(self.lossy_lf)
        jpeg_row.pack(fill='x', padx=5, pady=2)
        jpeg_label = ttk.Label(jpeg_row, text=t('label_jpeg_quality'))
        jpeg_label.pack(side='left')
        self._native_lossy_widgets.append(jpeg_label)
        self.jpeg_q_val_label = ttk.Label(jpeg_row, text=str(self.pdf_jpeg_quality.get()), width=4)
        self.jpeg_q_val_label.pack(side='left', padx=5)
        self._native_lossy_widgets.append(self.jpeg_q_val_label)
        self.jpeg_q_scale = tk.Scale(
            jpeg_row,
            from_=1,
            to=100,
            orient='horizontal',
            variable=self.pdf_jpeg_quality,
            command=lambda v: self.jpeg_q_val_label.config(text=str(int(float(v)))),
            length=300,
            showvalue=False,
            resolution=1,
        )
        self.jpeg_q_scale.pack(side='left', padx=5)
        self._native_lossy_widgets.append(self.jpeg_q_scale)

        self.jpeg_note_label = ttk.Label(jpeg_row, text=t('note_jpeg_only'), foreground='gray')

        png_row = ttk.Frame(self.lossy_lf)
        png_row.pack(fill='x', padx=5, pady=2)
        pdf_png_label = ttk.Label(png_row, text=t('label_png_quality'))
        pdf_png_label.pack(side='left')
        self._native_lossy_widgets.append(pdf_png_label)
        self._native_png_quality_widgets.append(pdf_png_label)
        self.pdf_png_q_val_label = ttk.Label(png_row, text=str(self.pdf_png_quality.get()), width=4)
        self.pdf_png_q_val_label.pack(side='left', padx=5)
        self._native_lossy_widgets.append(self.pdf_png_q_val_label)
        self._native_png_quality_widgets.append(self.pdf_png_q_val_label)
        self.pdf_png_q_scale = tk.Scale(
            png_row,
            from_=0,
            to=100,
            orient='horizontal',
            variable=self.pdf_png_quality,
            command=lambda v: self.pdf_png_q_val_label.config(text=str(int(float(v)))),
            length=300,
            showvalue=False,
            resolution=1,
        )
        self.pdf_png_q_scale.pack(side='left', padx=5)
        self._native_lossy_widgets.append(self.pdf_png_q_scale)
        self._native_png_quality_widgets.append(self.pdf_png_q_scale)

        source_label = t(f'tool_source.{self.capabilities.pngquant_source}')
        self.pdf_png_method_label = ttk.Label(
            png_row,
            text=t('pdf_png_engine.pngquant', source=source_label) if self.capabilities.pngquant_available else t('pdf_png_engine.pillow', source=source_label),
            foreground='gray',
        )

        self.pdf_png_fallback_note_label = ttk.Label(
            png_row,
            text=t('note_pngquant_fallback'),
            foreground='gray',
        )

        self.native_lossless_lf = ttk.LabelFrame(parent, text=t('section_pdf_lossless_options'))
        self.native_lossless_lf.pack(fill='x', padx=8, pady=4)
        self._native_ll_frame, self._native_lossless_widgets = self._create_lossless_controls(self.native_lossless_lf)
        self._native_ll_frame.pack(fill='x')

    def _build_gs_controls(self, parent):
        """Ghostscript 圧縮と追加の pikepdf 最適化設定を構築する。

        GS 本体の設定と、後段で任意に足す pikepdf 可逆最適化を同じ画面に置くが、意味が
        異なるため controller 側で個別に有効/無効を切り替えられる構造にしている。
        """
        preset_lf = ttk.LabelFrame(parent, text=t('label_preset'))
        preset_lf.pack(fill='x', padx=8, pady=4)
        self._gs_preset_widgets = []

        preset_grid = ttk.Frame(preset_lf)
        preset_grid.pack(fill='x', padx=5, pady=2)
        all_presets = [(key, t(f'gs_preset.{key}')) for key in ('screen', 'ebook', 'printer', 'prepress', 'default')] + [('custom', t('gs_preset.custom'))]
        for idx, (key, label) in enumerate(all_presets):
            display = f'{label}' if key == 'custom' else f'{key}: {label}'
            radio = ttk.Radiobutton(
                preset_grid,
                text=display,
                variable=self.gs_preset,
                value=key,
                command=self._update_pdf_controls,
            )
            row, column = divmod(idx, 2)
            radio.grid(row=row, column=column, sticky='w', padx=(0, 20), pady=2)
            self._gs_preset_widgets.append(radio)

        custom_row = ttk.Frame(parent)
        custom_row.pack(fill='x', padx=12, pady=4)
        custom_label = ttk.Label(custom_row, text=t('label_custom_dpi'))
        custom_label.pack(side='left')
        self.gs_dpi_val_label = ttk.Label(custom_row, text=str(self.gs_custom_dpi.get()), width=4)
        self.gs_dpi_val_label.pack(side='left', padx=5)
        self.gs_dpi_scale = tk.Scale(
            custom_row,
            from_=PDF_LOSSY_DPI_RANGE[0],
            to=PDF_LOSSY_DPI_RANGE[1],
            orient='horizontal',
            variable=self.gs_custom_dpi,
            command=lambda v: self.gs_dpi_val_label.config(text=str(int(float(v)))),
            length=300,
            showvalue=False,
            resolution=1,
        )
        self.gs_dpi_scale.pack(side='left', padx=5)
        self._gs_custom_dpi_widgets = [custom_label, self.gs_dpi_val_label, self.gs_dpi_scale]

        ll_check_row = ttk.Frame(parent)
        ll_check_row.pack(fill='x', padx=12, pady=4)
        self.gs_use_lossless_cb = ttk.Checkbutton(
            ll_check_row,
            text=t('checkbox_pikepdf_lossless'),
            variable=self.gs_use_lossless,
            command=self._update_pdf_controls,
        )
        self.gs_use_lossless_cb.pack(side='left')

        self.gs_lossless_lf = ttk.LabelFrame(parent, text=f'{t("section_pdf_lossless_options")}（pikepdf）')
        self.gs_lossless_lf.pack(fill='x', padx=8, pady=4)
        self._gs_ll_frame, self._gs_lossless_widgets = self._create_lossless_controls(self.gs_lossless_lf)
        self._gs_ll_frame.pack(fill='x')

    def _build_image_section(self, parent):
        """JPEG/PNG の品質と pngquant 利用設定を構築する。

        画像圧縮の設定は PDF 設定と独立しているため、別セクションに分けて「通常画像」と
        「PDF 内画像」の品質ノブを混同しないようにする。
        """
        img_lf = ttk.LabelFrame(parent, text=f' {t("label_image_compression")} ')
        img_lf.pack(fill='x', padx=8, pady=5)

        jpg_row = ttk.Frame(img_lf)
        jpg_row.pack(fill='x', padx=5, pady=2)
        ttk.Label(jpg_row, text=t('label_jpg_quality')).pack(side='left')
        self.jpg_quality_label = ttk.Label(jpg_row, text=str(self.jpg_quality.get()), width=4)
        self.jpg_quality_label.pack(side='left', padx=5)
        tk.Scale(
            jpg_row,
            from_=0,
            to=100,
            orient='horizontal',
            variable=self.jpg_quality,
            command=lambda v: self.jpg_quality_label.config(text=str(int(float(v)))),
            length=300,
            showvalue=False,
        ).pack(side='left')

        png_row = ttk.Frame(img_lf)
        png_row.pack(fill='x', padx=5, pady=2)
        ttk.Label(png_row, text=t('label_png_quality')).pack(side='left')
        self.png_quality_label = ttk.Label(png_row, text=str(self.png_quality.get()), width=4)
        self.png_quality_label.pack(side='left', padx=5)
        tk.Scale(
            png_row,
            from_=0,
            to=100,
            orient='horizontal',
            variable=self.png_quality,
            command=lambda v: self.png_quality_label.config(text=str(int(float(v)))),
            length=300,
            showvalue=False,
        ).pack(side='left')
        self.png_engine_note_label = ttk.Label(
            png_row,
            text=t('image_png_engine.pngquant', source=t(f'tool_source.{self.capabilities.pngquant_source}')) if self.use_pngquant.get() and self.capabilities.pngquant_available else t('image_png_engine.pillow', source=t(f'tool_source.{self.capabilities.pngquant_source}')),
            foreground='gray',
        )
        self.png_engine_note_label.pack(side='left', padx=(8, 0))

        pq_row = ttk.Frame(img_lf)
        pq_row.pack(fill='x', padx=5, pady=2)
        self.pngquant_check = ttk.Checkbutton(
            pq_row,
            text=t('checkbox_pngquant'),
            variable=self.use_pngquant,
            command=self._update_png_engine_labels,
        )
        self.pngquant_check.pack(side='left')
        if not self.capabilities.pngquant_available:
            # 未検出時に UI からも無効化しておくと、実行時フォールバックの理由が分かりやすい。
            self.pngquant_check.config(state='disabled')
            ttk.Label(pq_row, text=t('note_pngquant_unavailable'), foreground='gray').pack(side='left', padx=10)

    def _build_resize_section(self, parent):
        """画像リサイズ設定を手動指定と長辺指定の両方で提供する。

        同じリサイズ機能でも利用者の考え方が異なるため、ピクセル指定と長辺指定の両方を
        並べ、controller 側で今有効な入力だけを残す。
        """
        resize_lf = ttk.LabelFrame(parent, text=f' {t("section_resize_settings")} ')
        resize_lf.pack(fill='x', padx=8, pady=5)

        enable_row = ttk.Frame(resize_lf)
        enable_row.pack(fill='x', padx=5, pady=2)
        ttk.Checkbutton(
            enable_row,
            text=t('checkbox_enable_resize'),
            variable=self.resize_enabled,
            command=self._update_resize_controls,
        ).pack(side='left')

        ctrl_row = ttk.Frame(resize_lf)
        ctrl_row.pack(fill='x', padx=5, pady=2)
        self.resize_mode_manual_rb = ttk.Radiobutton(
            ctrl_row,
            text=t('resize_mode.manual'),
            variable=self.resize_mode,
            value='manual',
            command=self._update_resize_controls,
        )
        self.resize_mode_manual_rb.pack(side='left')
        ttk.Label(ctrl_row, text=t('label_width')).pack(side='left', padx=(10, 2))
        self.resize_width_entry = ttk.Entry(ctrl_row, textvariable=self.resize_width, width=6)
        self.resize_width_entry.pack(side='left')
        ttk.Label(ctrl_row, text=t('label_height')).pack(side='left', padx=(10, 2))
        self.resize_height_entry = ttk.Entry(ctrl_row, textvariable=self.resize_height, width=6)
        self.resize_height_entry.pack(side='left')
        self.resize_keep_aspect_chk = ttk.Checkbutton(ctrl_row, text=t('checkbox_keep_aspect'), variable=self.resize_keep_aspect)
        self.resize_keep_aspect_chk.pack(side='left', padx=(12, 0))

        long_row = ttk.Frame(resize_lf)
        long_row.pack(fill='x', padx=5, pady=2)
        self.resize_mode_long_rb = ttk.Radiobutton(
            long_row,
            text=t('resize_mode.long_edge'),
            variable=self.resize_mode,
            value='long_edge',
            command=self._update_resize_controls,
        )
        self.resize_mode_long_rb.pack(side='left')
        ttk.Label(long_row, text=t('label_long_edge')).pack(side='left', padx=(10, 2))
        self.long_edge_combo = ttk.Combobox(long_row, textvariable=self.long_edge_value_str, values=LONG_EDGE_PRESETS, width=8)
        self.long_edge_combo.pack(side='left')

    def _build_output_section(self, parent):
        """CSV、ZIP 展開、ミラー圧縮などの出力補助設定を構築する。

        これらは圧縮アルゴリズムではなくジョブ全体のふるまいを変える設定なので、
        出力設定として別枠にまとめている。
        """
        out_lf = ttk.LabelFrame(parent, text=f' {t("section_output_settings")} ')
        out_lf.pack(fill='x', padx=8, pady=5)

        csv_row = ttk.Frame(out_lf)
        csv_row.pack(fill='x', padx=5, pady=2)
        ttk.Checkbutton(csv_row, text=t('checkbox_csv_output'), variable=self.csv_enable).pack(side='left')
        ttk.Label(csv_row, text=t('label_csv_path')).pack(side='left', padx=(10, 2))
        ttk.Entry(csv_row, textvariable=self.csv_path, width=35).pack(side='left', padx=5)
        ttk.Button(csv_row, text=t('btn_browse'), command=self._choose_csv_path).pack(side='left', padx=2)

        zip_row = ttk.Frame(out_lf)
        zip_row.pack(fill='x', padx=5, pady=2)
        ttk.Checkbutton(
            zip_row,
            text=t('checkbox_extract_zip'),
            variable=self.extract_zip,
            command=self._update_zip_output_controls,
        ).pack(side='left')

        zip_output_row = ttk.Frame(out_lf)
        zip_output_row.pack(fill='x', padx=5, pady=2)
        self.zip_output_check = ttk.Checkbutton(
            zip_output_row,
            text=t('checkbox_zip_repack'),
            variable=self.zip_output_enabled,
        )
        self.zip_output_check.pack(side='left')

        debug_row = ttk.Frame(out_lf)
        debug_row.pack(fill='x', padx=5, pady=2)
        ttk.Checkbutton(debug_row, text=t('checkbox_debug_output'), variable=self.debug_mode).pack(side='left')

        copy_row = ttk.Frame(out_lf)
        copy_row.pack(fill='x', padx=5, pady=2)
        ttk.Checkbutton(
            copy_row,
            text=t('checkbox_mirror_copy'),
            variable=self.copy_non_target_files,
        ).pack(side='left')

        log_row = ttk.Frame(out_lf)
        log_row.pack(fill='x', padx=5, pady=2)
        ttk.Checkbutton(log_row, text=t('checkbox_auto_switch_log_tab'), variable=self.auto_switch_log_tab).pack(side='left')

    def _build_log_tab(self):
        """進捗バー、統計、ログテキストを備えたログ表示タブを構築する。

        実行中の安心感を出すため、状態、進捗率、詳細ログを 1 タブへ集約する。controller は
        ここに対して文字列や数値を流すだけでよい。
        """
        stats_frame = ttk.Frame(self.log_tab)
        stats_frame.pack(fill='x', padx=14, pady=(12, 8))
        self.stats_var = tk.StringVar(value=t('stats_initial'))
        ttk.Label(stats_frame, textvariable=self.stats_var, foreground='blue', font=('Arial', 10, 'bold')).pack(side='left')

        progress_lf = ttk.LabelFrame(self.log_tab, text=f' {t("progress_label")} ')
        progress_lf.pack(fill='x', padx=14, pady=(0, 8))

        status_row = ttk.Frame(progress_lf)
        status_row.pack(fill='x', padx=10, pady=(8, 4))
        ttk.Label(status_row, text=t('status_label')).pack(side='left')
        ttk.Label(status_row, textvariable=self.status_var, foreground='purple').pack(side='left', padx=(8, 0))

        self.progress = ttk.Progressbar(progress_lf, maximum=100, mode='determinate')
        self.progress.pack(fill='x', padx=10, pady=(0, 10))

        log_frame = ttk.Frame(self.log_tab)
        log_frame.pack(fill='both', expand=True, padx=14, pady=(0, 12))
        scrollbar = ttk.Scrollbar(log_frame)
        scrollbar.pack(side='right', fill='y')
        self.log_text = tk.Text(log_frame, height=15, width=85, yscrollcommand=scrollbar.set)
        self.log_text.pack(side='left', fill='both', expand=True)
        scrollbar.config(command=self.log_text.yview)

    def _build_action_buttons(self):
        """画面下部の主要アクションを中央に配置する。"""
        frame = ttk.Frame(self.main_container)
        frame.pack(fill='x', padx=14, pady=(6, 12))
        inner = ttk.Frame(frame)
        inner.pack(anchor='center')
        tk.Button(inner, text=t('btn_start_compress'), command=self.start_compress, width=16, bg='#ccffcc').pack(side='left', padx=14)
        tk.Button(inner, text=t('btn_exit'), command=self.on_exit, width=12, bg='#e6e6e6').pack(side='left', padx=14)

    def _create_lossless_controls(self, parent):
        """pikepdf 可逆最適化オプションのチェックボックス群を共通生成する。

        native/GS の両経路で同じ pikepdf オプションを使うため、UI の生成だけ共通化して
        説明ラベルや初期値のズレを防ぐ。
        """
        frame = ttk.Frame(parent)
        widgets: list[ttk.Checkbutton] = []

        row1 = ttk.Frame(frame)
        row1.pack(fill='x', padx=5, pady=2)
        for text, var in [
            ('Linearize', self.pdf_ll_linearize),
            ('ObjStream圧縮', self.pdf_ll_object_streams),
            ('メタデータ除去', self.pdf_ll_clean_metadata),
        ]:
            checkbox = ttk.Checkbutton(row1, text=text, variable=var)
            checkbox.pack(side='left', padx=(0, 12))
            widgets.append(checkbox)

        row2 = ttk.Frame(frame)
        row2.pack(fill='x', padx=5, pady=2)
        for text, var in [
            ('Flate再圧縮', self.pdf_ll_recompress_streams),
            ('孤立リソース削除', self.pdf_ll_remove_unreferenced),
        ]:
            checkbox = ttk.Checkbutton(row2, text=text, variable=var)
            checkbox.pack(side='left', padx=(0, 12))
            widgets.append(checkbox)

        return frame, widgets
