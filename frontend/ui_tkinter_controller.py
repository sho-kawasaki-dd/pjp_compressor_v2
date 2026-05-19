from __future__ import annotations

"""Tkinter UI のイベント処理とバックグラウンド実行制御を担当する。

この mixin は widget の生成そのものではなく、ユーザー操作を安全な backend request に
変換し、非同期実行結果を UI 状態へ戻す責務を持つ。特に Tk のメインスレッド制約と、
入力値の危険な組み合わせを事前に止めるガードをここへ集約している。
"""

import threading
import tkinter as tk
from pathlib import Path
from typing import Any, Callable, cast
from tkinter import filedialog, messagebox

from backend.core.compressor_utils import cleanup_folder, count_target_files, human_readable
from backend.contracts import ProgressEvent
from backend.orchestrator.job_runner import run_compression_request
from frontend.settings import INPUT_DIR_CLEANUP_EXTENSIONS, OUTPUT_DIR_CLEANUP_EXTENSIONS, SOUNDS_DIR
from frontend.settings import save_app_settings
from frontend.i18n import t
from frontend.ui_contracts import DropEventProtocol, TkUiControllerHostProtocol
from frontend.ui_tkinter_mapper import build_compression_request
from frontend.sound_utils import play_sound


class TkUiControllerMixin:
    def _controller_host(self) -> TkUiControllerHostProtocol:
        """mixin から `App` 実体を型付きで参照する。"""
        return cast(TkUiControllerHostProtocol, self)

    def _schedule_on_ui_thread(self, callback: Callable[[], None]) -> None:
        """Tk のメインスレッドへ安全に処理を戻す。

        backend 側のイベントやクリーンアップ処理は別スレッドから来るため、widget 更新は
        必ず `after()` 経由でメインスレッドへ戻す。controller の各更新メソッドがこの
        入口を共有することで、スレッド安全性の前提を揃える。
        """
        self._controller_host().after(0, callback)

    @staticmethod
    def _set_widget_state(widget: tk.Misc, state: str) -> None:
        """widget の state 切替を TclError 無しで吸収する小さな安全ラッパー。"""
        try:
            cast(Any, widget).config(state=state)
        except tk.TclError:
            pass

    def _pdf_png_engine_label_text(self) -> str:
        """PDF 内 PNG 再圧縮で使う量子化エンジン表記を返す。"""
        host = self._controller_host()
        source_label = t(f'tool_source.{host.capabilities.pngquant_source}')
        if host.capabilities.pngquant_available:
            return t('pdf_png_engine.pngquant', source=source_label)
        return t('pdf_png_engine.pillow', source=source_label)

    def _image_png_engine_label_text(self) -> str:
        """通常 PNG 圧縮で使うエンジン表記を返す。"""
        host = self._controller_host()
        source_label = t(f'tool_source.{host.capabilities.pngquant_source}')
        if host.use_pngquant.get() and host.capabilities.pngquant_available:
            return t('image_png_engine.pngquant', source=source_label)
        return t('image_png_engine.pillow', source=source_label)

    def _update_png_engine_labels(self) -> None:
        """PNG 圧縮エンジン注記ラベルの文言を現在状態へ同期する。"""
        host = self._controller_host()
        host.pdf_png_method_label.config(text=self._pdf_png_engine_label_text())
        host.png_engine_note_label.config(text=self._image_png_engine_label_text())

    def _save_app_settings(self) -> bool:
        """アプリ設定タブのトグル状態を JSON へ永続化する。"""
        host = self._controller_host()
        return save_app_settings(
            language=host.ui_language.get(),
            play_startup_sound=host.play_startup_sound.get(),
            play_cleanup_sound=host.play_cleanup_sound.get(),
        )

    def _update_pdf_controls(self) -> None:
        """選択中の PDF エンジンとモードに合わせて関連 UI を有効/無効化する。

        WHY:
        - 同じ画面に native/GS の全オプションを常時見せると、現在の実行経路で意味を
          持たない設定まで触れてしまう
        - pngquant のように実行環境依存で有効/無効が変わる項目は、backend の暗黙の
          フォールバックへ丸投げせず UI 側で理由を見せる
        - pack/forget と state 切替を一箇所へ集めることで、engine/mode の組み合わせが
          増えても表示整合性を保ちやすくする
        """
        host = self._controller_host()
        engine = host.pdf_engine.get()
        self._update_png_engine_labels()

        if engine == 'native':
            host.gs_frame.pack_forget()
            host.native_frame.pack(fill='x', padx=5, pady=(2, 5))

            mode = host.pdf_mode.get()
            lossy_active = mode in ('lossy', 'both')
            lossless_active = mode in ('lossless', 'both')

            # 非可逆設定は mode に応じて一括で活性制御する。
            lossy_state = 'normal' if lossy_active else 'disabled'
            for widget in host._native_lossy_widgets:
                self._set_widget_state(widget, lossy_state)
            self._set_widget_state(host.dpi_scale, lossy_state)
            self._set_widget_state(host.jpeg_q_scale, lossy_state)
            # PDF 内 PNG 系画像の品質スライダーは、pngquant が使える環境だけで有効化する。
            # Pillow フォールバックでは 256 色固定減色となり品質値を消費しないため、
            # UI 側でも無効化して意図を明示する。
            png_quality_state = 'normal' if lossy_active and host.capabilities.pngquant_available else 'disabled'
            for widget in host._native_png_quality_widgets:
                self._set_widget_state(widget, png_quality_state)
            self._set_widget_state(host.pdf_png_q_scale, png_quality_state)

            if lossy_active:
                host.jpeg_note_label.pack(side='left', padx=(5, 0))
                host.pdf_png_method_label.pack(side='left', padx=(8, 0))
            else:
                host.jpeg_note_label.pack_forget()
                host.pdf_png_method_label.pack_forget()

            if lossy_active and not host.capabilities.pngquant_available:
                host.pdf_png_fallback_note_label.pack(side='left', padx=(5, 0))
            else:
                host.pdf_png_fallback_note_label.pack_forget()

            # 可逆設定は pikepdf を使うモードでのみ触れるようにする。
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
        """依存ライブラリ検出結果を表示し、使えないエンジンを無効化する。

        利用不能な engine を選ばせたまま実行時エラーに落とすより、起動直後に現在の能力を
        表示して UI 自体を制約した方が、設定画面の学習コストが低い。
        """
        host = self._controller_host()
        report = host.capabilities
        parts = [
            t('capability_fitz_ok') if report.fitz_available else t('capability_fitz_missing'),
            t('capability_pikepdf_ok') if report.pikepdf_available else t('capability_pikepdf_missing'),
            f"GS:{t(f'tool_source.{report.ghostscript_source}')}",
            f"pngquant:{t(f'tool_source.{report.pngquant_source}')}",
        ]

        if not report.ghostscript_available:
            self._set_widget_state(host.gs_rb, 'disabled')
            if host.pdf_engine.get() == 'gs':
                host.pdf_engine.set('native')

        if not report.native_pdf_available:
            self._set_widget_state(host.native_rb, 'disabled')

        host.pdf_engine_status_var.set(t('pdf_engine_status', parts=', '.join(parts)))

    def _update_resize_controls(self) -> None:
        """リサイズ設定の入力欄を現在のモードに合わせて切り替える。

        `manual` と `long_edge` は同時に成立しないため、無関係な入力欄をグレーアウトして
        「どの値が今効いているか」を明示する。
        """
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

    def _update_zip_output_controls(self) -> None:
        """ZIP 展開トグルに従って ZIP 出力トグルを同期する。

        ZIP 出力は展開後成果物にしか意味を持たないため、展開 OFF では UI を無効化し、
        残留していた ON 状態もここで落として request 値とのズレを防ぐ。
        """
        host = self._controller_host()
        extract_zip_enabled = host.extract_zip.get()

        if not extract_zip_enabled and host.zip_output_enabled.get():
            host.zip_output_enabled.set(False)

        self._set_widget_state(host.zip_output_check, 'normal' if extract_zip_enabled else 'disabled')

    def choose_input(self) -> None:
        """入力フォルダ選択ダイアログを開き、選択後に衝突チェックまで行う。"""
        host = self._controller_host()
        folder = filedialog.askdirectory(initialdir=host.input_dir.get() or None)
        if folder:
            host.input_dir.set(folder)
            self._validate_and_fix_dirs()

    def choose_output(self) -> None:
        """出力フォルダ選択ダイアログを開き、選択後に衝突チェックまで行う。"""
        host = self._controller_host()
        folder = filedialog.askdirectory(initialdir=host.output_dir.get() or None)
        if folder:
            host.output_dir.set(folder)
            self._validate_and_fix_dirs()

    def _on_drop_input(self, event: DropEventProtocol) -> None:
        """ドラッグ&ドロップされたパスから入力フォルダを解決する。

        D&D ではフォルダ自体が落ちる場合とファイルが落ちる場合があるため、ユーザーが
        毎回フォルダ単位で操作しなくても親フォルダへ自然に正規化する。
        """
        host = self._controller_host()
        try:
            paths = host.tk.splitlist(event.data)
        except tk.TclError:
            paths = [event.data]

        for path in paths:
            # tkinterdnd2 は空白を含むパスを `{...}` で包むことがあるため剥がして扱う。
            normalized = path.strip('{}')
            dropped = Path(normalized)
            if dropped.is_dir():
                host.input_dir.set(normalized)
                self.log(t('log_dnd_folder_set', path=normalized))
                break
            if dropped.is_file():
                input_dir = dropped.parent
                host.input_dir.set(str(input_dir))
                self.log(t('log_dnd_folder_set', path=input_dir))
                break

    def _validate_and_fix_dirs(self) -> None:
        """入出力の重なりを検知し、危険な組み合わせを既定値へ戻す。

        UI からの設定変更経路が複数あるため、ダイアログ選択や D&D のたびに同じ安全確認を
        走らせ、backend 実行前の状態を常に保守的なものに寄せる。
        """
        host = self._controller_host()
        new_input, new_output, conflict = self._check_overlap_and_fix(host.input_dir.get(), host.output_dir.get())
        if conflict:
            host.input_dir.set(new_input)
            host.output_dir.set(new_output)
            self.log(t('log_folders_overlap_reset', input=new_input, output=new_output))
            messagebox.showwarning(t('dlg_folder_overlap_title'), t('dlg_folder_overlap_message'))

    def _paths_overlap(self, a: str, b: str) -> bool:
        """同一または内包関係のパスかを判定する。"""
        try:
            pa = Path(a).resolve()
            pb = Path(b).resolve()
            return pa == pb or pa in pb.parents or pb in pa.parents
        except Exception:
            return False

    def _check_overlap_and_fix(self, input_dir: str, output_dir: str) -> tuple[str, str, bool]:
        """危険な入出力の組み合わせを検知し、安全な既定値へフォールバックする。"""
        host = self._controller_host()
        if input_dir and output_dir and self._paths_overlap(input_dir, output_dir):
            return host.default_input_dir, host.default_output_dir, True
        return input_dir, output_dir, False

    def _choose_csv_path(self) -> None:
        """CSV 保存先をダイアログから選ばせる。"""
        host = self._controller_host()
        path = filedialog.asksaveasfilename(
            initialdir=host.output_dir.get() or str(Path.cwd()),
            defaultextension='.csv',
            filetypes=[(t('filetype_csv_files'), '*.csv'), (t('filetype_all_files'), '*.*')],
        )
        if path:
            host.csv_path.set(path)

    def _set_status(self, text: str) -> None:
        """ステータスラベルをスレッドセーフに更新する。"""
        host = self._controller_host()
        if threading.current_thread() is threading.main_thread():
            host.status_var.set(text)
            return
        self._schedule_on_ui_thread(lambda: host.status_var.set(text))

    def _append_log(self, msg: str) -> None:
        """ログウィジェットへ 1 行追加し、必要に応じて状態表示も更新する。

        ログは単なる履歴ではなく、終了/失敗のような高水準状態もここから派生させる。
        そのため、backend 側は詳細メッセージだけを流し、最終的な UI 文言は controller が
        組み立てる。
        """
        host = self._controller_host()
        host.log_text.insert('end', msg + '\n')
        host.log_text.see('end')

        if '完了！' in msg:
            current = int(float(host.progress['value']))
            host.status_var.set(t('status_completed_progress', pct=current))
        elif '処理中にエラー発生' in msg:
            host.status_var.set(t('status_failed_see_log'))

    def log(self, msg: str) -> None:
        """どのスレッドからでも安全にログを追記する。"""
        if threading.current_thread() is threading.main_thread():
            self._append_log(msg)
            return
        self._schedule_on_ui_thread(lambda: self._append_log(msg))

    def _update_progress_ui(self, current: int, total: int) -> None:
        """進捗バーと状態文字列を同時に更新する。"""
        host = self._controller_host()
        pct = 100 if total <= 0 else int(current / total * 100)
        host.progress['value'] = pct
        host.status_var.set(t('status_processing', pct=pct, current=current, total=total))
        host.update_idletasks()

    def update_progress(self, current: int, total: int) -> None:
        """進捗更新をメインスレッドへ中継する。"""
        if threading.current_thread() is threading.main_thread():
            self._update_progress_ui(current, total)
            return
        self._schedule_on_ui_thread(lambda: self._update_progress_ui(current, total))

    def _update_stats_ui(self, orig_total: int, out_total: int, saved: int, saved_pct: float) -> None:
        """最終統計表示を画面へ反映する。"""
        host = self._controller_host()
        host.stats_var.set(
            t(
                'stats_summary',
                summary=(
                    f'元合計={human_readable(orig_total)}, '
                    f'出力合計={human_readable(out_total)}, '
                    f'削減={human_readable(saved)} ({saved_pct:.1f}%)'
                ),
            )
        )
        host.status_var.set(t('status_completed_reduction', rate=saved_pct))

    def update_stats(self, orig_total: int, out_total: int, saved: int, saved_pct: float) -> None:
        """統計更新をメインスレッドへ中継する。"""
        if threading.current_thread() is threading.main_thread():
            self._update_stats_ui(orig_total, out_total, saved, saved_pct)
            return
        self._schedule_on_ui_thread(lambda: self._update_stats_ui(orig_total, out_total, saved, saved_pct))

    def _on_progress_event(self, event: ProgressEvent) -> None:
        """backend から届いたイベント種別を UI 更新へ振り分ける。

        backend は UI widget を知らず、`ProgressEvent` という抽象イベントだけを返す。
        controller はそのイベントをログ・進捗・統計・状態文言へ分配し、UI 層と backend 層の
        依存方向を逆転させない接着点になる。
        """
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
            self._set_status(t('status_failed_see_log'))

    def start_compress(self) -> None:
        """入力検証後、圧縮ジョブをバックグラウンドスレッドで開始する。

        WHY:
        - 実行前に UI 側で検出できる問題は先に止め、backend へ不要な失敗ケースを渡さない
        - 開始時ログへ主要設定を出しておくことで、ユーザーとテストの両方が「どの条件で
          走ったか」を後から追える
        - 圧縮本体は同期 API なので、Tk の応答性維持のため controller 側で明示的に
          スレッドへ逃がす
        """
        host = self._controller_host()
        input_dir = host.input_dir.get()
        output_dir = host.output_dir.get()

        fixed_input, fixed_output, conflict = self._check_overlap_and_fix(input_dir, output_dir)
        if conflict:
            host.input_dir.set(fixed_input)
            host.output_dir.set(fixed_output)
            input_dir, output_dir = fixed_input, fixed_output
            self.log(t('log_folders_overlap_reset', input=fixed_input, output=fixed_output))
            messagebox.showwarning(
                t('dlg_folder_overlap_title'),
                t('dlg_folder_overlap_message') + f'\n入力: {host.default_input_dir}\n出力: {host.default_output_dir}',
            )

        if not input_dir or not output_dir:
            self._set_status(t('status_failed_folders_unset'))
            messagebox.showerror(t('dlg_error_title'), t('dlg_folders_not_selected'))
            return
        if not Path(input_dir).is_dir():
            self._set_status(t('status_failed_check_input'))
            messagebox.showerror(t('dlg_error_title'), t('dlg_input_folder_missing'))
            return
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        if host.auto_switch_log_tab.get():
            # 実行直後にログへ移動すると、長時間処理でも「動いているか」が見えやすい。
            host.notebook.select(host.log_tab)

        # 前回実行の表示を残すと新しいジョブ結果と混ざるため、開始時に UI 状態を初期化する。
        host.log_text.delete(1.0, 'end')
        host.progress['value'] = 0
        host.stats_var.set(t('stats_processing'))
        host.status_var.set(t('status_compression_starting'))

        result = build_compression_request(host)
        request = result.request

        self.log(t('log_compression_started', path=input_dir))
        self.log(t('log_output_location', path=output_dir))

        if request.pdf_engine == 'native':
            source_label = t(f'tool_source.{host.capabilities.pngquant_source}')
            pdf_png_method = (
                t('pdf_png_engine.pngquant', source=source_label)
                if host.capabilities.pngquant_available
                else t('pdf_png_engine.pillow', source=source_label)
            )
            self.log(
                t(
                    'log_pdf_native_mode',
                    mode=request.pdf_mode,
                    dpi=request.pdf_dpi,
                    quality=request.pdf_jpeg_quality,
                    png_quality=request.pdf_png_quality,
                    method=pdf_png_method,
                )
            )
        else:
            gs_source = t(f'tool_source.{host.capabilities.ghostscript_source}')
            if request.gs_preset == 'custom':
                self.log(
                    t(
                        'log_pdf_ghostscript_custom',
                        source=gs_source,
                        dpi=request.gs_custom_dpi,
                        use_ll=host.gs_use_lossless.get(),
                    )
                )
            else:
                self.log(
                    t(
                        'log_pdf_ghostscript_preset',
                        source=gs_source,
                        preset=request.gs_preset,
                        use_ll=host.gs_use_lossless.get(),
                    )
                )

        self.log(
            t(
                'log_image_settings',
                jpg_q=request.jpg_quality,
                png_q=request.png_quality,
                use_pq=request.use_pngquant,
                pngquant_source=t(f'tool_source.{host.capabilities.pngquant_source}'),
            )
        )
        if host.resize_enabled.get():
            self.log(t('log_resize_settings', config=result.resize_config))

        self._set_status(t('status_processing', pct=0, current=0, total=0))

        # backend は同期処理なので、UI を止めないよう専用スレッドへ逃がす。
        thread = threading.Thread(
            target=run_compression_request,
            kwargs={'request': request, 'event_callback': self._on_progress_event},
            daemon=True,
        )
        host.threads.append(thread)
        thread.start()

    def cleanup_input(self) -> None:
        """入力フォルダの対象拡張子を確認ダイアログ付きで削除する。

        クリーンアップは取り消しできないため、削除対象数と拡張子を先に見せてから別
        スレッドで実行する。圧縮と同じく、I/O で UI を固めないことを優先する。
        """
        host = self._controller_host()
        input_dir = host.input_dir.get()
        if not input_dir or not Path(input_dir).exists():
            messagebox.showerror(t('dlg_error_title'), t('dlg_input_folder_not_set'))
            return

        count = count_target_files(input_dir, INPUT_DIR_CLEANUP_EXTENSIONS)
        exts = ', '.join(sorted(INPUT_DIR_CLEANUP_EXTENSIONS))
        if host.play_cleanup_sound.get():
            play_sound(SOUNDS_DIR / 'warning.wav')
        if messagebox.askyesno(
            t('dlg_cleanup_confirm_title'),
            t('dlg_cleanup_input_confirm') + '\n\n'
            + t('dlg_cleanup_extensions_label') + f'\n{exts}\n\n'
            + t('dlg_cleanup_file_count_label') + f'\n{t("dlg_cleanup_file_count_text", count=count)}\n\n'
            + t('dlg_cleanup_warning_subfolders'),
        ):
            self.log(t('log_input_cleanup_started', exts=exts))
            # 削除処理も I/O 待ちがあるため、UI 凍結を避けて別スレッド化する。
            thread = threading.Thread(
                target=cleanup_folder,
                args=(input_dir, self.log, t('cleanup_target_input'), INPUT_DIR_CLEANUP_EXTENSIONS),
                kwargs={'log_language': host.ui_language.get()},
                daemon=True,
            )
            host.threads.append(thread)
            thread.start()

    def cleanup_output(self) -> None:
        """出力フォルダの成果物とログを確認ダイアログ付きで削除する。

        出力側は生成物と CSV が混在するため、入力側とは別の対象拡張子集合で確認する。
        """
        host = self._controller_host()
        output_dir = host.output_dir.get()
        if not output_dir or not Path(output_dir).exists():
            messagebox.showerror(t('dlg_error_title'), t('dlg_output_folder_missing'))
            return

        count = count_target_files(output_dir, OUTPUT_DIR_CLEANUP_EXTENSIONS)
        exts = ', '.join(sorted(OUTPUT_DIR_CLEANUP_EXTENSIONS))
        if host.play_cleanup_sound.get():
            play_sound(SOUNDS_DIR / 'warning.wav')
        if messagebox.askyesno(
            t('dlg_cleanup_confirm_title'),
            t('dlg_cleanup_output_confirm') + '\n\n'
            + t('dlg_cleanup_extensions_label') + f'\n{exts}\n\n'
            + t('dlg_cleanup_file_count_label') + f'\n{t("dlg_cleanup_file_count_text", count=count)}\n\n'
            + t('dlg_cleanup_warning_subfolders'),
        ):
            self.log(t('log_output_cleanup_started', exts=exts))
            thread = threading.Thread(
                target=cleanup_folder,
                args=(output_dir, self.log, t('cleanup_target_output'), OUTPUT_DIR_CLEANUP_EXTENSIONS),
                kwargs={'log_language': host.ui_language.get()},
                daemon=True,
            )
            host.threads.append(thread)
            thread.start()

    def on_exit(self) -> None:
        """処理中スレッドの有無を確認してからアプリを終了する。

        daemon thread なので強制終了自体はできるが、ユーザーが長時間処理を誤って閉じない
        よう確認を挟む。
        """
        host = self._controller_host()
        if any(thread.is_alive() for thread in host.threads):
            if not messagebox.askyesno(t('dlg_exit_confirm_title'), t('dlg_exit_confirm_message')):
                return
        host.destroy()
