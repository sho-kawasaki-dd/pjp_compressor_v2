from __future__ import annotations

"""controller mixin の UI 制御契約を固定する integration test 群。

Tk 本体を起動せずに、Dummy host と widget を使って state machine、ログ反映、
スレッド橋渡し、設定永続化のつなぎ込みを検証する。
"""

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

import frontend.i18n as i18n
import frontend.ui_tkinter_controller as controller_module
from backend.contracts import CapabilityReport, JobControl, ProgressEvent
from frontend.ui_tkinter_controller import TkUiControllerMixin


pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def load_japanese_locale() -> None:
    i18n.load('ja')


class DummyVar:
    """controller/mapping が期待する最小限の variable 互換。"""

    def __init__(self, value):
        self._value = value

    def get(self):
        return self._value

    def set(self, value):
        self._value = value


class DummyWidget:
    """`config` と pack 系だけを持つ簡易 widget。"""

    def __init__(self):
        self.state = None
        self.packed = False
        self.text = None

    def config(self, state=None, text=None):
        if state is not None:
            self.state = state
        if text is not None:
            self.text = text

    def pack(self, **_kwargs):
        self.packed = True

    def pack_forget(self):
        self.packed = False


class DummyText:
    """ログタブの Text widget を置き換える記録用ダミー。"""

    def __init__(self):
        self.lines: list[str] = []
        self.deleted = False

    def insert(self, _index, text):
        self.lines.append(text)

    def see(self, _index):
        return None

    def delete(self, _start, _end):
        self.deleted = True
        self.lines.clear()


class DummyNotebook:
    """選択タブだけ追跡する notebook ダミー。"""

    def __init__(self):
        self.selected = None

    def select(self, tab):
        self.selected = tab


class DummyProgressbar(dict):
    """辞書アクセスされる Progressbar の代替。"""

    pass


class DummyThread:
    """バックグラウンド起動の意図だけを観測する thread ダミー。"""

    def __init__(self, *, target, args=(), kwargs=None, daemon):
        self.target = target
        self.args = args
        self.kwargs = kwargs or {}
        self.daemon = daemon
        self.started = False

    def start(self):
        self.started = True

    def is_alive(self):
        return self.started


@dataclass
class DummyRequest:
    """controller から runner へ渡る request の最小表現。"""

    input_dir: str
    output_dir: str
    pdf_engine: str = 'native'
    pdf_mode: str = 'both'
    pdf_dpi: int = 144
    pdf_jpeg_quality: int = 70
    pdf_png_quality: int = 60
    gs_preset: str = '/screen'
    gs_custom_dpi: int | None = None
    jpg_quality: int = 70
    png_quality: int = 70
    use_pngquant: bool = True
    zip_output_enabled: bool = False
    debug_mode: bool = True


