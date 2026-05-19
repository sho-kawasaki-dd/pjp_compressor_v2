from __future__ import annotations

"""shared locale helper の unit test。"""

import json
from pathlib import Path

import pytest

import shared.locale_catalog as locale_catalog


pytestmark = pytest.mark.unit


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def test_load_locale_catalog_merges_english_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    locales_dir = tmp_path / 'frontend' / 'config_data' / 'locales'
    locales_dir.mkdir(parents=True)
    _write_json(locales_dir / 'ja.json', {'hello': 'こんにちは'})
    _write_json(locales_dir / 'en.json', {'hello': 'Hello', 'goodbye': 'Goodbye'})
    monkeypatch.setattr(locale_catalog, 'LOCALES_DIR', locales_dir)

    catalog = locale_catalog.load_locale_catalog('ja')

    assert catalog['hello'] == 'こんにちは'
    assert catalog['goodbye'] == 'Goodbye'
    assert locale_catalog.translate('ja', 'missing.key') == 'missing.key'


def test_translate_uses_english_when_language_is_unknown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    locales_dir = tmp_path / 'frontend' / 'config_data' / 'locales'
    locales_dir.mkdir(parents=True)
    _write_json(locales_dir / 'en.json', {'greeting': 'Hello {name}'})
    monkeypatch.setattr(locale_catalog, 'LOCALES_DIR', locales_dir)

    assert locale_catalog.translate('fr', 'greeting', name='Alice') == 'Hello Alice'