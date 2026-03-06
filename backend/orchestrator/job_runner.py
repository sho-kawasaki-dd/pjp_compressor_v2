from __future__ import annotations

import csv
import multiprocessing
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from shared.configs import (
    GS_DEFAULT_PRESET,
    PDF_LOSSLESS_OPTIONS_DEFAULT,
    PDF_LOSSY_DPI_DEFAULT,
    PDF_LOSSY_JPEG_QUALITY_DEFAULT,
    PDF_LOSSY_PNG_TO_JPEG_DEFAULT,
)

from backend.services.archive_service import extract_zip_archives
from backend.contracts import CompressionRequest, ProgressEvent


def run_compression_job(
    input_dir: str,
    output_dir: str,
    jpg_quality: int,
    png_quality: int,
    use_pngquant: bool,
    log_func: Callable[[str], None],
    progress_func: Callable[[int, int], None],
    stats_func: Callable[[int, int, int, float], None],
    pdf_engine: str = 'native',
    pdf_mode: str = 'both',
    pdf_dpi: int = PDF_LOSSY_DPI_DEFAULT,
    pdf_jpeg_quality: int = PDF_LOSSY_JPEG_QUALITY_DEFAULT,
    pdf_png_to_jpeg: bool = PDF_LOSSY_PNG_TO_JPEG_DEFAULT,
    pdf_lossless_options: dict[str, Any] | None = None,
    gs_preset: str = GS_DEFAULT_PRESET,
    gs_custom_dpi: int | None = None,
    resize_enabled: bool | dict[str, Any] = False,
    resize_width: int = 0,
    resize_height: int = 0,
    csv_enable: bool = True,
    csv_path: str | None = None,
    extract_zip: bool = False,
    copy_non_target_files: bool = False,
) -> None:
    from backend.core.format_utils import human_readable
    from backend.core.worker_ops import process_single_file

    input_base = Path(input_dir)
    output_base = Path(output_dir)

    if extract_zip:
        log_func("ZIPファイルを展開してから圧縮を行います…")
        extracted_cnt, failed_cnt = extract_zip_archives(input_base, log_func)
        if extracted_cnt == 0 and failed_cnt == 0:
            log_func("ZIPファイルは検出されませんでした。")
        elif failed_cnt > 0:
            log_func(f"ZIP展開結果: 成功 {extracted_cnt} 件 / 失敗 {failed_cnt} 件")
        else:
            log_func(f"ZIP展開結果: {extracted_cnt} 件の ZIP を展開しました。")

    total_files: list[Path] = []
    for file_path in input_base.rglob('*'):
        if not file_path.is_file() or file_path.suffix.lower() == '.zip':
            continue
        total_files.append(file_path)

    total_len = len(total_files)
    if total_len == 0:
        log_func("入力フォルダにファイルが見つかりませんでした。")
        log_func("完了！")
        progress_func(1, 1)
        stats_func(0, 0, 0, 0.0)
        return

    tasks = []
    for inpath in total_files:
        fname = inpath.name
        ext = inpath.suffix.lower().lstrip('.')
        rel_dir = inpath.parent.relative_to(input_base)
        outdir = output_base / rel_dir
        outpath = outdir / fname

        if pdf_lossless_options is None:
            ll_opts = dict(PDF_LOSSLESS_OPTIONS_DEFAULT)
        else:
            ll_opts = pdf_lossless_options

        rcfg = None
        if isinstance(resize_enabled, dict):
            rcfg = resize_enabled
        else:
            if resize_enabled and (resize_width > 0 or resize_height > 0):
                rcfg = {
                    'enabled': True,
                    'mode': 'manual',
                    'width': int(resize_width),
                    'height': int(resize_height),
                    'keep_aspect': True,
                }

        tasks.append((
            str(inpath),
            str(outpath),
            ext,
            pdf_engine,
            pdf_mode,
            pdf_dpi,
            pdf_jpeg_quality,
            pdf_png_to_jpeg,
            ll_opts,
            gs_preset,
            gs_custom_dpi,
            jpg_quality,
            png_quality,
            use_pngquant,
            rcfg,
        ))

    max_workers = max(4, multiprocessing.cpu_count())
    log_func(f"並列処理開始（ワーカー数: {max_workers}、ファイル数: {total_len}）")

    csv_file = None
    csv_writer = None
    if csv_enable:
        try:
            csv_path_obj: Path
            if not csv_path:
                ts = datetime.now().strftime('%Y%m%d_%H%M%S')
                csv_path_obj = output_base / f"compression_log_{ts}.csv"
            else:
                csv_path_obj = Path(csv_path)

            csv_path_obj.parent.mkdir(parents=True, exist_ok=True)
            csv_file = open(csv_path_obj, 'w', newline='', encoding='utf-8')
            csv_writer = csv.writer(csv_file)
            csv_writer.writerow([
                'timestamp', 'input_path', 'output_path', 'ext', 'action',
                'orig_size', 'out_size', 'saved_bytes', 'saved_pct', 'notes',
            ])
            log_func(f"CSVログ出力: {csv_path_obj}")
        except Exception as exc:
            log_func(f"CSVログの作成に失敗しました: {exc}")
            csv_file = None
            csv_writer = None

    cnt = 0
    orig_total = 0
    out_total = 0
    processed_files = 0
    compressible_extensions = {'pdf', 'jpg', 'jpeg', 'png'}

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(process_single_file, task): task for task in tasks}
        for future in as_completed(futures):
            try:
                msg, orig_size, out_size, processed_flag = future.result()
                if processed_flag:
                    orig_total += orig_size
                    out_total += out_size
                    processed_files += 1
                elif copy_non_target_files:
                    task = futures[future]
                    inpath_task = Path(task[0])
                    outpath_task = Path(task[1])
                    ext_task = task[2]
                    is_non_target = ext_task not in compressible_extensions
                    try:
                        outpath_task.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(inpath_task, outpath_task)
                        rel_src = inpath_task.relative_to(input_base)
                        if is_non_target:
                            log_func(f"対象外コピー: {rel_src}")
                        else:
                            log_func(f"圧縮失敗のためフォールバックコピー: {rel_src}")
                    except Exception as copy_exc:
                        rel_src = inpath_task if not inpath_task.is_absolute() else inpath_task.name
                        log_func(f"コピー失敗: {rel_src} ({copy_exc})")

                cnt += 1
                log_func(msg)

                try:
                    if csv_writer:
                        action = msg.split(' | ')[0]
                        saved = orig_size - out_size
                        saved_pct = (saved / orig_size * 100) if orig_size > 0 else 0.0
                        timestamp = datetime.now().isoformat()
                        task = futures[future]
                        inpath_task = task[0]
                        outpath_task = task[1]
                        ext_task = task[2]
                        inpath_rel = str(Path(inpath_task).relative_to(input_base))
                        outpath_rel = str(Path(outpath_task).relative_to(output_base))
                        csv_writer.writerow([
                            timestamp,
                            inpath_rel,
                            outpath_rel,
                            ext_task,
                            action,
                            orig_size,
                            out_size,
                            saved,
                            f"{saved_pct:.1f}",
                            '',
                        ])
                except Exception:
                    pass

                progress_func(cnt, total_len)
            except Exception as exc:
                log_func(f"処理中にエラー発生: {exc}")
                cnt += 1
                progress_func(cnt, total_len)

    try:
        if csv_file:
            csv_file.close()
    except Exception:
        pass

    saved = orig_total - out_total
    saved_pct = (saved / orig_total * 100) if orig_total > 0 else 0.0
    log_func("完了！")
    log_func(
        f"統計（圧縮対象 {processed_files} 件）: "
        f"元合計={human_readable(orig_total)}, "
        f"出力合計={human_readable(out_total)}, "
        f"削減={human_readable(saved)} ({saved_pct:.1f}%)"
    )
    stats_func(orig_total, out_total, saved, saved_pct)