class ControllerHost(TkUiControllerMixin):
    """TkUiControllerMixin が依存する属性をまとめた host ダミー。"""

    def __init__(self, tmp_path: Path):
        # pngquant 未検出を既定にして、PDF PNG フォールバック UI の既定分岐を直接検証する。
        self.capabilities = CapabilityReport(True, True, 'C:/gs.exe', None, ghostscript_source='system', pngquant_source='unavailable')
        self.default_input_dir = str(tmp_path / 'default_input')
        self.default_output_dir = str(tmp_path / 'default_output')
        self.input_dir = DummyVar('')
        self.output_dir = DummyVar('')
        self.pdf_engine = DummyVar('native')
        self.pdf_mode = DummyVar('both')
        self.pdf_dpi = DummyVar(144)
        self.pdf_jpeg_quality = DummyVar(70)
        self.pdf_png_quality = DummyVar(60)
        self.gs_preset = DummyVar('/screen')
        self.gs_custom_dpi = DummyVar(150)
        self.gs_use_lossless = DummyVar(True)
        self.jpg_quality = DummyVar(70)
        self.png_quality = DummyVar(70)
        self.use_pngquant = DummyVar(True)
        self.resize_enabled = DummyVar(False)
        self.auto_switch_log_tab = DummyVar(True)
        self.play_startup_sound = DummyVar(True)
        self.play_cleanup_sound = DummyVar(True)
        self.ui_language = DummyVar('ja')
        self.status_var = DummyVar('待機中')
        self.stats_var = DummyVar('')
        self.pdf_engine_status_var = DummyVar('')
        self.notebook = DummyNotebook()
        self.app_settings_tab = object()
        self.log_tab = object()
        self.log_text = DummyText()
        self.progress = DummyProgressbar(value=0)
        self.threads: list[DummyThread] = []
        self.tk = SimpleNamespace(splitlist=lambda data: [data])
        self.native_frame = DummyWidget()
        self.gs_frame = DummyWidget()
        self.native_rb = DummyWidget()
        self.gs_rb = DummyWidget()
        self._native_lossy_widgets = [DummyWidget()]
        self._native_png_quality_widgets = [DummyWidget()]
        self.dpi_scale = DummyWidget()
        self.jpeg_q_scale = DummyWidget()
        self.pdf_png_q_scale = DummyWidget()
        self.jpeg_note_label = DummyWidget()
        self.pdf_png_method_label = DummyWidget()
        self.pdf_png_fallback_note_label = DummyWidget()
        self.png_engine_note_label = DummyWidget()
        self._native_lossless_widgets = [DummyWidget()]
        self._gs_custom_dpi_widgets = [DummyWidget()]
        self._gs_lossless_widgets = [DummyWidget()]
        self.resize_width_entry = DummyWidget()
        self.resize_height_entry = DummyWidget()
        self.resize_keep_aspect_chk = DummyWidget()
        self.resize_mode_manual_rb = DummyWidget()
        self.resize_mode_long_rb = DummyWidget()
        self.long_edge_combo = DummyWidget()
        self.extract_zip = DummyVar(True)
        self.zip_output_enabled = DummyVar(False)
        self.zip_output_check = DummyWidget()
        self.video_enabled = DummyVar(True)
        self.video_quality = DummyVar(75)
        self.video_codec = DummyVar('libx264')
        self.video_preset = DummyVar('medium')
        self.video_audio_mode = DummyVar('copy')
        self.video_max_long_edge = DummyVar('0')
        self.video_engine_status_var = DummyVar('')
        self.video_enable_check = DummyWidget()
        self.video_quality_scale = DummyWidget()
        self.video_quality_value_label = DummyWidget()
        self.video_h264_rb = DummyWidget()
        self.video_h265_rb = DummyWidget()
        self.video_h265_note_label = DummyWidget()
        self.video_preset_combo = DummyWidget()
        self.video_audio_combo = DummyWidget()
        self.video_long_edge_combo = DummyWidget()
        self._video_widgets = [self.video_quality_scale, self.video_h264_rb]
        self._video_combo_widgets = [self.video_preset_combo, self.video_audio_combo, self.video_long_edge_combo]
        self.start_button = DummyWidget()
        self.stop_button = DummyWidget()
        self.cleanup_input_button = DummyWidget()
        self.cleanup_output_button = DummyWidget()
        self.destroyed = False
        self.defer_after = False
        self.pending_after: list[tuple[object, tuple]] = []

    def after(self, _ms, func=None, *args):
        if func is not None:
            if self.defer_after:
                self.pending_after.append((func, args))
            else:
                func(*args)
        return None

    def update_idletasks(self):
        return None

    def destroy(self):
        self.destroyed = True
        return None


def test_check_overlap_and_fix_uses_default_dirs(tmp_path: Path) -> None:
    host = ControllerHost(tmp_path)

    input_dir = tmp_path / 'same'
    output_dir = input_dir / 'child'
    output_dir.mkdir(parents=True)

    fixed_input, fixed_output, conflict = host._check_overlap_and_fix(str(input_dir), str(output_dir))

    assert conflict is True
    assert fixed_input == host.default_input_dir
    assert fixed_output == host.default_output_dir


