from __future__ import annotations

"""設定分割後も legacy re-export が壊れていないことを確認する unit test。"""

import pytest

import backend.settings as backend_settings
import frontend.settings as frontend_settings
import shared.configs as legacy_configs
import shared.runtime_paths as runtime_paths


pytestmark = pytest.mark.unit


def test_frontend_settings_load_ui_catalogs_from_json() -> None:
    assert frontend_settings.PDF_COMPRESS_MODES['both'] == '両方'
    assert frontend_settings.GS_PRESETS['ebook'] == '電子書籍用 (150dpi)'
    assert frontend_settings.LONG_EDGE_PRESETS[0] == '640'
    assert frontend_settings.LONG_EDGE_PRESETS[-1] == '3840'


def test_shared_configs_reexports_split_settings() -> None:
    assert legacy_configs.APP_BASE_DIR == runtime_paths.APP_BASE_DIR
    assert legacy_configs.RESOURCE_BASE_DIR == runtime_paths.RESOURCE_BASE_DIR
    assert legacy_configs.PDF_ALLOWED_MODES == backend_settings.PDF_ALLOWED_MODES
    assert legacy_configs.PDF_LOSSY_DPI_DEFAULT == backend_settings.PDF_LOSSY_DPI_DEFAULT
    assert legacy_configs.PDF_LOSSY_JPEG_QUALITY_DEFAULT == backend_settings.PDF_LOSSY_JPEG_QUALITY_DEFAULT
    assert legacy_configs.PDF_LOSSY_PNG_QUALITY_DEFAULT == backend_settings.PDF_LOSSY_PNG_QUALITY_DEFAULT
    assert legacy_configs.PDF_LOSSLESS_OPTIONS_DEFAULT == backend_settings.PDF_LOSSLESS_OPTIONS_DEFAULT
    assert legacy_configs.GS_DEFAULT_PRESET == backend_settings.GS_DEFAULT_PRESET
    assert legacy_configs.PDF_COMPRESS_MODES == frontend_settings.PDF_COMPRESS_MODES
    assert legacy_configs.INPUT_DIR_CLEANUP_EXTENSIONS == frontend_settings.INPUT_DIR_CLEANUP_EXTENSIONS
