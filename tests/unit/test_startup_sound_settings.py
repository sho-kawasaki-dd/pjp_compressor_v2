from __future__ import annotations

"""起動音/通知音の設定が GUI 起動導線へ反映されるか確認する unit test。"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import frontend.bootstrap as bootstrap


pytestmark = pytest.mark.unit


class DummyVar:
    """設定トグル読み出しだけに使う最小 variable ダミー。"""

    def __init__(self, value):
        self._value = value

    def get(self):
        return self._value


class DummyApp:
    """bootstrap が参照する最小限の App 代替。"""

    def __init__(self, play_startup_sound: bool):
        self.play_startup_sound = DummyVar(play_startup_sound)
        self.after_calls: list[int] = []
        self.mainloop_called = False

    def after(self, ms, callback):
        self.after_calls.append(ms)
        callback()

    def lift(self):
        return None

    def focus_force(self):
        return None

    def mainloop(self):
        self.mainloop_called = True


def test_run_tkinter_app_skips_open_window_sound_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    played: list[Path] = []
    app = DummyApp(False)

    monkeypatch.setattr(bootstrap, '_build_startup_splash', lambda _app: None)
    monkeypatch.setattr(sys.modules['frontend.sound_utils'], 'play_sound', lambda sound_file: played.append(Path(sound_file)))
    monkeypatch.setitem(sys.modules, 'frontend.ui_tkinter', SimpleNamespace(App=lambda: app))

    exit_code = bootstrap.run_tkinter_app()

    assert exit_code == 0
    assert played == []
    assert app.mainloop_called is True


def test_get_default_dirs_skips_notice_sound_when_disabled(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pytest.importorskip('tkinterdnd2')
    import frontend.ui_tkinter as ui_module

    desktop_dir = tmp_path / 'Desktop'
    desktop_dir.mkdir()
    played: list[Path] = []

    monkeypatch.setattr(ui_module.os, 'name', 'nt')
    monkeypatch.setattr(ui_module.Path, 'home', staticmethod(lambda: tmp_path))
    monkeypatch.setattr(ui_module, 'load_app_settings', lambda: {'play_startup_sound': False, 'play_cleanup_sound': True})
    monkeypatch.setattr(ui_module, 'play_sound', lambda sound_file: played.append(Path(sound_file)))
    monkeypatch.setattr(ui_module.messagebox, 'askquestion', lambda *args, **kwargs: 'no')

    ui_module.get_default_dirs()

    assert played == []


def test_get_default_dirs_plays_notice_sound_when_enabled(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pytest.importorskip('tkinterdnd2')
    import frontend.ui_tkinter as ui_module

    desktop_dir = tmp_path / 'Desktop'
    desktop_dir.mkdir()
    played: list[Path] = []

    monkeypatch.setattr(ui_module.os, 'name', 'nt')
    monkeypatch.setattr(ui_module.Path, 'home', staticmethod(lambda: tmp_path))
    monkeypatch.setattr(ui_module, 'load_app_settings', lambda: {'play_startup_sound': True, 'play_cleanup_sound': True})
    monkeypatch.setattr(ui_module, 'play_sound', lambda sound_file: played.append(Path(sound_file)))
    monkeypatch.setattr(ui_module.messagebox, 'askquestion', lambda *args, **kwargs: 'no')

    ui_module.get_default_dirs()

    assert played == [ui_module.SOUNDS_DIR / 'notice.wav']