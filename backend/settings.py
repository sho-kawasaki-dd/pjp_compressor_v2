#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""backend の処理既定値を集約する。"""

from __future__ import annotations

PDF_ALLOWED_MODES = frozenset({'lossy', 'lossless', 'both'})

PDF_LOSSY_DPI_DEFAULT = 150
PDF_LOSSY_JPEG_QUALITY_DEFAULT = 75
PDF_LOSSY_PNG_TO_JPEG_DEFAULT = False

PDF_LOSSLESS_OPTIONS_DEFAULT = {
    'linearize': True,
    'object_streams': True,
    'clean_metadata': False,
    'recompress_streams': True,
    'remove_unreferenced': True,
}

GS_DEFAULT_PRESET = 'ebook'
