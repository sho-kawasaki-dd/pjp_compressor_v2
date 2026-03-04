from __future__ import annotations

import os
import threading
from tkinter import filedialog, messagebox

from backend.core.compressor_utils import cleanup_folder, count_target_files, human_readable
from backend.contracts import ProgressEvent
from backend.orchestrator.job_runner import run_compression_request
from frontend.ui_tkinter_mapper import build_compression_request
from frontend.sound_utils import play_sound
from shared.configs import INPUT_DIR_CLEANUP_EXTENSIONS, OUTPUT_DIR_CLEANUP_EXTENSIONS, SOUNDS_DIR


class TkUiControllerMixin:
    def _update_pdf_controls(self):
        engine = self.pdf_engine.get()

        if engine == 'native':
            self.gs_frame.pack_forget()
            self.native_frame.pack(fill='x', padx=5, pady=(2, 5))

            mode = self.pdf_mode.get()
            lossy_active = mode in ('lossy', 'both')
            lossless_active = mode in ('lossless', 'both')

            lossy_state = 'normal' if lossy_active else 'disabled'
            for widget in self._native_lossy_widgets:
                try:
                    widget.config(state=lossy_state)
                except Exception:
                    pass
            try:
                self.dpi_scale.config(state=lossy_state)
                self.jpeg_q_scale.config(state=lossy_state)
            except Exception:
                pass

            if lossy_active and not self.pdf_png_to_jpeg.get():
                self.jpeg_note_label.pack(side='left', padx=(5, 0))
            else:
                self.jpeg_note_label.pack_forget()

            lossless_state = 'normal' if lossless_active else 'disabled'
            for widget in self._native_lossless_widgets:
                try:
                    widget.config(state=lossless_state)
                except Exception:
                    pass
            return

        self.native_frame.pack_forget()
        self.gs_frame.pack(fill='x', padx=5, pady=(2, 5))

        is_custom = self.gs_preset.get() == 'custom'
        for widget in self._gs_custom_dpi_widgets:
            try:
                widget.config(state='normal' if is_custom else 'disabled')
            except Exception:
                pass

        gs_lossless = self.gs_use_lossless.get()
        for widget in self._gs_lossless_widgets:
            try:
                widget.config(state='normal' if gs_lossless else 'disabled')
            except Exception:
                pass

    def _refresh_pdf_engine_status(self):
        report = self.capabilities
        parts = [
            'PyMuPDF:OK' if report.fitz_available else 'PyMuPDF:なし',
            'pikepdf:OK' if report.pikepdf_available else 'pikepdf:なし',
            'GS:OK' if report.ghostscript_available else 'GS:未検出',
        ]

        if not report.ghostscript_available:
            try:
                self.gs_rb.config(state='disabled')
            except Exception:
                pass
            if self.pdf_engine.get() == 'gs':
                self.pdf_engine.set('native')

        if not report.native_pdf_available:
            try:
                self.native_rb.config(state='disabled')
            except Exception:
                pass

        self.pdf_engine_status_var.set(f"（{', '.join(parts)}）")

    def _update_resize_controls(self):
        try:
            enabled = self.resize_enabled.get()
            mode = self.resize_mode.get()
            is_manual = enabled and mode == 'manual'
            is_long_edge = enabled and mode == 'long_edge'

            for widget in (self.resize_width_entry, self.resize_height_entry):
                widget.config(state='normal' if is_manual else 'disabled')
            self.resize_keep_aspect_chk.config(state='normal' if is_manual else 'disabled')
            self.resize_mode_manual_rb.config(state='normal' if enabled else 'disabled')
            self.resize_mode_long_rb.config(state='normal' if enabled else 'disabled')
            self.long_edge_combo.config(state='normal' if is_long_edge else 'disabled')
        except Exception:
            pass

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
        try:
            paths = self.tk.splitlist(event.data)
        except Exception:
            paths = [event.data]

        for path in paths:
            normalized = path.strip('{}')
            if os.path.isdir(normalized):
                self.input_dir.set(normalized)
                self.log(f'D&D で入力フォルダ設定: {normalized}')
                break
            if os.path.isfile(normalized):
                input_dir = os.path.dirname(normalized)
                self.input_dir.set(input_dir)
                self.log(f'D&D で入力フォルダ設定: {input_dir}')
                break

    def _validate_and_fix_dirs(self):
        new_input, new_output, conflict = self._check_overlap_and_fix(self.input_dir.get(), self.output_dir.get())
        if conflict:
            self.input_dir.set(new_input)
            self.output_dir.set(new_output)
            self.log(f'入出力フォルダ重なり → リセット 入力:{new_input} 出力:{new_output}')
            messagebox.showwarning('入出力フォルダの重なり', '入力/出力フォルダが同一または内包関係にあるためデフォルトに戻しました。')

    def _paths_overlap(self, a, b):
        try:
            abs_a, abs_b = os.path.abspath(a), os.path.abspath(b)
            if abs_a == abs_b:
                return True
            common = os.path.commonpath([abs_a, abs_b])
            return common == abs_a or common == abs_b
        except Exception:
            return False

    def _check_overlap_and_fix(self, input_dir, output_dir):
        if input_dir and output_dir and self._paths_overlap(input_dir, output_dir):
            return self.default_input_dir, self.default_output_dir, True
        return input_dir, output_dir, False

    def _choose_csv_path(self):
        path = filedialog.asksaveasfilename(
            initialdir=self.output_dir.get() or os.getcwd(),
            defaultextension='.csv',
            filetypes=[('CSV files', '*.csv'), ('All files', '*.*')],
        )
        if path:
            self.csv_path.set(path)

    def _set_status(self, text):
        if threading.current_thread() is threading.main_thread():
            self.status_var.set(text)
            return
        self.after(0, lambda: self.status_var.set(text))

    def _append_log(self, msg):
        self.log_text.insert('end', msg + '\n')
        self.log_text.see('end')

        if '完了！' in msg:
            current = self.progress['value']
            self.status_var.set(f'完了（進捗 {int(current)}%）')
        elif '処理中にエラー発生' in msg:
            self.status_var.set('失敗（詳細はログ）')

    def log(self, msg):
        if threading.current_thread() is threading.main_thread():
            self._append_log(msg)
            return
        self.after(0, lambda: self._append_log(msg))

    def _update_progress_ui(self, current, total):
        pct = 100 if total <= 0 else int(current / total * 100)
        self.progress['value'] = pct
        self.status_var.set(f'処理中 {pct}% ({current}/{total})')
        self.update_idletasks()

    def update_progress(self, current, total):
        if threading.current_thread() is threading.main_thread():
            self._update_progress_ui(current, total)
            return
        self.after(0, lambda: self._update_progress_ui(current, total))

    def _update_stats_ui(self, orig_total, out_total, saved, saved_pct):
        self.stats_var.set(
            f'統計: 元合計={human_readable(orig_total)}, '
            f'出力合計={human_readable(out_total)}, '
            f'削減={human_readable(saved)} ({saved_pct:.1f}%)'
        )
        self.status_var.set(f'完了（削減率 {saved_pct:.1f}%）')

    def update_stats(self, orig_total, out_total, saved, saved_pct):
        if threading.current_thread() is threading.main_thread():
            self._update_stats_ui(orig_total, out_total, saved, saved_pct)
            return
        self.after(0, lambda: self._update_stats_ui(orig_total, out_total, saved, saved_pct))

    def _on_progress_event(self, event: ProgressEvent):
        if event.kind == 'log' and event.message is not None:
            self.log(event.message)
            return
        if event.kind == 'progress':
            self.update_progress(event.current or 0, event.total or 0)
            return
        if event.kind == 'stats':
            self.update_stats(event.orig_total or 0, event.out_total or 0, event.saved or 0, event.saved_pct or 0.0)
            return
        if event.kind == 'status' and event.message is not None:
            self._set_status(event.message)
            return
        if event.kind == 'error' and event.message is not None:
            self.log(event.message)
            self._set_status('失敗（詳細はログ）')

    def start_compress(self):
        input_dir = self.input_dir.get()
        output_dir = self.output_dir.get()

        fixed_input, fixed_output, conflict = self._check_overlap_and_fix(input_dir, output_dir)
        if conflict:
            self.input_dir.set(fixed_input)
            self.output_dir.set(fixed_output)
            input_dir, output_dir = fixed_input, fixed_output
            self.log(f'入出力フォルダ重なり → リセット 入力:{fixed_input} 出力:{fixed_output}')
            messagebox.showwarning(
                '入出力フォルダの重なり',
                f'デフォルトに戻しました。\n入力: {self.default_input_dir}\n出力: {self.default_output_dir}',
            )

        if not input_dir or not output_dir:
            self._set_status('失敗（入力/出力フォルダ未指定）')
            messagebox.showerror('エラー', '両方のフォルダを選択してください')
            return
        if not os.path.isdir(input_dir):
            self._set_status('失敗（入力フォルダを確認）')
            messagebox.showerror('エラー', '入力フォルダが存在しません')
            return
        os.makedirs(output_dir, exist_ok=True)

        if self.auto_switch_log_tab.get():
            self.notebook.select(self.log_tab)

        self.log_text.delete(1.0, 'end')
        self.progress['value'] = 0
        self.stats_var.set('統計: 処理中...')
        self.status_var.set('圧縮開始準備中…')

        result = build_compression_request(self)
        request = result.request

        self.log(f'圧縮開始: 入力={input_dir}')
        self.log(f'出力先: {output_dir}')

        if request.pdf_engine == 'native':
            self.log(
                f'PDF: ネイティブ モード={request.pdf_mode}, DPI={request.pdf_dpi}, '
                f'JPEG品質={request.pdf_jpeg_quality}, PNG→JPEG={request.pdf_png_to_jpeg}'
            )
        else:
            if request.gs_preset == 'custom':
                self.log(
                    f'PDF: GhostScript カスタムDPI={request.gs_custom_dpi}, '
                    f'pikepdf併用={self.gs_use_lossless.get()}'
                )
            else:
                self.log(
                    f'PDF: GhostScript プリセット={request.gs_preset}, '
                    f'pikepdf併用={self.gs_use_lossless.get()}'
                )

        self.log(
            f'画像: JPG={request.jpg_quality}, PNG={request.png_quality}, '
            f'pngquant={request.use_pngquant}'
        )
        if self.resize_enabled.get():
            self.log(f'リサイズ: {result.resize_config}')

        self._set_status('処理中 0% (0/0)')

        thread = threading.Thread(
            target=run_compression_request,
            kwargs={'request': request, 'event_callback': self._on_progress_event},
            daemon=True,
        )
        self.threads.append(thread)
        thread.start()

    def cleanup_input(self):
        input_dir = self.input_dir.get()
        if not input_dir or not os.path.exists(input_dir):
            messagebox.showerror('エラー', '入力フォルダが未指定、または存在しません')
            return

        count = count_target_files(input_dir, INPUT_DIR_CLEANUP_EXTENSIONS)
        exts = ', '.join(sorted(INPUT_DIR_CLEANUP_EXTENSIONS))
        play_sound(os.path.join(SOUNDS_DIR, 'warning.wav'))
        if messagebox.askyesno(
            'クリーンアップ確認',
            f'入力フォルダ内の対象ファイルを削除しますか？\n\n'
            f'【対象拡張子】\n{exts}\n\n'
            f'【削除対象ファイル数】\n約 {count} ファイル\n\n'
            'サブフォルダ含め削除されます。取り消し不可。',
        ):
            self.log(f'入力フォルダクリーンアップ開始（{exts}）…')
            thread = threading.Thread(
                target=cleanup_folder,
                args=(input_dir, self.log, '入力フォルダ', INPUT_DIR_CLEANUP_EXTENSIONS),
                daemon=True,
            )
            self.threads.append(thread)
            thread.start()

    def cleanup_output(self):
        output_dir = self.output_dir.get()
        if not output_dir or not os.path.exists(output_dir):
            messagebox.showerror('エラー', '出力フォルダが未指定、または存在しません')
            return

        count = count_target_files(output_dir, OUTPUT_DIR_CLEANUP_EXTENSIONS)
        exts = ', '.join(sorted(OUTPUT_DIR_CLEANUP_EXTENSIONS))
        play_sound(os.path.join(SOUNDS_DIR, 'warning.wav'))
        if messagebox.askyesno(
            'クリーンアップ確認',
            f'出力フォルダ内の対象ファイルを削除しますか？\n\n'
            f'【対象拡張子】\n{exts}\n\n'
            f'【削除対象ファイル数】\n約 {count} ファイル\n\n'
            'サブフォルダ含め削除されます。取り消し不可。',
        ):
            self.log(f'出力フォルダクリーンアップ開始（{exts}）…')
            thread = threading.Thread(
                target=cleanup_folder,
                args=(output_dir, self.log, '出力フォルダ', OUTPUT_DIR_CLEANUP_EXTENSIONS),
                daemon=True,
            )
            self.threads.append(thread)
            thread.start()

    def on_exit(self):
        if any(thread.is_alive() for thread in self.threads):
            if not messagebox.askyesno('終了確認', '処理中のスレッドがあります。終了しますか？'):
                return
        self.destroy()
