from __future__ import annotations

"""frontend の locale JSON を backend から読むための共通 helper。"""

import json
from pathlib import Path
from typing import Any

from shared.runtime_paths import RESOURCE_BASE_DIR


LOCALES_DIR = RESOURCE_BASE_DIR / 'frontend' / 'config_data' / 'locales'
SUPPORTED_LANGUAGES = {'ja', 'en'}


def _normalize_language(language: str | None) -> str:
    if not language:
        return 'en'
    normalized = language.strip().replace('-', '_').split('_', 1)[0].lower()
    if normalized in SUPPORTED_LANGUAGES:
        return normalized
    return 'en'


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError as exc:
        raise RuntimeError(f'JSON ファイルが見つかりません: {path}') from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f'JSON の形式が不正です: {path}') from exc

    if not isinstance(payload, dict):
        raise RuntimeError(f'JSON ルートは object である必要があります: {path}')
    return payload


def _load_catalog(language: str | None) -> dict[str, str]:
    normalized_language = _normalize_language(language)
    locale_path = LOCALES_DIR / f'{normalized_language}.json'

    try:
        payload = _read_json_object(locale_path)
    except RuntimeError:
        if normalized_language != 'en':
            locale_path = LOCALES_DIR / 'en.json'
            payload = _read_json_object(locale_path)
        else:
            raise

    resolved: dict[str, str] = {}
    for key, value in payload.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise RuntimeError(f'ロケール JSON は文字列キー/値の object である必要があります: {locale_path}')
        resolved[key] = value
    return resolved


def load_locale_catalog(language: str | None) -> dict[str, str]:
    """指定言語の locale catalog を読み、英語を安全な fallback にする。"""
    normalized_language = _normalize_language(language)
    english_catalog = _load_catalog('en')
    if normalized_language == 'en':
        return english_catalog

    localized_catalog = _load_catalog(normalized_language)
    merged = dict(english_catalog)
    merged.update(localized_catalog)
    return merged


def translate(language: str | None, key: str, **kwargs: Any) -> str:
    """指定言語の文言を返す。欠落時は key、英語、または未整形文字列へ落とす。"""
    template = load_locale_catalog(language).get(key, key)
    try:
        return template.format(**kwargs)
    except Exception:
        return template