from __future__ import annotations

import shutil
import tkinter as tk
from tkinter import ttk

from shared.configs import (
    GS_PRESETS,
    LONG_EDGE_PRESETS,
    PDF_COMPRESS_MODES,
    PDF_LOSSY_DPI_RANGE,
)


class TkUiViewMixin:
    def build_layout(self) -> None:
        self._build_root_scroll_container()
        self._build_folder_section()
        self._build_notebook()
        self._build_action_buttons()
        self._bind_root_mousewheel()

    def _build_root_scroll_container(self):
        root_frame = ttk.Frame(self)
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
        self.main_canvas.configure(scrollregion=self.main_canvas.bbox('all'))

    def _on_main_canvas_configure(self, event):
        self.main_canvas.itemconfigure(self.main_container_window, width=event.width)

    def _bind_root_mousewheel(self):
        self.bind_all('<MouseWheel>', self._on_root_mousewheel, add='+')

    def _on_root_mousewheel(self, event):
        # Keep Text widget wheel behavior unchanged (log area scrolls itself).
        target = self.winfo_containing(event.x_root, event.y_root)
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
        folder_frame = ttk.Frame(self.main_container)
        folder_frame.pack(fill='x', padx=14, pady=(12, 8))

        row_in = ttk.Frame(folder_frame)
        row_in.pack(fill='x', pady=4)
        ttk.Label(row_in, text='入力フォルダ:').pack(side='left')
        self.input_entry = ttk.Entry(row_in, textvariable=self.input_dir, width=45)
        self.input_entry.pack(side='left', padx=8)
        ttk.Button(row_in, text='選択', command=self.choose_input).pack(side='left', padx=4)
        tk.Button(row_in, text='クリーンアップ', command=self.cleanup_input, bg='#d0f6ff').pack(side='left', padx=4)

        if self.dnd_available:
            self.input_entry.drop_target_register(self.DND_FILES)
            self.input_entry.dnd_bind('<<Drop>>', self._on_drop_input)
            ttk.Label(row_in, text='（D&D可）', foreground='gray').pack(side='left', padx=6)
        else:
            ttk.Label(row_in, text='（D&D無効: tkinterdnd2 未インストール）', foreground='gray').pack(side='left', padx=6)

        row_out = ttk.Frame(folder_frame)
        row_out.pack(fill='x', pady=4)
        ttk.Label(row_out, text='出力フォルダ:').pack(side='left')
        ttk.Entry(row_out, textvariable=self.output_dir, width=45).pack(side='left', padx=8)
        ttk.Button(row_out, text='選択', command=self.choose_output).pack(side='left', padx=4)
        tk.Button(row_out, text='クリーンアップ', command=self.cleanup_output, bg='#ffcaca').pack(side='left', padx=4)

    def _build_notebook(self):
        self.notebook = ttk.Notebook(self.main_container)
        self.notebook.pack(fill='both', expand=True, padx=14, pady=8)

        self.settings_tab = ttk.Frame(self.notebook)
        self.log_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.settings_tab, text=' 圧縮設定 ')
        self.notebook.add(self.log_tab, text=' ログ ')

        self._build_settings_tab()
        self._build_log_tab()

    def _build_settings_tab(self):
        pdf_outer = tk.LabelFrame(
            self.settings_tab,
            text=' PDF圧縮設定（Pythonライブラリ / GhostScript） ',
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
            text=' 画像ファイル圧縮設定（JPEG/PNG 圧縮・リサイズ） ',
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
        engine_frame = ttk.Frame(parent)
        engine_frame.pack(fill='x', padx=8, pady=(6, 4))

        ttk.Label(engine_frame, text='エンジン:').pack(side='left')
        self.native_rb = ttk.Radiobutton(
            engine_frame,
            text='ネイティブ (PyMuPDF + pikepdf)',
            variable=self.pdf_engine,
            value='native',
            command=self._update_pdf_controls,
        )
        self.native_rb.pack(side='left', padx=(10, 5))
        self.gs_rb = ttk.Radiobutton(
            engine_frame,
            text='GhostScript',
            variable=self.pdf_engine,
            value='gs',
            command=self._update_pdf_controls,
        )
        self.gs_rb.pack(side='left', padx=5)

        self.pdf_engine_status_var = tk.StringVar(value='判定中…')
        ttk.Label(engine_frame, textvariable=self.pdf_engine_status_var, foreground='purple').pack(side='left', padx=(10, 0))

        self.native_frame = ttk.Frame(parent)
        self._build_native_controls(self.native_frame)

        self.gs_frame = ttk.Frame(parent)
        self._build_gs_controls(self.gs_frame)

    def _build_native_controls(self, parent):
        mode_frame = ttk.Frame(parent)
        mode_frame.pack(fill='x', padx=5, pady=2)
        ttk.Label(mode_frame, text='モード:').pack(side='left')
        for value, label in PDF_COMPRESS_MODES.items():
            ttk.Radiobutton(
                mode_frame,
                text=label,
                variable=self.pdf_mode,
                value=value,
                command=self._update_pdf_controls,
            ).pack(side='left', padx=(10, 3))

        self.lossy_lf = ttk.LabelFrame(parent, text='非可逆オプション')
        self.lossy_lf.pack(fill='x', padx=8, pady=4)
        self._native_lossy_widgets = []

        dpi_row = ttk.Frame(self.lossy_lf)
        dpi_row.pack(fill='x', padx=5, pady=2)
        dpi_label = ttk.Label(dpi_row, text='DPI:')
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
        jpeg_label = ttk.Label(jpeg_row, text='JPEG品質:')
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

        self.jpeg_note_label = ttk.Label(jpeg_row, text='※JPEG元画像にのみ適用', foreground='gray')

        png_jpeg_row = ttk.Frame(self.lossy_lf)
        png_jpeg_row.pack(fill='x', padx=5, pady=2)
        self.png_to_jpeg_cb = ttk.Checkbutton(
            png_jpeg_row,
            text='PNG → JPEG 変換',
            variable=self.pdf_png_to_jpeg,
            command=self._update_pdf_controls,
        )
        self.png_to_jpeg_cb.pack(side='left')
        self._native_lossy_widgets.append(self.png_to_jpeg_cb)

        self.native_lossless_lf = ttk.LabelFrame(parent, text='可逆オプション')
        self.native_lossless_lf.pack(fill='x', padx=8, pady=4)
        self._native_ll_frame, self._native_lossless_widgets = self._create_lossless_controls(self.native_lossless_lf)
        self._native_ll_frame.pack(fill='x')

    def _build_gs_controls(self, parent):
        preset_lf = ttk.LabelFrame(parent, text='プリセット')
        preset_lf.pack(fill='x', padx=8, pady=4)
        self._gs_preset_widgets = []

        preset_grid = ttk.Frame(preset_lf)
        preset_grid.pack(fill='x', padx=5, pady=2)
        all_presets = list(GS_PRESETS.items()) + [('custom', 'カスタム')]
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
        custom_label = ttk.Label(custom_row, text='カスタム DPI:')
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
            text='pikepdf 構造最適化も適用',
            variable=self.gs_use_lossless,
            command=self._update_pdf_controls,
        )
        self.gs_use_lossless_cb.pack(side='left')

        self.gs_lossless_lf = ttk.LabelFrame(parent, text='可逆オプション（pikepdf）')
        self.gs_lossless_lf.pack(fill='x', padx=8, pady=4)
        self._gs_ll_frame, self._gs_lossless_widgets = self._create_lossless_controls(self.gs_lossless_lf)
        self._gs_ll_frame.pack(fill='x')

    def _build_image_section(self, parent):
        img_lf = ttk.LabelFrame(parent, text=' 画像圧縮 ')
        img_lf.pack(fill='x', padx=8, pady=5)

        jpg_row = ttk.Frame(img_lf)
        jpg_row.pack(fill='x', padx=5, pady=2)
        ttk.Label(jpg_row, text='JPG 品質 (0-100):').pack(side='left')
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
        ttk.Label(png_row, text='PNG 品質 (0-100):').pack(side='left')
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

        pq_row = ttk.Frame(img_lf)
        pq_row.pack(fill='x', padx=5, pady=2)
        self.pngquant_check = ttk.Checkbutton(
            pq_row,
            text='pngquant 使用（パレット量子化・不可逆）',
            variable=self.use_pngquant,
        )
        self.pngquant_check.pack(side='left')
        if not shutil.which('pngquant'):
            self.pngquant_check.config(state='disabled')
            ttk.Label(pq_row, text='（pngquant 未検出のため無効）', foreground='gray').pack(side='left', padx=10)

    def _build_resize_section(self, parent):
        resize_lf = ttk.LabelFrame(parent, text=' リサイズ ')
        resize_lf.pack(fill='x', padx=8, pady=5)

        enable_row = ttk.Frame(resize_lf)
        enable_row.pack(fill='x', padx=5, pady=2)
        ttk.Checkbutton(
            enable_row,
            text='画像を一括リサイズする',
            variable=self.resize_enabled,
            command=self._update_resize_controls,
        ).pack(side='left')

        ctrl_row = ttk.Frame(resize_lf)
        ctrl_row.pack(fill='x', padx=5, pady=2)
        self.resize_mode_manual_rb = ttk.Radiobutton(
            ctrl_row,
            text='手動',
            variable=self.resize_mode,
            value='manual',
            command=self._update_resize_controls,
        )
        self.resize_mode_manual_rb.pack(side='left')
        ttk.Label(ctrl_row, text='幅:').pack(side='left', padx=(10, 2))
        self.resize_width_entry = ttk.Entry(ctrl_row, textvariable=self.resize_width, width=6)
        self.resize_width_entry.pack(side='left')
        ttk.Label(ctrl_row, text='高さ:').pack(side='left', padx=(10, 2))
        self.resize_height_entry = ttk.Entry(ctrl_row, textvariable=self.resize_height, width=6)
        self.resize_height_entry.pack(side='left')
        self.resize_keep_aspect_chk = ttk.Checkbutton(ctrl_row, text='アスペクト比保持', variable=self.resize_keep_aspect)
        self.resize_keep_aspect_chk.pack(side='left', padx=(12, 0))

        long_row = ttk.Frame(resize_lf)
        long_row.pack(fill='x', padx=5, pady=2)
        self.resize_mode_long_rb = ttk.Radiobutton(
            long_row,
            text='長辺指定',
            variable=self.resize_mode,
            value='long_edge',
            command=self._update_resize_controls,
        )
        self.resize_mode_long_rb.pack(side='left')
        ttk.Label(long_row, text='長辺(px):').pack(side='left', padx=(10, 2))
        self.long_edge_combo = ttk.Combobox(long_row, textvariable=self.long_edge_value_str, values=LONG_EDGE_PRESETS, width=8)
        self.long_edge_combo.pack(side='left')

    def _build_output_section(self, parent):
        out_lf = ttk.LabelFrame(parent, text=' 出力設定 ')
        out_lf.pack(fill='x', padx=8, pady=5)

        csv_row = ttk.Frame(out_lf)
        csv_row.pack(fill='x', padx=5, pady=2)
        ttk.Checkbutton(csv_row, text='CSV ログを出力する', variable=self.csv_enable).pack(side='left')
        ttk.Label(csv_row, text='保存先(任意):').pack(side='left', padx=(10, 2))
        ttk.Entry(csv_row, textvariable=self.csv_path, width=35).pack(side='left', padx=5)
        ttk.Button(csv_row, text='参照', command=self._choose_csv_path).pack(side='left', padx=2)

        zip_row = ttk.Frame(out_lf)
        zip_row.pack(fill='x', padx=5, pady=2)
        ttk.Checkbutton(zip_row, text='ZIP 展開してから圧縮', variable=self.extract_zip).pack(side='left')

        copy_row = ttk.Frame(out_lf)
        copy_row.pack(fill='x', padx=5, pady=2)
        ttk.Checkbutton(
            copy_row,
            text='圧縮対象外のファイルを出力フォルダへコピー',
            variable=self.copy_non_target_files,
        ).pack(side='left')

        log_row = ttk.Frame(out_lf)
        log_row.pack(fill='x', padx=5, pady=2)
        ttk.Checkbutton(log_row, text='圧縮開始時にログタブへ自動切替', variable=self.auto_switch_log_tab).pack(side='left')

    def _build_log_tab(self):
        stats_frame = ttk.Frame(self.log_tab)
        stats_frame.pack(fill='x', padx=14, pady=(12, 8))
        self.stats_var = tk.StringVar(value='統計: 処理前')
        ttk.Label(stats_frame, textvariable=self.stats_var, foreground='blue', font=('Arial', 10, 'bold')).pack(side='left')

        progress_lf = ttk.LabelFrame(self.log_tab, text=' 進捗 ')
        progress_lf.pack(fill='x', padx=14, pady=(0, 8))

        status_row = ttk.Frame(progress_lf)
        status_row.pack(fill='x', padx=10, pady=(8, 4))
        ttk.Label(status_row, text='状態:').pack(side='left')
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
        frame = ttk.Frame(self.main_container)
        frame.pack(fill='x', padx=14, pady=(6, 12))
        inner = ttk.Frame(frame)
        inner.pack(anchor='center')
        tk.Button(inner, text='圧縮開始', command=self.start_compress, width=16, bg='#ccffcc').pack(side='left', padx=14)
        tk.Button(inner, text='終了', command=self.on_exit, width=12, bg='#e6e6e6').pack(side='left', padx=14)

    def _create_lossless_controls(self, parent):
        frame = ttk.Frame(parent)
        widgets = []

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
