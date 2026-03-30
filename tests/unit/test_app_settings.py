from __future__ import annotations

import json
from pathlib import Path

import pytest

import frontend.settings as frontend_settings


pytestmark = pytest.mark.unit


def test_load_app_settings_defaults_when_section_missing(tmp_path: Path) -> None:
    config_path = tmp_path / 'ui_catalogs.json'
    config_path.write_text(
        json.dumps(
            {
                'pdf_compress_modes': {'both': '両方'},
                'gs_presets': {'ebook': '電子書籍用 (150dpi)'},
                'long_edge_presets': ['640'],
            },
            ensure_ascii=False,
        ),
        encoding='utf-8',
    )

    settings = frontend_settings.load_app_settings(config_path)

    assert settings == frontend_settings.APP_SETTINGS_DEFAULTS


def test_save_app_settings_round_trip(tmp_path: Path) -> None:
    config_path = tmp_path / 'ui_catalogs.json'
    config_path.write_text(
        json.dumps(
            {
                'pdf_compress_modes': {'both': '両方'},
                'gs_presets': {'ebook': '電子書籍用 (150dpi)'},
                'long_edge_presets': ['640'],
                'app_settings': {
                    'play_startup_sound': True,
                    'play_cleanup_sound': True,
                },
            },
            ensure_ascii=False,
        ),
        encoding='utf-8',
    )

    saved = frontend_settings.save_app_settings(
        play_startup_sound=False,
        play_cleanup_sound=True,
        resource_path=config_path,
    )

    assert saved is True
    assert frontend_settings.load_app_settings(config_path) == {
        'play_startup_sound': False,
        'play_cleanup_sound': True,
    }