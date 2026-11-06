from __future__ import annotations

"""orchestrator から渡された 1 ファイル分の圧縮処理を実行する。

worker は 1 ファイル単位の純粋な処理に寄せ、ZIP 展開や CSV 規約のようなジョブ全体
の事情は orchestrator 側へ残す。この分離により、並列実行時も worker の責務を
「拡張子ごとの適切な圧縮器選択」と「サイズ要約の合成」に限定できる。
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from backend.contracts import ImageCompressionConfig, JobControl
from backend.core.format_utils import human_readable
from backend.core.image_utils import (
    ImageCompressResult,
    compress_image_pillow,
    compress_png_pngquant,
    converted_image_extension,
)
from backend.core.pdf_utils import compress_pdf_gs, compress_pdf_native
from backend.core.video_utils import compress_video_ffmpeg
from backend.settings import VIDEO_EXTENSIONS
from shared.locale_catalog import translate

# 旧形式の 20 / 26 要素も受け付け、末尾に画像設定と画像用一時領域を追加する。
TASK_TUPLE_LENGTH = 28


@dataclass(frozen=True)
class WorkerFileResult:
    """1 ファイル処理の結果と CSV 用メタデータをまとめる。"""

    action_key: str
    message: str
    orig_size: int
    out_size: int | None
    processed: bool
    final_outpath: str | None = None
    kept_original_reason: Literal['no_gain', 'retention'] | None = None
    cancelled: bool = False
    notes: str = ''


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


def _csv_action_key(
    ext: str,
    processed: bool,
    *,
    kept_original_reason: Literal['no_gain', 'retention'] | None = None,
    cancelled: bool = False,
    image_target_extension: str | None = None,
) -> str:
    if cancelled:
        return 'csv_action_cancelled'
    if ext in VIDEO_EXTENSIONS:
        if not processed:
            return 'csv_action_failed'
        if kept_original_reason == 'no_gain':
            return 'csv_action_video_kept_original'
        if kept_original_reason == 'retention':
            return 'csv_action_video_kept_retention'
        return 'csv_action_video'
    if ext in {'jpg', 'jpeg', 'png', 'avif'}:
        if not processed:
            return 'csv_action_failed'
        if kept_original_reason == 'no_gain':
            return 'csv_action_image_kept_original'
        if kept_original_reason == 'retention':
            return 'csv_action_image_kept_retention'
        if image_target_extension == '.avif':
            return 'csv_action_avif'
        if ext == 'avif' and image_target_extension == '.jpg':
            return 'csv_action_compat_jpeg'
        return 'csv_action_png' if ext == 'png' else 'csv_action_jpeg'
    if ext == 'pdf':
        return 'csv_action_pdf'
    return 'csv_action_failed' if not processed else 'csv_action_unknown'


def _process_image_task(
    inpath: Path,
    outpath: Path,
    original_outpath: Path,
    ext: str,
    *,
    image_config: ImageCompressionConfig,
    jpg_quality: int,
    png_quality: int,
    use_pngquant: bool,
    resize_cfg,
    job_control: JobControl | None,
    temp_dir: Path | None,
    log_language: str,
) -> ImageCompressResult:
    """既存形式は従来の圧縮器を使い、新形式は後続フェーズまで明示的に拒否する。"""
    if converted_image_extension(ext, image_config) is not None:
        if job_control is None or temp_dir is None or original_outpath.suffix.lower() != inpath.suffix.lower():
            raise ValueError('converted image task requires a job control, work directory and original-extension destination')
        return ImageCompressResult(False, _t(log_language, 'image_conversion_unavailable', name=inpath.name), None)
    if ext in {'jpg', 'jpeg'}:
        ok, message = compress_image_pillow(str(inpath), str(outpath), jpg_quality, resize_cfg=resize_cfg, log_language=log_language)
    else:
        if use_pngquant:
            qmin = max(0, png_quality - 20)
            ok, message = compress_png_pngquant(str(inpath), str(outpath), qmin, png_quality, speed=3, resize_cfg=resize_cfg, log_language=log_language)
        else:
            ok, message = compress_image_pillow(str(inpath), str(outpath), png_quality, resize_cfg=resize_cfg, log_language=log_language)
    return ImageCompressResult(ok, message, str(outpath) if ok else None)


def process_single_file(args):
    """1 ファイル処理のユーティリティ。拡張子で処理系を自動選択する。

    orchestrator からは CSV 用メタデータ込みのタプルが渡される。index 0〜19 は画像・PDF
    の処理に必要な値と CSV 文脈、index 20〜25 は動画処理と停止制御用の値、末尾は画像
    設定と一時領域である。旧形式のタプルも受け付け、不足分は既定値として扱う。
    """
    args = tuple(args[:TASK_TUPLE_LENGTH]) + (None,) * max(0, TASK_TUPLE_LENGTH - len(args))
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
        _,
        _,
        _,
        log_language,
        video_config,
        video_progress_callback,
        original_outpath,
        job_control,
        capabilities,
        video_temp_dir,
        image_config,
        image_temp_dir,
    ) = args  # type: ignore[misc]

    inpath = Path(inpath)
    outpath = Path(outpath)
    if image_config is None:
        image_config = ImageCompressionConfig()
    if not isinstance(image_config, ImageCompressionConfig):
        raise TypeError('image_config must be an ImageCompressionConfig')

    try:
        orig_size = inpath.stat().st_size
    except OSError as exc:
        return WorkerFileResult(
            action_key='csv_action_failed',
            message=_t(log_language, 'worker_input_stat_failed', name=inpath.name, detail=str(exc)),
            orig_size=0,
            out_size=0,
            processed=False,
        )

    if job_control is not None and job_control.is_cancelled:
        # 未開始タスクは出力先を作らず中断結果だけ返す。
        return WorkerFileResult(
            action_key='csv_action_cancelled',
            message=_t(log_language, 'worker_cancelled', name=inpath.name),
            orig_size=orig_size,
            out_size=orig_size,
            processed=False,
            cancelled=True,
        )

    processed = False
    final_outpath: str | None = None
    kept_original_reason = None
    cancelled = False
    notes = ''
    image_target_extension = converted_image_extension(ext, image_config)
    is_image_task = ext in {'jpg', 'jpeg', 'png'} or (ext == 'avif' and image_config.avif_to_jpeg_compat)
    if image_target_extension is None:
        outdir = outpath.parent
        if not outdir.exists():
            outdir.mkdir(parents=True, exist_ok=True)
    if ext in VIDEO_EXTENSIONS and video_config is not None:
        missing = [
            name
            for name, value in (
                ('capabilities', capabilities),
                ('job_control', job_control),
                ('video_temp_dir', video_temp_dir),
            )
            if value is None
        ]
        if missing:
            raise ValueError(f'video task is missing required fields: {", ".join(missing)}')
        if job_control is None:
            raise ValueError('video task is missing required field: job_control')
        video_result = compress_video_ffmpeg(
            str(inpath),
            str(outpath),
            str(original_outpath or outpath),
            video_config,
            capabilities=capabilities,
            job_control=job_control,
            temp_dir=Path(video_temp_dir),
            progress_callback=video_progress_callback,
            log_language=log_language,
        )
        processed = video_result.ok
        base_msg = video_result.message
        final_outpath = video_result.final_outpath
        kept_original_reason = video_result.kept_original_reason
        cancelled = video_result.cancelled
        notes = ';'.join(video_result.notes)
    elif ext == 'pdf':
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
    elif is_image_task:
        if image_target_extension is not None and (original_outpath is None or job_control is None or image_temp_dir is None):
            raise ValueError('converted image task requires original_outpath, job_control and image_temp_dir')
        image_result = _process_image_task(
            inpath,
            outpath,
            Path(original_outpath or outpath),
            ext,
            image_config=image_config,
            jpg_quality=jpg_quality,
            png_quality=png_quality,
            use_pngquant=use_pngquant,
            resize_cfg=resize_cfg,
            job_control=job_control,
            temp_dir=Path(image_temp_dir) if image_temp_dir is not None else None,
            log_language=log_language,
        )
        processed = image_result.ok
        base_msg = image_result.message
        final_outpath = image_result.final_outpath
        kept_original_reason = image_result.kept_original_reason
        cancelled = image_result.cancelled
        notes = ';'.join(image_result.notes)
    else:
        try:
            # 対象外ファイルは orchestrator 側で必要ならコピーするため、ここでは理由だけ返す。
            base_msg = _t(log_language, 'worker_unsupported', name=inpath.name)
        except Exception as e:
            base_msg = _t(log_language, 'worker_unsupported_failed', name=inpath.name, exc=e)

    try:
        if final_outpath is not None:
            out_size = Path(final_outpath).stat().st_size
        elif is_image_task:
            # 過去の出力があっても、今回配置していない画像のサイズには使わない。
            out_size = 0
        elif ext in VIDEO_EXTENSIONS and video_config is not None:
            # 配置されていない動画失敗は、出力先に残った過去の成果物を出力サイズとして数えない。
            out_size = orig_size
        else:
            out_size = outpath.stat().st_size if outpath.exists() else orig_size
    except OSError as exc:
        if is_image_task:
            processed = False
            out_size = None
            base_msg = _t(log_language, 'image_conversion_failed', name=inpath.name, detail=str(exc))
        else:
            out_size = orig_size

    action_key = _csv_action_key(
        ext,
        processed,
        kept_original_reason=kept_original_reason,
        cancelled=cancelled,
        image_target_extension=image_target_extension,
    )
    msg = base_msg if out_size is None or (is_image_task and not processed) else compose_worker_message(base_msg, orig_size, out_size, log_language)
    return WorkerFileResult(
        action_key=action_key,
        message=msg,
        orig_size=orig_size,
        out_size=out_size,
        processed=processed,
        final_outpath=final_outpath,
        kept_original_reason=kept_original_reason,
        cancelled=cancelled,
        notes=notes,
    )
