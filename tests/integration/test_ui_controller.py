from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

import frontend.ui_tkinter_controller as controller_module
from backend.contracts import CapabilityReport, ProgressEvent
from frontend.ui_tkinter_controller import TkUiControllerMixin


pytestmark = pytest.mark.integration


class DummyVar:
    def __init__(self, value):
        self._value = value

    def get(self):
        return self._value

    def set(self, value):
        self._value = value


class DummyWidget:
    def __init__(self):
        self.state = None
        self.packed = False

    def config(self, state=None):
        self.state = state

    def pack(self, **_kwargs):
        self.packed = True

    def pack_forget(self):
        self.packed = False


class DummyText:
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
    def __init__(self):
        self.selected = None

    def select(self, tab):
        self.selected = tab


class DummyProgressbar(dict):
    pass


class DummyThread:
    def __init__(self, *, target, kwargs, daemon):
        self.target = target
        self.kwargs = kwargs
        self.daemon = daemon
        self.started = False

    def start(self):
        self.started = True

    def is_alive(self):
        return self.started


@dataclass
class DummyRequest:
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
    debug_mode: bool = True


class ControllerHost(TkUiControllerMixin):
    def __init__(self, tmp_path: Path):
        self.capabilities = CapabilityReport(True, True, 'C:/gs.exe', None)
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
        self.status_var = DummyVar('待機中')
        self.stats_var = DummyVar('')
        self.pdf_engine_status_var = DummyVar('')
        self.notebook = DummyNotebook()
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
        self.pdf_png_fallback_note_label = DummyWidget()
        self._native_lossless_widgets = [DummyWidget()]
        self._gs_custom_dpi_widgets = [DummyWidget()]
        self._gs_lossless_widgets = [DummyWidget()]
        self.resize_width_entry = DummyWidget()
        self.resize_height_entry = DummyWidget()
        self.resize_keep_aspect_chk = DummyWidget()
        self.resize_mode_manual_rb = DummyWidget()
        self.resize_mode_long_rb = DummyWidget()
        self.long_edge_combo = DummyWidget()

    def after(self, _ms, func=None, *args):
        if func is not None:
            func(*args)
        return None

    def update_idletasks(self):
        return None

    def destroy(self):
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
    assert host.pdf_png_fallback_note_label.packed is True
    assert host.jpeg_note_label.packed is True


def test_update_pdf_controls_enables_pdf_png_slider_with_pngquant(tmp_path: Path) -> None:
    host = ControllerHost(tmp_path)
    host.capabilities = CapabilityReport(True, True, 'C:/gs.exe', 'C:/pngquant.exe')

    host._update_pdf_controls()

    assert all(widget.state == 'normal' for widget in host._native_png_quality_widgets)
    assert host.pdf_png_q_scale.state == 'normal'
    assert host.pdf_png_fallback_note_label.packed is False