def test_on_progress_event_routes_error_to_log_and_status(tmp_path: Path) -> None:
    host = ControllerHost(tmp_path)

    host._on_progress_event(ProgressEvent(kind='error', message='bad'))

    assert any('bad' in line for line in host.log_text.lines)
    assert host.status_var.get() == '失敗（詳細はログ）'


def test_append_log_does_not_infer_status_from_message_text(tmp_path: Path) -> None:
    host = ControllerHost(tmp_path)

    host._append_log('完了！')
    host._append_log('処理中にエラー発生')

    assert host.status_var.get() == '待機中'


def test_start_compress_spawns_background_runner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    host = ControllerHost(tmp_path)
    input_dir = tmp_path / 'input'
    output_dir = tmp_path / 'output'
    input_dir.mkdir()
    host.input_dir.set(str(input_dir))
    host.output_dir.set(str(output_dir))

    built_request = DummyRequest(str(input_dir), str(output_dir), debug_mode=True)
    monkeypatch.setattr(
        controller_module,
        'build_compression_request',
        lambda _host: SimpleNamespace(request=built_request, resize_config=False),
    )
    monkeypatch.setattr(
        controller_module,
        'messagebox',
        SimpleNamespace(showwarning=lambda *args, **kwargs: None, showerror=lambda *args, **kwargs: None),
    )
    monkeypatch.setattr(controller_module.threading, 'Thread', DummyThread)

    # UI を即時ブロックしないこと自体が controller の重要責務なので、Thread 起動を確認する。
    host.start_compress()

    assert host.notebook.selected is host.log_tab
    assert host.progress['value'] == 0
    assert host.stats_var.get() == '統計: 処理中...'
    assert len(host.threads) == 1
    assert host.threads[0].started is True
    assert host.threads[0].kwargs['request'].debug_mode is True


def test_update_pdf_controls_disables_pdf_png_slider_without_pngquant(tmp_path: Path) -> None:
    host = ControllerHost(tmp_path)

    host._update_pdf_controls()

    assert all(widget.state == 'disabled' for widget in host._native_png_quality_widgets)
    assert host.pdf_png_q_scale.state == 'disabled'
    assert host.pdf_png_method_label.packed is True
    assert host.pdf_png_method_label.text == 'PNG圧縮エンジン: Pillow 256色固定 (pngquant:未検出)'
    assert host.pdf_png_fallback_note_label.packed is True
    assert host.jpeg_note_label.packed is True
    assert host.png_engine_note_label.text == 'PNG圧縮エンジン: Pillow (pngquant:未検出)'


def test_update_pdf_controls_enables_pdf_png_slider_with_pngquant(tmp_path: Path) -> None:
    host = ControllerHost(tmp_path)
    host.capabilities = CapabilityReport(True, True, 'C:/gs.exe', 'C:/pngquant.exe', ghostscript_source='system', pngquant_source='bundled')

    host._update_pdf_controls()

    assert all(widget.state == 'normal' for widget in host._native_png_quality_widgets)
    assert host.pdf_png_q_scale.state == 'normal'
    assert host.pdf_png_method_label.packed is True
    assert host.pdf_png_method_label.text == 'PNG圧縮エンジン: pngquant (bundled)'
    assert host.pdf_png_fallback_note_label.packed is False


def test_update_pdf_controls_hides_pdf_png_method_label_when_lossy_disabled(tmp_path: Path) -> None:
    host = ControllerHost(tmp_path)
    host.pdf_mode.set('lossless')

    host._update_pdf_controls()

    assert host.pdf_png_method_label.packed is False


