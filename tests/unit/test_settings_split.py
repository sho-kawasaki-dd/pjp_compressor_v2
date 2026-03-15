from __future__ import annotations

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
    assert legacy_configs.PDF_COMPRESS_MODES == frontend_settings.PDF_COMPRESS_MODES
    assert legacy_configs.INPUT_DIR_CLEANUP_EXTENSIONS == frontend_settings.INPUT_DIR_CLEANUP_EXTENSIONS
