from __future__ import annotations

"""orchestrator から渡された 1 ファイル分の圧縮処理を実行する。

worker は 1 ファイル単位の純粋な処理に寄せ、ZIP 展開や CSV 規約のようなジョブ全体
の事情は orchestrator 側へ残す。この分離により、並列実行時も worker の責務を
「拡張子ごとの適切な圧縮器選択」と「サイズ要約の合成」に限定できる。
"""

from dataclasses import dataclass
from pathlib import Path

from backend.core.format_utils import human_readable
from backend.core.image_utils import compress_image_pillow, compress_png_pngquant
from backend.core.pdf_utils import compress_pdf_gs, compress_pdf_native
from shared.locale_catalog import translate


@dataclass(frozen=True)
class WorkerFileResult:
    """1 ファイル処理の結果と CSV 用メタデータをまとめる。"""

    action_key: str
    message: str
    orig_size: int
    out_size: int
    processed: bool


def _t(log_language: str, key: str, **kwargs) -> str:
    return translate(log_language, key, **kwargs)


def build_size_summary(orig_size: int, out_size: int, log_language: str = 'ja') -> str:
    """前後サイズ差を 1 本の要約文へ整形する。"""
    saved_size = orig_size - out_size
    saved_pct = (saved_size / orig_size * 100) if orig_size > 0 else 0.0
    orig = human_readable(orig_size)
    out = human_readable(out_size)
    saved = human_readable(abs(saved_size))

    if saved_size > 0:
        delta = _t(log_language, 'worker_size_delta_saved', saved=saved, saved_pct=saved_pct)
    elif saved_size < 0:
        delta = _t(log_language, 'worker_size_delta_grown', saved=saved, saved_pct=saved_pct)
    else:
        delta = _t(log_language, 'worker_size_delta_unchanged')

    return _t(log_language, 'worker_size_before_after', orig=orig, out=out, delta=delta)


def compose_worker_message(base_msg: str, orig_size: int, out_size: int, log_language: str = 'ja') -> str:
    """worker 本体の結果メッセージとサイズ要約を組み立てる。"""
    return f'{base_msg} | {build_size_summary(orig_size, out_size, log_language)}'


def _csv_action_key(ext: str, processed: bool) -> str:
    if ext == 'pdf':
        return 'csv_action_pdf'
    if ext in ['jpg', 'jpeg']:
        return 'csv_action_jpeg'
    if ext == 'png':
        return 'csv_action_png'
    return 'csv_action_failed' if not processed else 'csv_action_unknown'


def process_single_file(args):
    """1 ファイル処理のユーティリティ。拡張子で処理系を自動選択する。

    orchestrator からは CSV 用メタデータ込みの長いタプルが渡されるが、worker が
    実際に必要とするのは先頭 20 要素だけである。ここで切り詰めておくことで、
    worker はログ表示用の後続フィールドに依存せずに済む。
    """
    # Orchestrator may append metadata fields after resize_cfg for logging purposes.
    args = tuple(args[:20])
    (
        inpath,
        outpath,
        ext,
        pdf_engine,
        pdf_mode,
        pdf_dpi,
        pdf_jpeg_quality,
        pdf_png_quality,
        pdf_lossless_options,
        gs_preset,
        gs_custom_dpi,
        jpg_quality,
        png_quality,
        use_pngquant,
        resize_cfg,
        debug_mode,
        csv_input_path,
        csv_output_path,
        csv_notes,
        log_language,
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
                log_language=log_language,
            )
        else:
            _, base_msg = compress_pdf_native(
                str(inpath),
                str(outpath),
                mode=pdf_mode,
                target_dpi=pdf_dpi,
                jpeg_quality=pdf_jpeg_quality,
                png_quality=pdf_png_quality,
                lossless_options=pdf_lossless_options,
                debug=debug_mode,
                log_language=log_language,
            )
    elif ext in ['jpg', 'jpeg']:
        processed = True
        _, base_msg = compress_image_pillow(str(inpath), str(outpath), jpg_quality, resize_cfg=resize_cfg, log_language=log_language)
    elif ext == 'png':
        processed = True
        if use_pngquant:
            # UI の PNG 品質は上限値として扱い、下限は少し広めに取って圧縮率を確保する。
            qmin = max(0, png_quality - 20)
            qmax = png_quality
            _, base_msg = compress_png_pngquant(str(inpath), str(outpath), qmin, qmax, speed=3, resize_cfg=resize_cfg, log_language=log_language)
        else:
            _, base_msg = compress_image_pillow(str(inpath), str(outpath), png_quality, resize_cfg=resize_cfg, log_language=log_language)
    else:
        try:
            # 対象外ファイルは orchestrator 側で必要ならコピーするため、ここでは理由だけ返す。
            base_msg = _t(log_language, 'worker_unsupported', name=inpath.name)
        except Exception as e:
            base_msg = _t(log_language, 'worker_unsupported_failed', name=inpath.name, exc=e)

    try:
        out_size = outpath.stat().st_size if outpath.exists() else orig_size
    except Exception:
        out_size = orig_size

    action_key = _csv_action_key(ext, processed)
    msg = compose_worker_message(base_msg, orig_size, out_size, log_language)
    return WorkerFileResult(action_key=action_key, message=msg, orig_size=orig_size, out_size=out_size, processed=processed)
