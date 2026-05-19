from __future__ import annotations

"""frontend.i18n の単体テスト。"""

import json
from pathlib import Path

import pytest

import frontend.i18n as i18n


pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def reset_i18n_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(i18n, '_current_language', 'en', raising=False)
    monkeypatch.setattr(i18n, '_current', {}, raising=False)


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def test_detect_os_language_prefers_japanese(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(i18n.locale, 'getdefaultlocale', lambda: ('ja_JP', 'UTF-8'))

    assert i18n.detect_os_language() == 'ja'


def test_detect_os_language_defaults_to_english(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(i18n.locale, 'getdefaultlocale', lambda: ('en_US', 'UTF-8'))

    assert i18n.detect_os_language() == 'en'


def test_load_reads_locale_and_falls_back_to_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    locales_dir = tmp_path / 'frontend' / 'config_data' / 'locales'
    locales_dir.mkdir(parents=True)
    _write_json(locales_dir / 'ja.json', {'hello': 'こんにちは'})
    _write_json(locales_dir / 'en.json', {'hello': 'Hello'})
    monkeypatch.setattr(i18n, 'LOCALES_DIR', locales_dir)

    i18n.load('ja')
    assert i18n.t('hello') == 'こんにちは'
    assert i18n.t('missing.key') == 'missing.key'

    i18n.load('en')
    assert i18n.t('hello') == 'Hello'


def test_init_from_settings_uses_catalog_language(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    frontend_config_dir = tmp_path / 'frontend' / 'config_data'
    locales_dir = frontend_config_dir / 'locales'
    locales_dir.mkdir(parents=True)
    _write_json(locales_dir / 'ja.json', {'hello': 'こんにちは'})
    _write_json(locales_dir / 'en.json', {'hello': 'Hello'})
    _write_json(
        frontend_config_dir / 'ui_catalogs.json',
        {
            'long_edge_presets': ['640'],
            'app_settings': {
                'language': 'ja',
                'play_startup_sound': True,
                'play_cleanup_sound': True,
            },
        },
    )
    monkeypatch.setattr(i18n, 'LOCALES_DIR', locales_dir)

    language = i18n.init_from_settings(tmp_path)

    assert language == 'ja'
    assert i18n.t('hello') == 'こんにちは'


def test_init_from_settings_falls_back_to_os_language(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    frontend_config_dir = tmp_path / 'frontend' / 'config_data'
    locales_dir = frontend_config_dir / 'locales'
    locales_dir.mkdir(parents=True)
    _write_json(locales_dir / 'ja.json', {'hello': 'こんにちは'})
    _write_json(locales_dir / 'en.json', {'hello': 'Hello'})
    _write_json(
        frontend_config_dir / 'ui_catalogs.json',
        {
            'long_edge_presets': ['640'],
            'app_settings': {
                'language': '',
                'play_startup_sound': True,
                'play_cleanup_sound': True,
            },
        },
    )
    monkeypatch.setattr(i18n, 'LOCALES_DIR', locales_dir)
    monkeypatch.setattr(i18n.locale, 'getdefaultlocale', lambda: ('ja_JP', 'UTF-8'))

    language = i18n.init_from_settings(tmp_path)

    assert language == 'ja'
    assert i18n.t('hello') == 'こんにちは'