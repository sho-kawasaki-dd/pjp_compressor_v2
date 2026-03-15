from __future__ import annotations

"""PDF 圧縮関連機能のサービス層再公開。"""

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
