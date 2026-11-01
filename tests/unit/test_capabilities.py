from __future__ import annotations

"""任意依存の検出順序と劣化起動判定を確認する unit test。"""

from pathlib import Path
import subprocess

import pytest

from backend import capabilities
from shared import runtime_paths


pytestmark = pytest.mark.unit


def test_detect_ghostscript_prefers_system_over_bundled(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    bundled = tmp_path / 'vendor' / 'Ghostscript-windows' / 'bin' / 'gswin64c.exe'
    bundled.parent.mkdir(parents=True)
    bundled.write_text('stub', encoding='utf-8')

    lookup = {
        'gswin64c': 'C:/Ghostscript/bin/gswin64c.exe',
        'gswin32c': None,
        'gs': 'C:/Ghostscript/bin/gs.exe',
    }
    monkeypatch.setattr(runtime_paths, 'APP_BASE_DIR', tmp_path)
    monkeypatch.setattr(runtime_paths.shutil, 'which', lookup.get)

    resolution = capabilities._detect_ghostscript()

    assert resolution.path == 'C:/Ghostscript/bin/gswin64c.exe'
    assert resolution.source == 'system'


def test_detect_pngquant_falls_back_to_bundled(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    bundled = tmp_path / 'vendor' / 'pngquant-windows' / 'pngquant' / 'pngquant.exe'
    bundled.parent.mkdir(parents=True)
    bundled.write_text('stub', encoding='utf-8')

    monkeypatch.setattr(runtime_paths, 'APP_BASE_DIR', tmp_path)
    monkeypatch.setattr(runtime_paths, 'RESOURCE_BASE_DIR', tmp_path)
    monkeypatch.setattr(runtime_paths.shutil, 'which', lambda _name: None)

    resolution = capabilities._detect_pngquant()

    assert resolution.path == str(bundled.resolve())
    assert resolution.source == 'bundled'


def test_detect_capabilities_handles_missing_optional_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_import(name: str):
        if name == 'fitz':
            return object()
        raise ImportError(name)

    monkeypatch.setattr(capabilities.importlib, 'import_module', fake_import)
    monkeypatch.setattr(runtime_paths.shutil, 'which', lambda name: 'C:/tools/pngquant.exe' if name == 'pngquant' else None)
    monkeypatch.setattr(runtime_paths, '_resolve_bundled_executable', lambda _candidates: None)

    report = capabilities.detect_capabilities()

    assert report.fitz_available is True
    assert report.pikepdf_available is False
    assert report.ghostscript_available is False
    assert report.pngquant_available is True
    assert report.native_pdf_available is True
    assert report.ghostscript_source == 'unavailable'
    assert report.pngquant_source == 'system'
    assert report.ffmpeg_source == 'unavailable'
    assert report.video_available is False


ENCODERS_OUTPUT = """Encoders:
 V..... = Video
 ------
 V....D libx264              libx264 H.264 / AVC (codec h264)
 V....D libx265              libx265 H.265 / HEVC (codec hevc)
 A....D aac                  AAC (Advanced Audio Coding)
 A....D libmp3lame           libmp3lame MP3
"""


def _completed(returncode: int = 0, stdout: str = '', stderr: str = '') -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def _patch_tools(monkeypatch: pytest.MonkeyPatch, run) -> list[list[str]]:
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append(list(command))
        return run(command, **kwargs)

    monkeypatch.setattr(runtime_paths.shutil, 'which', lambda name: f'C:/ff/{name}.exe' if name in ('ffmpeg', 'ffprobe') else None)
    monkeypatch.setattr(capabilities.subprocess, 'run', fake_run)
    return calls


def test_detect_ffmpeg_collects_encoders_and_caches(monkeypatch: pytest.MonkeyPatch) -> None:
    def run(command, **kwargs):
        assert kwargs['timeout'] == 10
        return _completed(stdout=ENCODERS_OUTPUT if '-encoders' in command else 'ffprobe version 7')

    calls = _patch_tools(monkeypatch, run)

    first = capabilities.detect_capabilities()
    second = capabilities.detect_capabilities()

    assert first.ffmpeg_encoders == frozenset({'libx264', 'aac'})
    assert first.ffmpeg_available and first.ffprobe_available and first.video_available
    assert first.ffmpeg_source == 'system' and first.ffprobe_source == 'system'
    assert second.ffmpeg_path == first.ffmpeg_path
    assert len(calls) == 2  # ffmpeg -encoders と ffprobe -version が各1回だけ


def test_detect_ffmpeg_ignores_hevc_encoders(monkeypatch: pytest.MonkeyPatch) -> None:
    output = ' V....D libx264              libx264 H.264\n V....D libx265              libx265 H.265\n'
    _patch_tools(monkeypatch, lambda command, **kwargs: _completed(stdout=output))

    report = capabilities.detect_capabilities()

    assert report.ffmpeg_available is True
    assert report.ffmpeg_encoders == frozenset({'libx264'})


def test_detect_ffprobe_failure_keeps_sanitized_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    def run(command, **kwargs):
        if '-encoders' in command:
            return _completed(stdout=ENCODERS_OUTPUT)
        return _completed(returncode=1, stderr='C:/ff/ffprobe.exe: bad dll\n')

    _patch_tools(monkeypatch, run)

    report = capabilities.detect_capabilities()

    assert report.ffprobe_path == 'C:/ff/ffprobe.exe'
    assert report.ffprobe_available is False
    assert report.video_available is False
    assert report.ffprobe_detection_error == 'ffprobe.exe: bad dll'
    assert report.ffmpeg_available is True


def test_detect_ffmpeg_start_failure_and_timeout_are_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    def run(command, **kwargs):
        if '-encoders' in command:
            raise OSError('cannot run')
        raise subprocess.TimeoutExpired(command, 10)

    _patch_tools(monkeypatch, run)

    report = capabilities.detect_capabilities()

    assert report.ffmpeg_available is False
    assert 'cannot run' in (report.ffmpeg_detection_error or '')
    assert report.ffmpeg_encoders == frozenset()
    assert 'timed out' in (report.ffprobe_detection_error or '')
    assert report.ffprobe_available is False


def test_ffmpeg_resolves_to_bundled_x264_only_build_when_system_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    bundled = tmp_path / 'vendor' / 'ffmpeg-windows' / 'bin' / 'ffmpeg.exe'
    bundled.parent.mkdir(parents=True)
    bundled.write_text('stub', encoding='utf-8')
    monkeypatch.setattr(runtime_paths, 'APP_BASE_DIR', tmp_path)
    monkeypatch.setattr(runtime_paths, 'RESOURCE_BASE_DIR', tmp_path)
    monkeypatch.setattr(runtime_paths.shutil, 'which', lambda _name: None)

    resolution = runtime_paths.resolve_ffmpeg_executable()

    assert resolution.path == str(bundled.resolve())
    assert resolution.source == 'bundled'


def test_ffprobe_resolves_to_bundled_x264_only_build_when_system_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    bundled = tmp_path / 'vendor' / 'ffmpeg-windows' / 'bin' / 'ffprobe.exe'
    bundled.parent.mkdir(parents=True)
    bundled.write_text('stub', encoding='utf-8')
    monkeypatch.setattr(runtime_paths, 'APP_BASE_DIR', tmp_path)
    monkeypatch.setattr(runtime_paths, 'RESOURCE_BASE_DIR', tmp_path)
    monkeypatch.setattr(runtime_paths.shutil, 'which', lambda _name: None)

    bundled_result = runtime_paths.resolve_ffprobe_executable()
    assert bundled_result.path == str(bundled.resolve())
    assert bundled_result.source == 'bundled'

    monkeypatch.setattr(runtime_paths.shutil, 'which', lambda name: 'C:/system/ffprobe.exe' if name == 'ffprobe' else None)
    system_result = runtime_paths.resolve_ffprobe_executable()
    assert system_result.path == 'C:/system/ffprobe.exe'
    assert system_result.source == 'system'


def test_clearing_video_tool_cache_rechecks_both_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    encoder_output = ENCODERS_OUTPUT

    def run(command, **kwargs):
        return _completed(stdout=encoder_output if '-encoders' in command else 'ffprobe version')

    calls = _patch_tools(monkeypatch, run)
    assert capabilities.detect_capabilities().ffmpeg_encoders == frozenset({'libx264', 'aac'})
    encoder_output = ' V....D libx264 libx264 H.264\n'
    assert capabilities.detect_capabilities().ffmpeg_encoders == frozenset({'libx264', 'aac'})
    assert len(calls) == 2

    capabilities.clear_video_tool_cache()

    assert capabilities.detect_capabilities().ffmpeg_encoders == frozenset({'libx264'})
    assert len(calls) == 4
