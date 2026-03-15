from __future__ import annotations

"""orchestrator から渡された 1 ファイル分の圧縮処理を実行する。"""

from pathlib import Path

from backend.core.format_utils import human_readable
from backend.core.image_utils import compress_image_pillow, compress_png_pngquant
from backend.core.pdf_utils import compress_pdf_gs, compress_pdf_native


def process_single_file(args):
    """1 ファイル処理のユーティリティ。拡張子で処理系を自動選択。"""
    # Orchestrator may append metadata fields after resize_cfg for logging purposes.
    args = tuple(args[:16])
    (
        inpath,
        outpath,
        ext,
        pdf_engine,
        pdf_mode,
        pdf_dpi,
        pdf_jpeg_quality,
        pdf_png_to_jpeg,
        pdf_lossless_options,
        gs_preset,
        gs_custom_dpi,
        jpg_quality,
        png_quality,
        use_pngquant,
        resize_cfg,
        debug_mode,
    ) = args

    inpath = Path(inpath)
    outpath = Path(outpath)

    try:
        orig_size = inpath.stat().st_size
    except Exception:
        orig_size = 0

    outdir = outpath.parent
    if not outdir.exists():
        outdir.mkdir(parents=True, exist_ok=True)

    processed = False
    if ext == 'pdf':
        processed = True
        # PDF はエンジン選択があるため、ここでネイティブ系と Ghostscript 系を分岐する。
        if pdf_engine == 'gs':
            _, base_msg = compress_pdf_gs(
                str(inpath),
                str(outpath),
                preset=gs_preset,
                custom_dpi=gs_custom_dpi,
                lossless_options=pdf_lossless_options,
            )
        else:
            _, base_msg = compress_pdf_native(
                str(inpath),
                str(outpath),
                mode=pdf_mode,
                target_dpi=pdf_dpi,
                jpeg_quality=pdf_jpeg_quality,
                png_to_jpeg=pdf_png_to_jpeg,
                lossless_options=pdf_lossless_options,
                debug=debug_mode,
            )
    elif ext in ['jpg', 'jpeg']:
        processed = True
        _, base_msg = compress_image_pillow(str(inpath), str(outpath), jpg_quality, resize_cfg=resize_cfg)
    elif ext == 'png':
        processed = True
        if use_pngquant:
            # UI の PNG 品質は上限値として扱い、下限は少し広めに取って圧縮率を確保する。
            qmin = max(0, png_quality - 20)
            qmax = png_quality
            _, base_msg = compress_png_pngquant(str(inpath), str(outpath), qmin, qmax, speed=3, resize_cfg=resize_cfg)
        else:
            _, base_msg = compress_image_pillow(str(inpath), str(outpath), png_quality, resize_cfg=resize_cfg)
    else:
        try:
            # 対象外ファイルは orchestrator 側で必要ならコピーするため、ここでは理由だけ返す。
            base_msg = f"未対応: {inpath.name}（Left in the input folder）"
        except Exception as e:
            base_msg = f"未対応ファイル失敗: {inpath.name} ({e})"

    try:
        out_size = outpath.stat().st_size if outpath.exists() else orig_size
    except Exception:
        out_size = orig_size

    saved_size = orig_size - out_size
    saved_pct = (saved_size / orig_size * 100) if orig_size > 0 else 0.0
    # 呼び出し側が CSV・UI・ログで同じ文字列を使えるよう、詳細はここでまとめる。
    size_info = f" | Before: {human_readable(orig_size)} → After: {human_readable(out_size)}"
    if saved_size > 0:
        size_info += f" (削減: {human_readable(saved_size)}, -{saved_pct:.1f}%)"
    elif saved_size < 0:
        size_info += f" (増加: {human_readable(-saved_size)}, +{-saved_pct:.1f}%)"
    else:
        size_info += ' (変化なし)'

    msg = base_msg + size_info
    return msg, orig_size, out_size, processed
