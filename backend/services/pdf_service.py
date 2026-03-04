from __future__ import annotations

from backend.core.compressor_utils import (
    compress_pdf,
    compress_pdf_ghostscript,
    compress_pdf_lossless,
    compress_pdf_lossy,
    compress_pdf_native,
    get_ghostscript_path,
)

__all__ = [
    'compress_pdf',
    'compress_pdf_ghostscript',
    'compress_pdf_lossless',
    'compress_pdf_lossy',
    'compress_pdf_native',
    'get_ghostscript_path',
]
