#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""frontend の UI 設定と表示用カタログを集約する。

frontend では値そのものよりも「どこから設定を読むか」が重要なので、JSON 読み込み、
既定値補完、リソースパス解決をこのモジュールへ集める。UI コードはここから完成済みの
定数や辞書を受け取るだけにして、設定ファイル形式の都合を広げない。
"""

from __future__ import annotations

import json
from pathlib import Path

from typing import Any

from shared.runtime_paths import APP_BASE_DIR, RESOURCE_BASE_DIR


UI_CATALOGS_PATH = RESOURCE_BASE_DIR / 'frontend' / 'config_data' / 'ui_catalogs.json'
APP_SETTINGS_DEFAULTS = {
    'language': '',
    'play_startup_sound': True,
    'play_cleanup_sound': True,
}


def _read_ui_catalogs_payload(resource_path: Path | None = None) -> dict[str, Any]:
    """UI カタログ JSON 全体を読み込んで返す。

    形式不正は静かに握りつぶすより起動時に明示した方が修正しやすいため、呼び出し側で
    扱いやすい `RuntimeError` へ正規化して返す。
    """
    target_path = resource_path or UI_CATALOGS_PATH
    try:
        payload = json.loads(target_path.read_text(encoding='utf-8'))
    except FileNotFoundError as exc:
        raise RuntimeError(f'UI カタログが見つかりません: {target_path}') from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f'UI カタログ JSON の形式が不正です: {target_path}') from exc

    if not isinstance(payload, dict):
        raise RuntimeError('UI カタログ JSON のルートは object である必要があります')
    return payload


def load_app_settings(resource_path: Path | None = None) -> dict[str, bool | str]:
    """永続化されたアプリ設定を読み込み、欠落値には既定値を補う。

    設定 JSON はユーザー編集や将来の項目追加で欠損しうるため、常に完全な辞書を返して
    UI 初期化側の分岐を減らす。
    """
    payload = _read_ui_catalogs_payload(resource_path)
    settings = payload.get('app_settings')
    if not isinstance(settings, dict):
        return dict(APP_SETTINGS_DEFAULTS)

    resolved = dict(APP_SETTINGS_DEFAULTS)
    for key in resolved:
        value = settings.get(key)
        if isinstance(resolved[key], bool) and isinstance(value, bool):
            resolved[key] = value
        elif isinstance(resolved[key], str) and isinstance(value, str):
            resolved[key] = value
    return resolved


def save_app_settings(
    *,
    language: str = '',
    play_startup_sound: bool,
    play_cleanup_sound: bool,
    resource_path: Path | None = None,
) -> bool:
    """app_settings セクションだけを更新して JSON へ保存する。

    表示用カタログと同じ JSON を共有しているため、必要部分だけを書き換えて他セクションを
    壊さないことを優先する。
    """
    target_path = resource_path or UI_CATALOGS_PATH
    try:
        payload = _read_ui_catalogs_payload(target_path)
    except RuntimeError:
        return False

    payload['app_settings'] = {
        'language': language,
        'play_startup_sound': bool(play_startup_sound),
        'play_cleanup_sound': bool(play_cleanup_sound),
    }

    try:
        target_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    except OSError:
        return False
    return True


def _load_ui_catalogs() -> tuple[str, ...]:
    """UI 表示用の静的カタログを JSON から読み込む。

    文字列カタログを Python コードへベタ書きしないことで、UI 文言と選択肢の追加を
    コード変更なしで追いやすくする。
    """
    payload = _read_ui_catalogs_payload()

    long_edge_presets = payload.get('long_edge_presets')

    if not isinstance(long_edge_presets, list) or not all(isinstance(value, str) for value in long_edge_presets):
        raise RuntimeError('long_edge_presets は文字列配列である必要があります')

    return tuple(long_edge_presets)


LONG_EDGE_PRESETS = _load_ui_catalogs()

# DPI 範囲は UI スライダーと mapper の clamp 基準を揃えるため frontend 側で共有する。
PDF_LOSSY_DPI_RANGE = (36, 600)

INPUT_DIR_CLEANUP_EXTENSIONS = {'.pdf', '.jpg', '.jpeg', '.png', '.zip'}
OUTPUT_DIR_CLEANUP_EXTENSIONS = {'.pdf', '.jpg', '.jpeg', '.png', '.csv', '.zip'}

APP_DEFAULT_INPUT_DIR = APP_BASE_DIR / 'input_files'
APP_DEFAULT_OUTPUT_DIR = APP_BASE_DIR / 'output_files'
APP_DEFAULT_WINDOW_SIZE = '850x950'

SOUNDS_DIR = RESOURCE_BASE_DIR / 'sounds'
IMAGES_DIR = RESOURCE_BASE_DIR / 'images'

DEBUG_MODE_DEFAULT = False
COPY_NON_TARGET_FILES_DEFAULT = False
