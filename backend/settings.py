#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""backend の処理既定値を集約する。

既定値をここへ寄せる理由は、UI の初期表示、mapper の補正、backend の最終防衛線が
同じ基準を共有できるようにするためである。圧縮アルゴリズム本体には「値の意味」だけ
を残し、「既定で何を選ぶか」はこのモジュールへ閉じ込める。
"""

from __future__ import annotations

PDF_ALLOWED_MODES = frozenset({'lossy', 'lossless', 'both'})

# 画質と圧縮率のバランスが極端に崩れにくい既定値を採用する。
PDF_LOSSY_DPI_DEFAULT = 150
PDF_LOSSY_JPEG_QUALITY_DEFAULT = 75
PDF_LOSSY_PNG_QUALITY_DEFAULT = 70

# pikepdf の可逆最適化は、サイズ改善が出やすいものを既定で有効にしている。
PDF_LOSSLESS_OPTIONS_DEFAULT = {
    'linearize': True,
    'object_streams': True,
    'clean_metadata': False,
    'recompress_streams': True,
    'remove_unreferenced': True,
}

# Ghostscript は汎用用途で破綻しにくい `ebook` を backend 標準とする。
GS_DEFAULT_PRESET = 'ebook'
