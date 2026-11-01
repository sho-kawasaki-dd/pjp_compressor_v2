from __future__ import annotations

"""shared locale helper の unit test。"""

import json
from pathlib import Path
from string import Formatter

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


def test_project_catalogs_have_matching_keys_and_placeholders() -> None:
    locales_dir = Path(__file__).resolve().parents[2] / 'frontend' / 'config_data' / 'locales'
    catalogs = {
        language: json.loads((locales_dir / f'{language}.json').read_text(encoding='utf-8'))
        for language in ('ja', 'en')
    }

    assert catalogs['ja'].keys() == catalogs['en'].keys()
    assert 'video_audio_aac_converted' in catalogs['ja']
    for key in catalogs['ja']:
        fields = [
            {name for _, name, _, _ in Formatter().parse(catalogs[language][key]) if name is not None}
            for language in ('ja', 'en')
        ]
        assert fields[0] == fields[1], key