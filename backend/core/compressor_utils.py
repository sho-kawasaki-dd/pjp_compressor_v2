#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
compressor_utils.py (compatibility shim)

旧来の import パス互換を維持するための再エクスポートモジュール。
実処理は責務別モジュールへ分割済みで、本モジュールは移行期間中の
外部呼び出しを壊さないための窓口として残している。
"""

from __future__ import annotations

from backend.settings import (
    GS_DEFAULT_PRESET,
    PDF_LOSSY_DPI_DEFAULT,
    PDF_LOSSY_JPEG_QUALITY_DEFAULT,
    PDF_LOSSY_PNG_TO_JPEG_DEFAULT,
)

from backend.core.archive_utils import extract_zip_archives
from backend.core.file_ops import cleanup_folder, count_target_files
from backend.core.format_utils import human_readable
from backend.core.image_utils import compress_image_pillow, compress_png_pngquant
from backend.core.pdf_utils import (
    compress_pdf_gs,
    compress_pdf_ghostscript,
    compress_pdf_lossless,
    compress_pdf_lossy,
    compress_pdf_native,
    get_ghostscript_path,
)
from backend.core.worker_ops import process_single_file

# 互換維持対象の公開APIシンボル一覧
__all__ = (
    'compress_folder',
    'cleanup_folder',
    'count_target_files',
    'human_readable',
    'get_ghostscript_path',
)

def get_public_api_symbols() -> tuple[str, ...]:
    """互換維持対象の公開APIシンボル一覧を返す。"""
    return __all__
    
def compress_folder(
    input_dir,
    output_dir,
    jpg_quality,
    png_quality,
    use_pngquant,
    log_func,
    progress_func,
    stats_func,
    pdf_engine='native',
    pdf_mode='both',
    pdf_dpi=PDF_LOSSY_DPI_DEFAULT,
    pdf_jpeg_quality=PDF_LOSSY_JPEG_QUALITY_DEFAULT,
    pdf_png_to_jpeg=PDF_LOSSY_PNG_TO_JPEG_DEFAULT,
    pdf_lossless_options=None,
    gs_preset=GS_DEFAULT_PRESET,
    gs_custom_dpi=None,
    resize_enabled=False,
    resize_width=0,
    resize_height=0,
    csv_enable=True,
    csv_path=None,
    extract_zip=False,
):
    """フォルダ全体を並列処理で圧縮する互換 API。

    既存コードはこの関数名に依存しているため、内部実装が orchestrator へ移っても
    シグネチャを極力保ったまま転送する。
    """
    from backend.orchestrator.job_runner import run_compression_job

    # orchestrator を唯一の実処理入口にして、圧縮フローの重複実装を避ける。
    return run_compression_job(
        input_dir=input_dir,
        output_dir=output_dir,
        jpg_quality=jpg_quality,
        png_quality=png_quality,
        use_pngquant=use_pngquant,
        log_func=log_func,
        progress_func=progress_func,
        stats_func=stats_func,
        pdf_engine=pdf_engine,
        pdf_mode=pdf_mode,
        pdf_dpi=pdf_dpi,
        pdf_jpeg_quality=pdf_jpeg_quality,
        pdf_png_to_jpeg=pdf_png_to_jpeg,
        pdf_lossless_options=pdf_lossless_options,
        gs_preset=gs_preset,
        gs_custom_dpi=gs_custom_dpi,
        resize_enabled=resize_enabled,
        resize_width=resize_width,
        resize_height=resize_height,
        csv_enable=csv_enable,
        csv_path=csv_path,
        extract_zip=extract_zip,
    )
