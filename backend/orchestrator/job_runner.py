from __future__ import annotations

"""圧縮ジョブ全体の段取りを管理する。

この層は個別圧縮アルゴリズムを持たず、入力走査、ZIP 展開、タスク生成、
並列実行、CSV 出力、進捗通知をまとめて担当する。
"""

import csv
import multiprocessing
import shutil
import tempfile
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


def _safe_rel(path: Path, base: Path) -> str:
    """基準ディレクトリに対する相対パスを安全に返す。"""
    try:
        return str(path.relative_to(base))
    except Exception:
        return path.name


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
    """入力フォルダ全体を走査し、圧縮ジョブを最後まで実行する。

    主な責務は以下の通り。
    - 通常ファイルと ZIP 展開後ファイルを単一のタスク列へ統合する
    - ワーカースレッドへ個別処理を投げ、進捗と統計を逐次通知する
    - CSV ログやフォールバックコピーを含むジョブ全体の付帯処理を管理する
    """

    from backend.core.format_utils import human_readable
    from backend.core.worker_ops import process_single_file

    input_base = Path(input_dir)
    output_base = Path(output_dir)

    zip_files: list[Path] = [
        path for path in input_base.rglob('*.zip') if path.is_file()
    ]

    zip_output_copies: list[tuple[Path, Path, str, str]] = []
    temp_extract_root: Path | None = None
    if copy_non_target_files:
        # mirror モードでは ZIP 自体も出力へ残し、展開結果と元 ZIP の両方を保持する。
        for zip_path in zip_files:
            rel_zip = zip_path.relative_to(input_base)
            out_zip = output_base / rel_zip
            zip_output_copies.append((
                zip_path,
                out_zip,
                str(rel_zip),
                str(rel_zip),
            ))

    # worker task tuple:
    # (
    #   inpath, outpath, ext,
    #   pdf_engine, pdf_mode, pdf_dpi, pdf_jpeg_quality, pdf_png_to_jpeg,
    #   pdf_lossless_options, gs_preset, gs_custom_dpi,
    #   jpg_quality, png_quality, use_pngquant, resize_cfg,
    #   csv_input_path, csv_output_path,
    # )
    tasks: list[tuple[Any, ...]] = []

    def append_task(inpath: Path, outpath: Path, csv_input_path: str, csv_output_path: str) -> None:
        """ワーカーへ渡すタスク 1 件を構築する。"""
        ext = inpath.suffix.lower().lstrip('.')

        if pdf_lossless_options is None:
            ll_opts = dict(PDF_LOSSLESS_OPTIONS_DEFAULT)
        else:
            ll_opts = pdf_lossless_options

        rcfg = None
        if isinstance(resize_enabled, dict):
            # 新 API では resize 情報を dict で受け取るため、そのまま優先採用する。
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
            csv_input_path,
            csv_output_path,
        ))

    # Normal files in input directory (non-ZIP): always keep existing behavior.
    for file_path in input_base.rglob('*'):
        if not file_path.is_file() or file_path.suffix.lower() == '.zip':
            continue
        rel_path = file_path.relative_to(input_base)
        outpath = output_base / rel_path
        append_task(file_path, outpath, str(rel_path), str(rel_path))

    # ZIP extraction: done in temporary workspace so input directory remains unchanged.
    if extract_zip:
        if zip_files:
            log_func("ZIPファイルを展開してから圧縮を行います…")
            temp_extract_root = Path(tempfile.mkdtemp(prefix='pjp_zip_extract_'))
            temp_root = temp_extract_root
            extracted_cnt_total = 0
            failed_cnt_total = 0

            for zip_path in zip_files:
                rel_zip = zip_path.relative_to(input_base)
                # 入力フォルダを直接書き換えないため、ZIP ごとに一時 staging 領域へ複製する。
                staged_root = temp_root / rel_zip.parent / zip_path.stem
                staged_root.mkdir(parents=True, exist_ok=True)
                staged_zip = staged_root / zip_path.name
                shutil.copy2(zip_path, staged_zip)

                extracted_cnt, failed_cnt = extract_zip_archives(staged_root, log_func)
                extracted_cnt_total += extracted_cnt
                failed_cnt_total += failed_cnt

                output_zip_root = output_base / rel_zip.parent / zip_path.stem
                for extracted_file in staged_root.rglob('*'):
                    if not extracted_file.is_file() or extracted_file.suffix.lower() == '.zip':
                        continue
                    # CSV では「どの ZIP の中のどのファイルか」が分かるよう `zip::path` 形式で残す。
                    rel_inside_zip = extracted_file.relative_to(staged_root)
                    outpath = output_zip_root / rel_inside_zip
                    csv_input = f"{rel_zip.as_posix()}::{rel_inside_zip.as_posix()}"
                    csv_output = str((rel_zip.parent / zip_path.stem / rel_inside_zip).as_posix())
                    append_task(extracted_file, outpath, csv_input, csv_output)

            if extracted_cnt_total == 0 and failed_cnt_total == 0:
                log_func("ZIPファイルは検出されませんでした。")
            elif failed_cnt_total > 0:
                log_func(f"ZIP展開結果: 成功 {extracted_cnt_total} 件 / 失敗 {failed_cnt_total} 件")
            else:
                log_func(f"ZIP展開結果: {extracted_cnt_total} 件の ZIP を展開しました。")
        else:
            log_func("ZIPファイルは検出されませんでした。")

    total_len = len(tasks) + len(zip_output_copies)
    if total_len == 0:
        log_func("入力フォルダにファイルが見つかりませんでした。")
        log_func("完了！")
        progress_func(1, 1)
        stats_func(0, 0, 0, 0.0)
        if temp_extract_root:
            shutil.rmtree(temp_extract_root, ignore_errors=True)
        return

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
            # 先頭にヘッダを書いておくことで、途中失敗時も解析しやすい CSV を維持する。
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

    # Mirror mode for ZIP files: copy original ZIPs to output.
    for in_zip, out_zip, csv_input, csv_output in zip_output_copies:
        try:
            out_zip.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(in_zip, out_zip)
            log_func(f"ZIPコピー: {_safe_rel(in_zip, input_base)}")
            if csv_writer:
                timestamp = datetime.now().isoformat()
                size_val = in_zip.stat().st_size
                csv_writer.writerow([
                    timestamp,
                    csv_input,
                    csv_output,
                    'zip',
                    'ZIPコピー',
                    size_val,
                    size_val,
                    0,
                    '0.0',
                    '',
                ])
        except Exception as copy_exc:
            log_func(f"ZIPコピー失敗: {_safe_rel(in_zip, input_base)} ({copy_exc})")
        cnt += 1
        progress_func(cnt, total_len)

    if tasks:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(process_single_file, task): task for task in tasks}
            for future in as_completed(futures):
                try:
                    msg, orig_size, out_size, processed_flag = future.result()
                    task = futures[future]
                    inpath_task = Path(task[0])
                    outpath_task = Path(task[1])
                    ext_task = task[2]
                    csv_input = task[15]
                    csv_output = task[16]

                    if processed_flag:
                        orig_total += orig_size
                        out_total += out_size
                        processed_files += 1
                    elif copy_non_target_files:
                        # 非圧縮対象や圧縮失敗ファイルも mirror モードでは出力に揃えておく。
                        is_non_target = ext_task not in compressible_extensions
                        try:
                            outpath_task.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(inpath_task, outpath_task)
                            if is_non_target:
                                log_func(f"対象外コピー: {csv_input}")
                            else:
                                log_func(f"圧縮失敗のためフォールバックコピー: {csv_input}")
                        except Exception as copy_exc:
                            log_func(f"コピー失敗: {csv_input} ({copy_exc})")

                    cnt += 1
                    log_func(msg)

                    try:
                        if csv_writer:
                            # 画面ログと CSV の action を揃えるため、メッセージ先頭を action 名として使う。
                            action = msg.split(' | ')[0]
                            saved = orig_size - out_size
                            saved_pct = (saved / orig_size * 100) if orig_size > 0 else 0.0
                            timestamp = datetime.now().isoformat()
                            csv_writer.writerow([
                                timestamp,
                                csv_input,
                                csv_output,
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
    if temp_extract_root:
        shutil.rmtree(temp_extract_root, ignore_errors=True)
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
    """`CompressionRequest` ベースの新 API をイベント駆動で実行する。"""

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