def test_update_png_engine_labels_tracks_pngquant_checkbox(tmp_path: Path) -> None:
    host = ControllerHost(tmp_path)
    host.capabilities = CapabilityReport(True, True, 'C:/gs.exe', 'C:/pngquant.exe', ghostscript_source='system', pngquant_source='system')

    host.use_pngquant.set(True)
    host._update_png_engine_labels()
    assert host.png_engine_note_label.text == 'PNG圧縮エンジン: pngquant (system)'

    host.use_pngquant.set(False)
    host._update_png_engine_labels()
    assert host.png_engine_note_label.text == 'PNG圧縮エンジン: Pillow (pngquant:system)'


def test_update_zip_output_controls_disables_and_clears_toggle_when_extract_zip_off(tmp_path: Path) -> None:
    host = ControllerHost(tmp_path)
    host.extract_zip.set(False)
    host.zip_output_enabled.set(True)

    host._update_zip_output_controls()

    assert host.zip_output_enabled.get() is False
    assert host.zip_output_check.state == 'disabled'


def test_update_zip_output_controls_enables_toggle_when_extract_zip_on(tmp_path: Path) -> None:
    host = ControllerHost(tmp_path)
    host.extract_zip.set(True)

    host._update_zip_output_controls()

    assert host.zip_output_check.state == 'normal'


def test_refresh_pdf_engine_status_shows_tool_sources(tmp_path: Path) -> None:
    host = ControllerHost(tmp_path)
    host.capabilities = CapabilityReport(True, False, 'C:/gs.exe', 'C:/pngquant.exe', ghostscript_source='bundled', pngquant_source='system')

    host._refresh_pdf_engine_status()

    assert host.pdf_engine_status_var.get() == '（PyMuPDF:OK, pikepdf:なし, GS:bundled, pngquant:system）'


