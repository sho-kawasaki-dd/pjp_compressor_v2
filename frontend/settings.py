#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""frontend の UI 設定と表示用カタログを集約する。"""

from __future__ import annotations

import json

from shared.runtime_paths import APP_BASE_DIR, RESOURCE_BASE_DIR


def _load_ui_catalogs() -> tuple[dict[str, str], dict[str, str], tuple[str, ...]]:
    """UI 表示用の静的カタログを JSON から読み込む。"""
    resource_path = RESOURCE_BASE_DIR / 'frontend' / 'config_data' / 'ui_catalogs.json'
    try:
        payload = json.loads(resource_path.read_text(encoding='utf-8'))
    except FileNotFoundError as exc:
        raise RuntimeError(f'UI カタログが見つかりません: {resource_path}') from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f'UI カタログ JSON の形式が不正です: {resource_path}') from exc

    if not isinstance(payload, dict):
        raise RuntimeError('UI カタログ JSON のルートは object である必要があります')

    pdf_modes = payload.get('pdf_compress_modes')
    gs_presets = payload.get('gs_presets')
    long_edge_presets = payload.get('long_edge_presets')

    if not isinstance(pdf_modes, dict) or not all(isinstance(key, str) and isinstance(value, str) for key, value in pdf_modes.items()):
        raise RuntimeError('pdf_compress_modes は文字列キー/値の object である必要があります')
    if not isinstance(gs_presets, dict) or not all(isinstance(key, str) and isinstance(value, str) for key, value in gs_presets.items()):
        raise RuntimeError('gs_presets は文字列キー/値の object である必要があります')
    if not isinstance(long_edge_presets, list) or not all(isinstance(value, str) for value in long_edge_presets):
        raise RuntimeError('long_edge_presets は文字列配列である必要があります')

    return dict(pdf_modes), dict(gs_presets), tuple(long_edge_presets)


PDF_COMPRESS_MODES, GS_PRESETS, LONG_EDGE_PRESETS = _load_ui_catalogs()

PDF_LOSSY_DPI_RANGE = (36, 600)

INPUT_DIR_CLEANUP_EXTENSIONS = {'.pdf', '.jpg', '.jpeg', '.png', '.zip'}
OUTPUT_DIR_CLEANUP_EXTENSIONS = {'.pdf', '.jpg', '.jpeg', '.png', '.csv'}

APP_DEFAULT_INPUT_DIR = APP_BASE_DIR / 'input_files'
APP_DEFAULT_OUTPUT_DIR = APP_BASE_DIR / 'output_files'
APP_DEFAULT_WINDOW_SIZE = '750x850'

SOUNDS_DIR = RESOURCE_BASE_DIR / 'sounds'
IMAGES_DIR = RESOURCE_BASE_DIR / 'images'

DEBUG_MODE_DEFAULT = False
COPY_NON_TARGET_FILES_DEFAULT = False