def run_compression_request(
    request: CompressionRequest,
    event_callback: Callable[[ProgressEvent], None],
) -> None:
    def on_log(message: str) -> None:
        event_callback(ProgressEvent(kind='log', message=message))

    def on_progress(current: int, total: int) -> None:
        event_callback(ProgressEvent(kind='progress', current=current, total=total))

    def on_stats(orig_total: int, out_total: int, saved: int, saved_pct: float) -> None:
        event_callback(
            ProgressEvent(
                kind='stats',
                orig_total=orig_total,
                out_total=out_total,
                saved=saved,
                saved_pct=saved_pct,
            )
        )

    try:
        run_compression_job(
            input_dir=request.input_dir,
            output_dir=request.output_dir,
            jpg_quality=request.jpg_quality,
            png_quality=request.png_quality,
            use_pngquant=request.use_pngquant,
            log_func=on_log,
            progress_func=on_progress,
            stats_func=on_stats,
            pdf_engine=request.pdf_engine,
            pdf_mode=request.pdf_mode,
            pdf_dpi=request.pdf_dpi,
            pdf_jpeg_quality=request.pdf_jpeg_quality,
            pdf_png_to_jpeg=request.pdf_png_to_jpeg,
            pdf_lossless_options=request.pdf_lossless_options,
            gs_preset=request.gs_preset,
            gs_custom_dpi=request.gs_custom_dpi,
            resize_enabled=request.resize_config,
            resize_width=request.resize_width,
            resize_height=request.resize_height,
            csv_enable=request.csv_enable,
            csv_path=request.csv_path,
            extract_zip=request.extract_zip,
            copy_non_target_files=request.copy_non_target_files,
        )
    except Exception as exc:
        event_callback(ProgressEvent(kind='error', message=f"処理中にエラー発生: {exc}"))