def test_save_app_settings_passes_current_toggle_values(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    host = ControllerHost(tmp_path)
    captured: dict[str, bool | str] = {}

    def fake_save_app_settings(*, language: str, play_startup_sound: bool, play_cleanup_sound: bool) -> bool:
        captured['language'] = language
        captured['play_startup_sound'] = play_startup_sound
        captured['play_cleanup_sound'] = play_cleanup_sound
        return True

    host.play_startup_sound.set(False)
    host.play_cleanup_sound.set(True)
    host.ui_language.set('en')
    monkeypatch.setattr(controller_module, 'save_app_settings', fake_save_app_settings)

    saved = host._save_app_settings()

    assert saved is True
    assert captured == {
        'language': 'en',
        'play_startup_sound': False,
        'play_cleanup_sound': True,
    }


def test_cleanup_input_skips_warning_sound_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    host = ControllerHost(tmp_path)
    input_dir = tmp_path / 'input'
    input_dir.mkdir()
    host.input_dir.set(str(input_dir))
    host.play_cleanup_sound.set(False)
    played: list[Path] = []

    monkeypatch.setattr(controller_module, 'play_sound', lambda sound_file: played.append(Path(sound_file)))
    monkeypatch.setattr(controller_module.messagebox, 'askyesno', lambda *args, **kwargs: False)

    host.cleanup_input()

    assert played == []


def test_cleanup_input_passes_stable_cleanup_target_key(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    host = ControllerHost(tmp_path)
    input_dir = tmp_path / 'input'
    input_dir.mkdir()
    host.input_dir.set(str(input_dir))
    host.play_cleanup_sound.set(False)

    monkeypatch.setattr(controller_module.messagebox, 'askyesno', lambda *args, **kwargs: True)
    monkeypatch.setattr(controller_module, 'play_sound', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(controller_module.threading, 'Thread', DummyThread)

    host.cleanup_input()

    assert len(host.threads) == 1
    thread = host.threads[0]
    assert thread.kwargs['log_language'] == 'ja'
    assert thread.args[2] == 'cleanup_target_input'


def test_cleanup_output_plays_warning_sound_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    host = ControllerHost(tmp_path)
    output_dir = tmp_path / 'output'
    output_dir.mkdir()
    host.output_dir.set(str(output_dir))
    host.play_cleanup_sound.set(True)
    played: list[Path] = []

    monkeypatch.setattr(controller_module, 'play_sound', lambda sound_file: played.append(Path(sound_file)))
    monkeypatch.setattr(controller_module.messagebox, 'askyesno', lambda *args, **kwargs: False)

    host.cleanup_output()

    assert played == [controller_module.SOUNDS_DIR / 'warning.wav']


# ---------------------------------------------------------------------------
# 動画 UI・停止・終了処理
# ---------------------------------------------------------------------------


class SyncThread:
    """start() で即座に target を実行する thread ダミー（実行後は非 alive）。"""

    def __init__(self, *, target, args=(), kwargs=None, daemon=False):
        self.target = target
        self.args = args
        self.kwargs = kwargs or {}

    def start(self):
        self.target(*self.args, **self.kwargs)

    def is_alive(self):
        return False


def _video_capabilities(*, hevc: bool = True, ffmpeg: bool = True, ffprobe: bool = True) -> CapabilityReport:
    encoders = frozenset({'libx264', 'aac'} | ({'libx265'} if hevc else set()))
    return CapabilityReport(
        True,
        True,
        'C:/gs.exe',
        None,
        ghostscript_source='system',
        pngquant_source='unavailable',
        ffmpeg_path='C:/ffmpeg.exe' if ffmpeg else None,
        ffmpeg_source='system' if ffmpeg else 'unavailable',
        ffmpeg_encoders=encoders if ffmpeg else frozenset(),
        ffprobe_path='C:/ffprobe.exe' if ffprobe else None,
        ffprobe_source='bundled' if ffprobe else 'unavailable',
    )


def _prepare_running_host(host: ControllerHost) -> JobControl:
    control = JobControl()
    host._job_control = control
    host._job_running = True
    return control


def _patch_messagebox(monkeypatch: pytest.MonkeyPatch) -> dict[str, list]:
    calls: dict[str, list] = {'warning': [], 'error': [], 'ask': []}
    monkeypatch.setattr(
        controller_module,
        'messagebox',
        SimpleNamespace(
            showwarning=lambda *a, **k: calls['warning'].append(a),
            showerror=lambda *a, **k: calls['error'].append(a),
            askyesno=lambda *a, **k: calls['ask'].append(a) or True,
        ),
    )
    return calls


def test_video_events_compose_status_with_overall_progress(tmp_path: Path) -> None:
    host = ControllerHost(tmp_path)

    host._on_progress_event(ProgressEvent(kind='progress', current=1, total=4))
    assert host.status_var.get() == '処理中 25% (1/4)'

    host._on_progress_event(ProgressEvent(kind='video_progress', message='a.mov', video_phase='started'))
    assert host.status_var.get() == '処理中 25% (1/4) | 動画: a.mov'

    host._on_progress_event(ProgressEvent(kind='video_progress', message='a.mov', current=40, video_phase='updated'))
    assert host.status_var.get() == '処理中 25% (1/4) | 動画: a.mov (40%)'

    # 割合不明の更新は表示を消さず、割合だけを外す。
    host._on_progress_event(ProgressEvent(kind='video_progress', message='a.mov', video_phase='updated'))
    assert host.status_var.get() == '処理中 25% (1/4) | 動画: a.mov'

    # 画像の完了通知でも動画表示は残る。
    host._on_progress_event(ProgressEvent(kind='video_progress', message='a.mov', current=60, video_phase='updated'))
    host._on_progress_event(ProgressEvent(kind='progress', current=2, total=4))
    assert host.status_var.get() == '処理中 50% (2/4) | 動画: a.mov (60%)'

    host._on_progress_event(ProgressEvent(kind='video_progress', message='a.mov', video_phase='finished'))
    assert host.status_var.get() == '処理中 50% (2/4)'


def test_start_compress_locks_controls_and_passes_job_control(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    host = ControllerHost(tmp_path)
    input_dir = tmp_path / 'input'
    input_dir.mkdir()
    host.input_dir.set(str(input_dir))
    host.output_dir.set(str(tmp_path / 'output'))
    calls = _patch_messagebox(monkeypatch)
    monkeypatch.setattr(
        controller_module,
        'build_compression_request',
        lambda _host: SimpleNamespace(request=DummyRequest(str(input_dir), str(tmp_path / 'output')), resize_config=False),
    )
    monkeypatch.setattr(controller_module.threading, 'Thread', DummyThread)

    host.start_compress()

    assert host._job_running is True
    assert isinstance(host.threads[0].kwargs['job_control'], JobControl)
    assert host.threads[0].kwargs['job_control'] is host._job_control
    assert host.start_button.state == 'disabled'
    assert host.stop_button.state == 'normal'
    assert host.cleanup_input_button.state == 'disabled'
    assert host.cleanup_output_button.state == 'disabled'

    # 実行中の再開始・クリーンアップは拒否して通知する。
    host.start_compress()
    host.cleanup_input()
    host.cleanup_output()
    assert len(host.threads) == 1
    assert len(calls['warning']) == 3


@pytest.mark.parametrize(
    'event',
    [
        ProgressEvent(kind='stats', orig_total=10, out_total=5, saved=5, saved_pct=50.0),
        ProgressEvent(kind='error', message='boom'),
        ProgressEvent(kind='cancelled', message='中断メッセージ', orig_total=10, out_total=8, saved=2, saved_pct=20.0),
    ],
)
def test_terminal_events_restore_controls_and_clear_video_state(tmp_path: Path, event: ProgressEvent) -> None:
    host = ControllerHost(tmp_path)
    _prepare_running_host(host)
    host._update_action_states()
    host._on_progress_event(ProgressEvent(kind='video_progress', message='a.mov', current=10, video_phase='updated'))

    host._on_progress_event(event)

    assert host._job_running is False
    assert host._job_control is None
    assert host._video_progress is None
    assert host.start_button.state == 'normal'
    assert host.stop_button.state == 'disabled'
    assert host.cleanup_input_button.state == 'normal'
    assert host.cleanup_output_button.state == 'normal'


def test_cancelled_event_shows_partial_stats_without_completion_text(tmp_path: Path) -> None:
    host = ControllerHost(tmp_path)
    _prepare_running_host(host)

    host._on_progress_event(
        ProgressEvent(kind='cancelled', message='中断メッセージ', orig_total=10, out_total=8, saved=2, saved_pct=20.0)
    )

    assert host.status_var.get() == '中断しました（部分集計はログ・統計を参照）'
    assert '完了' not in host.status_var.get()
    assert any('中断メッセージ' in line for line in host.log_text.lines)
    assert '20.0%' in host.stats_var.get()


def test_finish_job_ui_ignores_stale_control(tmp_path: Path) -> None:
    host = ControllerHost(tmp_path)
    old_control = JobControl()
    new_control = _prepare_running_host(host)

    host._finish_job_ui(old_control)

    assert host._job_running is True
    assert host._job_control is new_control


def test_stop_compress_disables_stop_button_and_spawns_stop_worker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    host = ControllerHost(tmp_path)
    control = _prepare_running_host(host)
    host._update_action_states()
    monkeypatch.setattr(controller_module.threading, 'Thread', DummyThread)

    host.stop_compress()
    host.stop_compress()  # 2 回目は無視される

    assert host._stopping is True
    assert host.stop_button.state == 'disabled'
    assert host.status_var.get().startswith('停止中')
    assert host._stop_thread is not None
    assert host._stop_thread.target == host._stop_worker
    assert host._stop_thread.args == (control,)

    # 停止中は進捗イベントで状態表示を上書きしない。
    host._on_progress_event(ProgressEvent(kind='progress', current=1, total=2))
    assert host.status_var.get().startswith('停止中')


def test_stop_worker_requests_cancel_and_terminates_processes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    host = ControllerHost(tmp_path)
    control = _prepare_running_host(host)
    terminated: list[JobControl] = []
    monkeypatch.setattr(
        controller_module,
        'terminate_active_video_processes',
        lambda ctl, **_kwargs: terminated.append(ctl),
    )

    host._stop_worker(control)

    assert control.is_cancelled is True
    assert terminated == [control]
    assert host._stop_error is None


def test_stop_worker_failure_is_reported_and_allows_retry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    host = ControllerHost(tmp_path)
    control = _prepare_running_host(host)
    host._stopping = True

    def failing_terminate(_control, **_kwargs):
        raise RuntimeError('cannot kill')

    monkeypatch.setattr(controller_module, 'terminate_active_video_processes', failing_terminate)

    host._stop_worker(control)

    assert host._stop_error == 'cannot kill'
    assert any('cannot kill' in line for line in host.log_text.lines)
    assert host._stopping is False
    assert host.stop_button.state == 'normal'


def test_on_exit_without_work_destroys_immediately(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    host = ControllerHost(tmp_path)
    calls = _patch_messagebox(monkeypatch)

    host.on_exit()

    assert host.destroyed is True
    assert calls['ask'] == []


def test_on_exit_declined_keeps_running_job(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    host = ControllerHost(tmp_path)
    _prepare_running_host(host)
    _patch_messagebox(monkeypatch)
    monkeypatch.setattr(controller_module.messagebox, 'askyesno', lambda *a, **k: False)

    host.on_exit()

    assert host.destroyed is False
    assert host._exit_requested is False
    assert host._stopping is False


def test_on_exit_stops_job_and_destroys_only_after_worker_finishes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    host = ControllerHost(tmp_path)
    host.defer_after = True
    control = _prepare_running_host(host)
    _patch_messagebox(monkeypatch)
    terminated: list[JobControl] = []
    monkeypatch.setattr(controller_module.threading, 'Thread', SyncThread)
    monkeypatch.setattr(
        controller_module,
        'terminate_active_video_processes',
        lambda ctl, **_kwargs: terminated.append(ctl),
    )

    host.on_exit()

    # 停止処理は停止ボタンと共通で、ワーカーが残っている間は閉じない。
    assert terminated == [control]
    assert control.is_cancelled is True
    assert host._exit_requested is True
    assert host.start_button.state == 'disabled'
    assert host.stop_button.state == 'disabled'
    assert host.destroyed is False
    assert len(host.pending_after) == 1

    # ワーカーの終端が届くまで再スケジュールされ続ける。
    func, args = host.pending_after.pop()
    func(*args)
    assert host.destroyed is False
    assert len(host.pending_after) == 1

    host._on_progress_event(ProgressEvent(kind='cancelled', message='x'))
    func, args = host.pending_after.pop()
    func(*args)
    assert host.destroyed is True


def test_on_exit_aborts_when_stop_fails(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    host = ControllerHost(tmp_path)
    host.defer_after = True
    _prepare_running_host(host)
    calls = _patch_messagebox(monkeypatch)
    monkeypatch.setattr(controller_module.threading, 'Thread', SyncThread)

    def failing_terminate(_control, **_kwargs):
        raise RuntimeError('cannot kill')

    monkeypatch.setattr(controller_module, 'terminate_active_video_processes', failing_terminate)

    host.on_exit()

    assert host.destroyed is False
    assert host._exit_requested is False
    assert len(calls['error']) == 1
    assert host.stop_button.state == 'normal'


def test_run_compression_thread_restores_state_even_without_terminal_event(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    host = ControllerHost(tmp_path)
    control = _prepare_running_host(host)
    seen: dict[str, object] = {}

    def fake_runner(request, event_callback, job_control=None):
        seen['control'] = job_control

    monkeypatch.setattr(controller_module, 'run_compression_request', fake_runner)

    host._run_compression_thread(request=object(), event_callback=host._on_progress_event, job_control=control)

    assert seen['control'] is control
    assert host._job_running is False
    assert host.start_button.state == 'normal'


def test_update_video_controls_disables_everything_when_tools_unavailable(tmp_path: Path) -> None:
    host = ControllerHost(tmp_path)
    host.capabilities = _video_capabilities(ffmpeg=False)

    host._update_video_controls()
    host._refresh_video_engine_status()

    assert host.video_enable_check.state == 'disabled'
    assert all(widget.state == 'disabled' for widget in host._video_widgets)
    assert all(combo.state == 'disabled' for combo in host._video_combo_widgets)
    assert host.video_h265_rb.state == 'disabled'
    assert 'ffmpeg が見つかりません' in host.video_engine_status_var.get()


def test_update_video_controls_disables_only_h265_without_libx265(tmp_path: Path) -> None:
    host = ControllerHost(tmp_path)
    host.capabilities = _video_capabilities(hevc=False)
    host.video_codec.set('libx265')

    host._update_video_controls()
    host._refresh_video_engine_status()

    assert host.video_codec.get() == 'libx264'
    assert host.video_h265_rb.state == 'disabled'
    assert host.video_h265_note_label.packed is True
    assert host.video_h264_rb.state == 'normal'
    assert host.video_preset_combo.state == 'readonly'
    assert 'H.265:不可' in host.video_engine_status_var.get()


def test_update_video_controls_follows_enable_toggle(tmp_path: Path) -> None:
    host = ControllerHost(tmp_path)
    host.capabilities = _video_capabilities()

    host.video_enabled.set(False)
    host._update_video_controls()
    assert host.video_h265_rb.state == 'disabled'
    assert all(combo.state == 'disabled' for combo in host._video_combo_widgets)
    assert host.video_enable_check.state == 'normal'

    host.video_enabled.set(True)
    host._update_video_controls()
    assert host.video_h265_rb.state == 'normal'
    assert all(combo.state == 'readonly' for combo in host._video_combo_widgets)
    assert all(widget.state == 'normal' for widget in host._video_widgets)
    assert host.video_h265_note_label.packed is False
    assert host.video_quality_value_label.text == '75（CRF 24）'
    host._refresh_video_engine_status()
    assert host.video_engine_status_var.get() == '（ffmpeg:system, ffprobe:bundled, H.265:可）'


def test_cleanup_output_takes_output_lock_and_skips_when_in_use(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    host = ControllerHost(tmp_path)
    cleaned: list[str] = []
    released: list[bool] = []
    monkeypatch.setattr(controller_module, 'cleanup_folder', lambda target, *a, **k: cleaned.append(target))

    class FakeLock:
        def release(self):
            released.append(True)

    monkeypatch.setattr(controller_module, 'acquire_output_lock', lambda _target: FakeLock())
    host._cleanup_running = True
    host._run_cleanup_thread(str(tmp_path), host.log, 'cleanup_target_output', {'.mp4'}, lock_output=True)

    assert cleaned == [str(tmp_path)]
    assert released == [True]
    assert host._cleanup_running is False

    def busy(_target):
        raise controller_module.OutputLockError('busy')

    monkeypatch.setattr(controller_module, 'acquire_output_lock', busy)
    cleaned.clear()
    host._run_cleanup_thread(str(tmp_path), host.log, 'cleanup_target_output', {'.mp4'}, lock_output=True)

    assert cleaned == []
    assert any('使用中' in line for line in host.log_text.lines)


def test_start_compress_is_rejected_during_cleanup(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    host = ControllerHost(tmp_path)
    host._cleanup_running = True
    calls = _patch_messagebox(monkeypatch)
    monkeypatch.setattr(controller_module.threading, 'Thread', DummyThread)

    host.start_compress()

    assert host.threads == []
    assert len(calls['warning']) == 1
