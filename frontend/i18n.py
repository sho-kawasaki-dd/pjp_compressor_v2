#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""UI 文言のローカライズを扱う。"""

from __future__ import annotations

import json
import locale
from pathlib import Path
from typing import Any

from shared.runtime_paths import RESOURCE_BASE_DIR


UI_CATALOGS_PATH = RESOURCE_BASE_DIR / 'frontend' / 'config_data' / 'ui_catalogs.json'
LOCALES_DIR = RESOURCE_BASE_DIR / 'frontend' / 'config_data' / 'locales'
SUPPORTED_LANGUAGES = {'ja', 'en'}

_current_language = 'en'
_current: dict[str, str] = {}


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


def _resolve_catalog_path(resource_path: Path | None = None) -> Path:
    if resource_path is None:
        return UI_CATALOGS_PATH
    if resource_path.is_dir():
        return resource_path / 'frontend' / 'config_data' / 'ui_catalogs.json'
    return resource_path


def detect_os_language() -> str:
    """OS の既定ロケールから ja/en を推定する。"""
    locale_name, _ = locale.getdefaultlocale()
    return 'ja' if isinstance(locale_name, str) and locale_name.lower().startswith('ja') else 'en'


def load(language: str) -> None:
    """ロケール JSON を読み込んで現在の翻訳辞書を更新する。"""
    normalized_language = _normalize_language(language)
    locale_path = LOCALES_DIR / f'{normalized_language}.json'

    try:
        payload = _read_json_object(locale_path)
    except RuntimeError:
        if normalized_language != 'en':
            normalized_language = 'en'
            locale_path = LOCALES_DIR / 'en.json'
            payload = _read_json_object(locale_path)
        else:
            raise

    resolved: dict[str, str] = {}
    for key, value in payload.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise RuntimeError(f'ロケール JSON は文字列キー/値の object である必要があります: {locale_path}')
        resolved[key] = value

    global _current_language, _current
    _current_language = normalized_language
    _current = resolved


def init_from_settings(resource_path: Path | None = None) -> str:
    """ui_catalogs.json から言語設定を読み、未設定なら OS から初期化する。"""
    catalog_path = _resolve_catalog_path(resource_path)

    language = ''
    try:
        payload = _read_json_object(catalog_path)
    except RuntimeError:
        language = detect_os_language()
    else:
        app_settings = payload.get('app_settings')
        if isinstance(app_settings, dict):
            raw_language = app_settings.get('language')
            if isinstance(raw_language, str):
                language = raw_language

        if not language:
            language = detect_os_language()

    load(language)
    return _current_language


def t(key: str, **kwargs: Any) -> str:
    """現在言語の文言を返す。"""
    template = _current.get(key, key)
    return template.format(**kwargs)
