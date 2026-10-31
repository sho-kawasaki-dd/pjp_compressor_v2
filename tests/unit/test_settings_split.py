from __future__ import annotations

"""設定分割後も legacy re-export が壊れていないことを確認する unit test。"""

import pytest

import backend.settings as backend_settings
import frontend.settings as frontend_settings
import shared.configs as legacy_configs
import shared.runtime_paths as runtime_paths


pytestmark = pytest.mark.unit


def test_frontend_settings_load_ui_catalogs_from_json() -> None:
    assert frontend_settings.LONG_EDGE_PRESETS[0] == '640'
    assert frontend_settings.LONG_EDGE_PRESETS[-1] == '3840'
    assert not hasattr(frontend_settings, 'PDF_COMPRESS_MODES')
    assert not hasattr(frontend_settings, 'GS_PRESETS')


def test_shared_configs_reexports_split_settings() -> None:
    assert legacy_configs.APP_BASE_DIR == runtime_paths.APP_BASE_DIR
    assert legacy_configs.RESOURCE_BASE_DIR == runtime_paths.RESOURCE_BASE_DIR
    assert legacy_configs.PDF_ALLOWED_MODES == backend_settings.PDF_ALLOWED_MODES
    assert legacy_configs.PDF_LOSSY_DPI_DEFAULT == backend_settings.PDF_LOSSY_DPI_DEFAULT
    assert legacy_configs.PDF_LOSSY_JPEG_QUALITY_DEFAULT == backend_settings.PDF_LOSSY_JPEG_QUALITY_DEFAULT
    assert legacy_configs.PDF_LOSSY_PNG_QUALITY_DEFAULT == backend_settings.PDF_LOSSY_PNG_QUALITY_DEFAULT
    assert legacy_configs.PDF_LOSSLESS_OPTIONS_DEFAULT == backend_settings.PDF_LOSSLESS_OPTIONS_DEFAULT
    assert legacy_configs.GS_DEFAULT_PRESET == backend_settings.GS_DEFAULT_PRESET
    assert legacy_configs.LONG_EDGE_PRESETS == frontend_settings.LONG_EDGE_PRESETS
    assert not hasattr(legacy_configs, 'PDF_COMPRESS_MODES')
    assert not hasattr(legacy_configs, 'GS_PRESETS')
    assert legacy_configs.INPUT_DIR_CLEANUP_EXTENSIONS == frontend_settings.INPUT_DIR_CLEANUP_EXTENSIONS


def test_video_cleanup_extensions_derive_from_backend() -> None:
    assert frontend_settings.VIDEO_CLEANUP_EXTENSIONS == {f'.{ext}' for ext in backend_settings.VIDEO_EXTENSIONS}
    assert frontend_settings.VIDEO_CLEANUP_EXTENSIONS <= frontend_settings.INPUT_DIR_CLEANUP_EXTENSIONS
    assert frontend_settings.VIDEO_CLEANUP_EXTENSIONS <= frontend_settings.OUTPUT_DIR_CLEANUP_EXTENSIONS


def test_aac_bitrate_for_channels() -> None:
    assert backend_settings.aac_bitrate_for_channels(1) == '96k'
    assert backend_settings.aac_bitrate_for_channels(2) == '128k'
    assert backend_settings.aac_bitrate_for_channels(6) == '384k'
    assert backend_settings.aac_bitrate_for_channels(8) == '512k'
    assert backend_settings.aac_bitrate_for_channels(10) is None
    assert backend_settings.aac_bitrate_for_channels(None) is None
    assert backend_settings.aac_bitrate_for_channels(10, '192k') == '192k'


def test_ffmpeg_ffprobe_resolution_order(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    for relative in ('ffmpeg-windows/bin/ffmpeg.exe', 'ffmpeg-windows/ffprobe.exe'):
        target = tmp_path / 'vendor' / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('stub', encoding='utf-8')
    monkeypatch.setattr(runtime_paths, 'APP_BASE_DIR', tmp_path)
    monkeypatch.setattr(runtime_paths, 'RESOURCE_BASE_DIR', tmp_path)

    monkeypatch.setattr(runtime_paths.shutil, 'which', lambda name: 'C:/sys/ffmpeg.exe' if name == 'ffmpeg' else None)
    assert runtime_paths.resolve_ffmpeg_executable().source == 'system'
    ffprobe = runtime_paths.resolve_ffprobe_executable()
    assert ffprobe.source == 'bundled' and ffprobe.path.endswith('ffprobe.exe')

    monkeypatch.setattr(runtime_paths, 'APP_BASE_DIR', tmp_path / 'missing')
    monkeypatch.setattr(runtime_paths, 'RESOURCE_BASE_DIR', tmp_path / 'missing')
    assert runtime_paths.resolve_ffprobe_executable().source == 'unavailable'
