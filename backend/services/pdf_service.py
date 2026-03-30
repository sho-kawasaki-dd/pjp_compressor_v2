from __future__ import annotations

"""PDF 圧縮関連機能のサービス層再公開。

PDF は依存や分岐が多いため、呼び出し側が core 実装名へ直接結び付かないよう
service 層の名前付き窓口を維持している。
"""

from backend.core.pdf_utils import (
    compress_pdf_ghostscript,
    compress_pdf_lossless,
    compress_pdf_lossy,
    compress_pdf_native,
    get_ghostscript_path,
)

__all__ = [
    'compress_pdf_ghostscript',
    'compress_pdf_lossless',
    'compress_pdf_lossy',
    'compress_pdf_native',
    'get_ghostscript_path',
]
