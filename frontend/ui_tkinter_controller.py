from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from typing import Any, Callable, cast
from tkinter import filedialog, messagebox

from backend.core.compressor_utils import cleanup_folder, count_target_files, human_readable
from backend.contracts import ProgressEvent
from backend.orchestrator.job_runner import run_compression_request
from frontend.ui_contracts import DropEventProtocol, TkUiControllerHostProtocol
from frontend.ui_tkinter_mapper import build_compression_request
from frontend.sound_utils import play_sound
from shared.configs import INPUT_DIR_CLEANUP_EXTENSIONS, OUTPUT_DIR_CLEANUP_EXTENSIONS, SOUNDS_DIR


class TkUiControllerMixin:
    def _controller_host(self) -> TkUiControllerHostProtocol:
        return cast(TkUiControllerHostProtocol, self)

    def _schedule_on_ui_thread(self, callback: Callable[[], None]) -> None:
        self._controller_host().after(0, callback)

    @staticmethod
    def _set_widget_state(widget: tk.Misc, state: str) -> None:
        try:
            cast(Any, widget).config(state=state)
        except tk.TclError:
            pass

    def _update_pdf_controls(self) -> None:
        host = self._controller_host()
        engine = host.pdf_engine.get()

        if engine == 'native':
            host.gs_frame.pack_forget()
            host.native_frame.pack(fill='x', padx=5, pady=(2, 5))

            mode = host.pdf_mode.get()
            lossy_active = mode in ('lossy', 'both')
            lossless_active = mode in ('lossless', 'both')

            lossy_state = 'normal' if lossy_active else 'disabled'
            for widget in host._native_lossy_widgets:
                self._set_widget_state(widget, lossy_state)
            self._set_widget_state(host.dpi_scale, lossy_state)
            self._set_widget_state(host.jpeg_q_scale, lossy_state)

            if lossy_active and not host.pdf_png_to_jpeg.get():
                host.jpeg_note_label.pack(side='left', padx=(5, 0))
            else:
                host.jpeg_note_label.pack_forget()

            lossless_state = 'normal' if lossless_active else 'disabled'
            for widget in host._native_lossless_widgets:
                self._set_widget_state(widget, lossless_state)
            return

        host.native_frame.pack_forget()
        host.gs_frame.pack(fill='x', padx=5, pady=(2, 5))

        is_custom = host.gs_preset.get() == 'custom'
        for widget in host._gs_custom_dpi_widgets:
            self._set_widget_state(widget, 'normal' if is_custom else 'disabled')

        gs_lossless = host.gs_use_lossless.get()
        for widget in host._gs_lossless_widgets:
            self._set_widget_state(widget, 'normal' if gs_lossless else 'disabled')

    def _refresh_pdf_engine_status(self) -> None:
        host = self._controller_host()
        report = host.capabilities
        parts = [
            'PyMuPDF:OK' if report.fitz_available else 'PyMuPDF:なし',
            'pikepdf:OK' if report.pikepdf_available else 'pikepdf:なし',
            'GS:OK' if report.ghostscript_available else 'GS:未検出',
        ]

        if not report.ghostscript_available:
            self._set_widget_state(host.gs_rb, 'disabled')
            if host.pdf_engine.get() == 'gs':
                host.pdf_engine.set('native')

        if not report.native_pdf_available:
            self._set_widget_state(host.native_rb, 'disabled')

        host.pdf_engine_status_var.set(f"（{', '.join(parts)}）")

    def _update_resize_controls(self) -> None:
        host = self._controller_host()
        enabled = host.resize_enabled.get()
        mode = host.resize_mode.get()
        is_manual = enabled and mode == 'manual'
        is_long_edge = enabled and mode == 'long_edge'

        for widget in (host.resize_width_entry, host.resize_height_entry):
            self._set_widget_state(widget, 'normal' if is_manual else 'disabled')
        self._set_widget_state(host.resize_keep_aspect_chk, 'normal' if is_manual else 'disabled')
        self._set_widget_state(host.resize_mode_manual_rb, 'normal' if enabled else 'disabled')
        self._set_widget_state(host.resize_mode_long_rb, 'normal' if enabled else 'disabled')
        self._set_widget_state(host.long_edge_combo, 'normal' if is_long_edge else 'disabled')

    def choose_input(self) -> None:
        host = self._controller_host()
        folder = filedialog.askdirectory(initialdir=host.input_dir.get() or None)
        if folder:
            host.input_dir.set(folder)
            self._validate_and_fix_dirs()

    def choose_output(self) -> None:
        host = self._controller_host()
        folder = filedialog.askdirectory(initialdir=host.output_dir.get() or None)
        if folder:
            host.output_dir.set(folder)
            self._validate_and_fix_dirs()

    def _on_drop_input(self, event: DropEventProtocol) -> None:
        host = self._controller_host()
        try:
            paths = host.tk.splitlist(event.data)
        except tk.TclError:
            paths = [event.data]

        for path in paths:
            normalized = path.strip('{}')
            dropped = Path(normalized)
            if dropped.is_dir():
                host.input_dir.set(normalized)
                self.log(f'D&D で入力フォルダ設定: {normalized}')
                break
            if dropped.is_file():
                input_dir = dropped.parent
                host.input_dir.set(str(input_dir))
                self.log(f'D&D で入力フォルダ設定: {input_dir}')
                break

    def _validate_and_fix_dirs(self) -> None:
        host = self._controller_host()
        new_input, new_output, conflict = self._check_overlap_and_fix(host.input_dir.get(), host.output_dir.get())
        if conflict:
            host.input_dir.set(new_input)
            host.output_dir.set(new_output)
            self.log(f'入出力フォルダ重なり → リセット 入力:{new_input} 出力:{new_output}')
            messagebox.showwarning('入出力フォルダの重なり', '入力/出力フォルダが同一または内包関係にあるためデフォルトに戻しました。')

    def _paths_overlap(self, a: str, b: str) -> bool:
        try:
            pa = Path(a).resolve()
            pb = Path(b).resolve()
            return pa == pb or pa in pb.parents or pb in pa.parents
        except Exception:
            return False

    def _check_overlap_and_fix(self, input_dir: str, output_dir: str) -> tuple[str, str, bool]:
        host = self._controller_host()
        if input_dir and output_dir and self._paths_overlap(input_dir, output_dir):
            return host.default_input_dir, host.default_output_dir, True
        return input_dir, output_dir, False

    def _choose_csv_path(self) -> None:
        host = self._controller_host()
        path = filedialog.asksaveasfilename(
            initialdir=host.output_dir.get() or str(Path.cwd()),
            defaultextension='.csv',
            filetypes=[('CSV files', '*.csv'), ('All files', '*.*')],
        )
        if path:
            host.csv_path.set(path)

    def _set_status(self, text: str) -> None:
        host = self._controller_host()
        if threading.current_thread() is threading.main_thread():
            host.status_var.set(text)
            return
        self._schedule_on_ui_thread(lambda: host.status_var.set(text))

    def _append_log(self, msg: str) -> None:
        host = self._controller_host()
        host.log_text.insert('end', msg + '\n')
        host.log_text.see('end')

        if '完了！' in msg:
            current = int(float(host.progress['value']))
            host.status_var.set(f'完了（進捗 {current}%）')
        elif '処理中にエラー発生' in msg:
            host.status_var.set('失敗（詳細はログ）')

    def log(self, msg: str) -> None:
        if threading.current_thread() is threading.main_thread():
            self._append_log(msg)
            return
        self._schedule_on_ui_thread(lambda: self._append_log(msg))

    def _update_progress_ui(self, current: int, total: int) -> None:
        host = self._controller_host()
        pct = 100 if total <= 0 else int(current / total * 100)
        host.progress['value'] = pct
        host.status_var.set(f'処理中 {pct}% ({current}/{total})')
        host.update_idletasks()

    def update_progress(self, current: int, total: int) -> None:
        if threading.current_thread() is threading.main_thread():
            self._update_progress_ui(current, total)
            return
        self._schedule_on_ui_thread(lambda: self._update_progress_ui(current, total))

    def _update_stats_ui(self, orig_total: int, out_total: int, saved: int, saved_pct: float) -> None:
        host = self._controller_host()
        host.stats_var.set(
            f'統計: 元合計={human_readable(orig_total)}, '
            f'出力合計={human_readable(out_total)}, '
            f'削減={human_readable(saved)} ({saved_pct:.1f}%)'
        )
        host.status_var.set(f'完了（削減率 {saved_pct:.1f}%）')

    def update_stats(self, orig_total: int, out_total: int, saved: int, saved_pct: float) -> None:
        if threading.current_thread() is threading.main_thread():
            self._update_stats_ui(orig_total, out_total, saved, saved_pct)
            return
        self._schedule_on_ui_thread(lambda: self._update_stats_ui(orig_total, out_total, saved, saved_pct))

    def _on_progress_event(self, event: ProgressEvent) -> None:
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

    def start_compress(self) -> None:
        host = self._controller_host()
        input_dir = host.input_dir.get()
        output_dir = host.output_dir.get()

        fixed_input, fixed_output, conflict = self._check_overlap_and_fix(input_dir, output_dir)
        if conflict:
            host.input_dir.set(fixed_input)
            host.output_dir.set(fixed_output)
            input_dir, output_dir = fixed_input, fixed_output
            self.log(f'入出力フォルダ重なり → リセット 入力:{fixed_input} 出力:{fixed_output}')
            messagebox.showwarning(
                '入出力フォルダの重なり',
                f'デフォルトに戻しました。\n入力: {host.default_input_dir}\n出力: {host.default_output_dir}',
            )

        if not input_dir or not output_dir:
            self._set_status('失敗（入力/出力フォルダ未指定）')
            messagebox.showerror('エラー', '両方のフォルダを選択してください')
            return
        if not Path(input_dir).is_dir():
            self._set_status('失敗（入力フォルダを確認）')
            messagebox.showerror('エラー', '入力フォルダが存在しません')
            return
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        if host.auto_switch_log_tab.get():
            host.notebook.select(host.log_tab)

        host.log_text.delete(1.0, 'end')
        host.progress['value'] = 0
        host.stats_var.set('統計: 処理中...')
        host.status_var.set('圧縮開始準備中…')

        result = build_compression_request(host)
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
                    f'pikepdf併用={host.gs_use_lossless.get()}'
                )
            else:
                self.log(
                    f'PDF: GhostScript プリセット={request.gs_preset}, '
                    f'pikepdf併用={host.gs_use_lossless.get()}'
                )

        self.log(
            f'画像: JPG={request.jpg_quality}, PNG={request.png_quality}, '
            f'pngquant={request.use_pngquant}'
        )
        if host.resize_enabled.get():
            self.log(f'リサイズ: {result.resize_config}')

        self._set_status('処理中 0% (0/0)')

        thread = threading.Thread(
            target=run_compression_request,
            kwargs={'request': request, 'event_callback': self._on_progress_event},
            daemon=True,
        )
        host.threads.append(thread)
        thread.start()

    def cleanup_input(self) -> None:
        host = self._controller_host()
        input_dir = host.input_dir.get()
        if not input_dir or not Path(input_dir).exists():
            messagebox.showerror('エラー', '入力フォルダが未指定、または存在しません')
            return

        count = count_target_files(input_dir, INPUT_DIR_CLEANUP_EXTENSIONS)
        exts = ', '.join(sorted(INPUT_DIR_CLEANUP_EXTENSIONS))
        play_sound(SOUNDS_DIR / 'warning.wav')
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
            host.threads.append(thread)
            thread.start()

    def cleanup_output(self) -> None:
        host = self._controller_host()
        output_dir = host.output_dir.get()
        if not output_dir or not Path(output_dir).exists():
            messagebox.showerror('エラー', '出力フォルダが未指定、または存在しません')
            return

        count = count_target_files(output_dir, OUTPUT_DIR_CLEANUP_EXTENSIONS)
        exts = ', '.join(sorted(OUTPUT_DIR_CLEANUP_EXTENSIONS))
        play_sound(SOUNDS_DIR / 'warning.wav')
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
            host.threads.append(thread)
            thread.start()

    def on_exit(self) -> None:
        host = self._controller_host()
        if any(thread.is_alive() for thread in host.threads):
            if not messagebox.askyesno('終了確認', '処理中のスレッドがあります。終了しますか？'):
                return
        host.destroy()
