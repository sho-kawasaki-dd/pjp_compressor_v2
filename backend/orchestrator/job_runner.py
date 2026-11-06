from __future__ import annotations

"""圧縮ジョブ全体の段取りを管理する。

この層は個別圧縮アルゴリズムを持たず、入力走査、ZIP 展開、タスク生成、
並列実行、CSV 出力、進捗通知をまとめて担当する。

設計上の要点は、入力フォルダを直接変更しないことと、UI が理解しやすい形で
ジョブ全体の状態をイベントへ落とし直すことである。圧縮そのものよりも、
安全な一時作業領域と一貫したログ/CSV/進捗の整合性を守る責務が大きい。
"""

import csv
import multiprocessing
import shutil
import tempfile
from contextlib import ExitStack
from dataclasses import dataclass
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from backend.settings import (
    APP_WORK_DIR_NAME,
    GS_DEFAULT_PRESET,
    IMAGE_WORK_OWNER_TOKEN,
    IMAGE_WORK_SUBDIR,
    PDF_LOSSLESS_OPTIONS_DEFAULT,
    PDF_LOSSY_DPI_DEFAULT,
    PDF_LOSSY_JPEG_QUALITY_DEFAULT,
    PDF_LOSSY_PNG_QUALITY_DEFAULT,
    VIDEO_EXTENSIONS,
)

from backend.capabilities import detect_capabilities
from backend.services.archive_service import extract_zip_archives
from backend.services.video_service import (
    cleanup_stale_video_temps,
    create_video_job_dir,
    place_original_copy,
    terminate_active_video_processes,
    tool_unavailable_reason,
)
from backend.core.archive_utils import zip_directory
from backend.core.image_utils import (
    cleanup_stale_image_temps,
    converted_image_extension,
    create_image_job_dir,
    place_image_original_copy,
)
from backend.core.job_files import remove_owned_job_dir
from backend.contracts import (
    CapabilityReport,
    CompressionRequest,
    ImageCompressionConfig,
    JobControl,
    ProgressEvent,
    ToolSource,
    VideoCompressionConfig,
)
from backend.orchestrator.job_lock import OutputLockError, acquire_output_lock
from shared.locale_catalog import load_locale_catalog, translate as locale_translate
from shared.path_utils import paths_overlap
from shared.runtime_paths import describe_tool_source


def _safe_rel(path: Path, base: Path) -> str:
    """基準ディレクトリに対する相対パスを安全に返す。"""
    try:
        return str(path.relative_to(base))
    except Exception:
        return path.name


@dataclass(frozen=True)
class ZipOutputPlan:
    """1 つの ZIP 入力に対する出力関連パスをまとめる。"""

    input_zip_path: Path
    relative_zip_path: Path
    folder_output_root: Path
    archive_output_path: Path

    def staged_root_for(self, temp_root: Path) -> Path:
        """一時展開先を ZIP ごとに決める。"""
        return temp_root / self.relative_zip_path.parent / self.input_zip_path.stem

    def csv_input_path_for(self, rel_inside_zip: Path) -> str:
        """CSV に残す ZIP 内パス表現を返す。"""
        return f"{self.relative_zip_path.as_posix()}::{rel_inside_zip.as_posix()}"

    def csv_output_path_for(self, rel_inside_zip: Path) -> str:
        """CSV に残す最終出力側パス表現を返す。"""
        return str((self.relative_zip_path.parent / self.folder_output_root.name / rel_inside_zip).as_posix())

    def csv_notes_for(self, output_base: Path) -> str:
        """CSV の notes 列へ残す ZIP 再生成先を返す。"""
        try:
            archive_rel = self.archive_output_path.relative_to(output_base).as_posix()
        except Exception:
            archive_rel = self.archive_output_path.as_posix()
        return f'zip_archive={archive_rel}'


def _build_zip_output_plan(input_base: Path, output_base: Path, zip_path: Path) -> ZipOutputPlan:
    """ZIP 1 件ぶんの出力用パスをまとめて決める。"""
    relative_zip_path = zip_path.relative_to(input_base)
    folder_output_root = output_base / relative_zip_path.parent / zip_path.stem
    archive_output_path = folder_output_root.parent / f"{folder_output_root.name}.zip"
    return ZipOutputPlan(
        input_zip_path=zip_path,
        relative_zip_path=relative_zip_path,
        folder_output_root=folder_output_root,
        archive_output_path=archive_output_path,
    )


def _format_message(catalog: dict[str, str], key: str, **kwargs: Any) -> str:
    """ロケール catalog から文言を取得し、フォーマット失敗時も落とさない。"""
    template = catalog.get(key, key)
    try:
        return template.format(**kwargs)
    except Exception:
        return template


def _csv_headers(catalog: dict[str, str]) -> list[str]:
    """CSV 1 行目のヘッダを locale から組み立てる。"""
    return [
        catalog.get('csv_header_timestamp', 'timestamp'),
        catalog.get('csv_header_input_path', 'input_path'),
        catalog.get('csv_header_output_path', 'output_path'),
        catalog.get('csv_header_ext', 'ext'),
        catalog.get('csv_header_action', 'action'),
        catalog.get('csv_header_orig_size', 'orig_size'),
        catalog.get('csv_header_out_size', 'out_size'),
        catalog.get('csv_header_saved_bytes', 'saved_bytes'),
        catalog.get('csv_header_saved_pct', 'saved_pct'),
        catalog.get('csv_header_notes', 'notes'),
    ]


def _csv_action_label(catalog: dict[str, str], ext: str, *, processed: bool) -> str:
    """CSV の action 列に入れる処理種別ラベルを返す。"""
    if ext == 'pdf':
        return catalog.get('csv_action_pdf', 'PDF compression')
    if ext in {'jpg', 'jpeg'}:
        return catalog.get('csv_action_jpeg', 'JPEG compression')
    if ext == 'png':
        return catalog.get('csv_action_png', 'PNG compression')
    if ext in VIDEO_EXTENSIONS and processed:
        return catalog.get('csv_action_video', 'Video compression')
    if processed:
        return catalog.get('csv_action_unknown', 'Unknown')
    return catalog.get('csv_action_failed', 'Compression failed')


def _video_tool_part(catalog: dict[str, str], label_key: str, default_label: str, source: ToolSource, error: str | None) -> str:
    label = catalog.get(label_key, default_label)
    detected = catalog.get(f'tool_source.{source}', describe_tool_source(source))
    return f'{label}{detected} ({error})' if error else f'{label}{detected}'


def _tool_detection_summary(catalog: dict[str, str], report: CapabilityReport) -> str:
    """起動時ログに出す外部ツール検出要約を返す。

    検出結果はジョブ開始時に 1 回だけ取得したものを受け取り、ここでは再検出しない。
    """
    parts = [
        catalog.get('capability_fitz_ok', 'PyMuPDF:OK') if report.fitz_available else catalog.get('capability_fitz_missing', 'PyMuPDF:なし'),
        catalog.get('capability_pikepdf_ok', 'pikepdf:OK') if report.pikepdf_available else catalog.get('capability_pikepdf_missing', 'pikepdf:なし'),
        f"{catalog.get('capability_ghostscript_label', 'Ghostscript=')}{catalog.get(f'tool_source.{report.ghostscript_source}', describe_tool_source(report.ghostscript_source))}",
        f"{catalog.get('capability_pngquant_label', 'pngquant:')}{catalog.get(f'tool_source.{report.pngquant_source}', describe_tool_source(report.pngquant_source))}",
        _video_tool_part(
            catalog, 'capability_ffmpeg_label', 'ffmpeg:', report.ffmpeg_source,
            report.ffmpeg_detection_error or report.ffmpeg_decoder_detection_error,
        ),
        _video_tool_part(catalog, 'capability_ffprobe_label', 'ffprobe:', report.ffprobe_source, report.ffprobe_detection_error),
    ]
    return _format_message(catalog, 'log_dependency_detection_summary', parts=', '.join(parts))


@dataclass(frozen=True)
class _TaskCandidate:
    """出力パス確定前のタスク候補。通常走査分と ZIP 展開分で共通に使う。"""

    inpath: Path
    outpath: Path  # 入力と同じ拡張子の既定出力先
    csv_input: str
    csv_output: str
    csv_notes: str


@dataclass(frozen=True)
class _PlannedOutput:
    outpath: Path
    original_outpath: Path


def _plan_converted_outputs(
    candidates: list[_TaskCandidate],
    target_extension: Callable[[_TaskCandidate], str | None],
) -> dict[int, _PlannedOutput]:
    """変換先と元拡張子の出力名を、ジョブ内の候補同士で衝突しないよう決める。

    出力フォルダの既存ファイルは判定に含めないため、同じ入力・出力先で再実行しても名前は
    変わらない。キーは Windows の大文字小文字非区別に合わせて casefold する。
    """
    claimed = {str(candidate.outpath).casefold() for candidate in candidates}
    reserved_originals: set[str] = set()
    original_paths: dict[int, Path] = {}
    indexes = sorted(
        range(len(candidates)),
        key=lambda index: (
            str(candidates[index].outpath).casefold(),
            candidates[index].csv_input.casefold(),
            candidates[index].csv_input,
        ),
    )
    for index in indexes:
        candidate = candidates[index]
        path = candidate.outpath
        key = str(path).casefold()
        if key in reserved_originals:
            src_ext = candidate.inpath.suffix.lower().lstrip('.') or 'file'
            for name in _candidate_converted_names(path.stem, src_ext, path.suffix):
                proposed = path.parent / name
                if str(proposed).casefold() not in claimed:
                    path = proposed
                    claimed.add(str(path).casefold())
                    break
        reserved_originals.add(str(path).casefold())
        original_paths[index] = path

    planned: dict[int, _PlannedOutput] = {}
    for index in indexes:
        candidate = candidates[index]
        original = original_paths[index]
        extension = target_extension(candidate)
        if extension is None or extension.casefold() == original.suffix.casefold():
            planned[index] = _PlannedOutput(original, original)
            continue
        src_ext = candidate.inpath.suffix.lower().lstrip('.') or 'file'
        for name in _candidate_converted_names(original.stem, src_ext, extension):
            path = original.parent / name
            if str(path).casefold() not in claimed:
                claimed.add(str(path).casefold())
                planned[index] = _PlannedOutput(path, original)
                break
    return planned


def _candidate_converted_names(stem: str, src_ext: str, target_ext: str):
    """`stem.ext` → `stem_{src_ext}.ext` → `stem_{src_ext}_2.ext` の順に返す。"""
    yield f'{stem}{target_ext}'
    yield f'{stem}_{src_ext}{target_ext}'
    serial = 2
    while True:
        yield f'{stem}_{src_ext}_{serial}{target_ext}'
        serial += 1


def _normalize_video_config(config: VideoCompressionConfig | dict[str, Any] | None) -> VideoCompressionConfig | None:
    if config is None or isinstance(config, VideoCompressionConfig):
        return config
    return VideoCompressionConfig.from_mapping(config)


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
    pdf_png_quality: int = PDF_LOSSY_PNG_QUALITY_DEFAULT,
    pdf_lossless_options: dict[str, Any] | None = None,
    gs_preset: str = GS_DEFAULT_PRESET,
    gs_custom_dpi: int | None = None,
    resize_enabled: bool | dict[str, Any] = False,
    resize_width: int = 0,
    resize_height: int = 0,
    csv_enable: bool = True,
    csv_path: str | None = None,
    extract_zip: bool = False,
    zip_output_enabled: bool = False,
    debug_mode: bool = False,
    copy_non_target_files: bool = False,
    log_language: str = 'ja',
    video_config: VideoCompressionConfig | dict[str, Any] | None = None,
    event_func: Callable[[ProgressEvent], None] | None = None,
    job_control: JobControl | None = None,
) -> None:
    """入力フォルダ全体を走査し、圧縮ジョブを最後まで実行する。

    主な責務は以下の通り。
    - 入出力の重なりを拒否し、出力フォルダの排他ロックをジョブ全体で保持する
    - 通常ファイルと ZIP 展開後ファイルを単一のタスク列へ統合する
    - ワーカースレッドへ個別処理を投げ、進捗と統計を逐次通知する
    - CSV ログやフォールバックコピーを含むジョブ全体の付帯処理を管理する

        WHY:
        - UI や CLI 入口から見える振る舞いを 1 箇所へ集め、圧縮アルゴリズム層へ
            ZIP やミラー圧縮の事情を漏らさない
        - 入力フォルダを不変に保つことで、失敗時も元データを調査できるようにする
        - ログ、CSV、進捗が同じ単位で増えるようにし、利用者とテストの両方が
            処理結果を追跡しやすくする
    """
    catalog = load_locale_catalog(log_language)

    if paths_overlap(input_dir, output_dir):
        raise ValueError(_format_message(catalog, 'log_folders_overlap_error', input=input_dir, output=output_dir))
    normalized_video_config = _normalize_video_config(video_config)
    control = job_control if job_control is not None else JobControl()

    try:
        output_lock = acquire_output_lock(output_dir)
    except OutputLockError as exc:
        raise OutputLockError(_format_message(catalog, 'log_output_in_use', path=output_dir)) from exc

    # 出力排他は executor・ZIP 再生成・CSV 閉鎖・一時領域掃除が終わるまで保持する。
    # ExitStack は後入れ先出しなので、先に登録したロック解放が最後に実行される。
    with ExitStack() as cleanup:
        cleanup.callback(output_lock.release)
        notify_finished = _run_locked_job(
            cleanup,
            control,
            normalized_video_config,
            input_dir=input_dir,
            output_dir=output_dir,
            jpg_quality=jpg_quality,
            png_quality=png_quality,
            use_pngquant=use_pngquant,
            log_func=log_func,
            progress_func=progress_func,
            stats_func=stats_func,
            event_func=event_func,
            pdf_engine=pdf_engine,
            pdf_mode=pdf_mode,
            pdf_dpi=pdf_dpi,
            pdf_jpeg_quality=pdf_jpeg_quality,
            pdf_png_quality=pdf_png_quality,
            pdf_lossless_options=pdf_lossless_options,
            gs_preset=gs_preset,
            gs_custom_dpi=gs_custom_dpi,
            resize_enabled=resize_enabled,
            resize_width=resize_width,
            resize_height=resize_height,
            csv_enable=csv_enable,
            csv_path=csv_path,
            extract_zip=extract_zip,
            zip_output_enabled=zip_output_enabled,
            debug_mode=debug_mode,
            copy_non_target_files=copy_non_target_files,
            log_language=log_language,
        )
    # 完了・中断の通知はロック解放後に行う。
    notify_finished()


def _run_locked_job(
    cleanup: ExitStack,
    control: JobControl,
    video_cfg: VideoCompressionConfig | None,
    *,
    input_dir: str,
    output_dir: str,
    jpg_quality: int,
    png_quality: int,
    use_pngquant: bool,
    log_func: Callable[[str], None],
    progress_func: Callable[[int, int], None],
    stats_func: Callable[[int, int, int, float], None],
    event_func: Callable[[ProgressEvent], None] | None,
    pdf_engine: str,
    pdf_mode: str,
    pdf_dpi: int,
    pdf_jpeg_quality: int,
    pdf_png_quality: int,
    pdf_lossless_options: dict[str, Any] | None,
    gs_preset: str,
    gs_custom_dpi: int | None,
    resize_enabled: bool | dict[str, Any],
    resize_width: int,
    resize_height: int,
    csv_enable: bool,
    csv_path: str | None,
    extract_zip: bool,
    zip_output_enabled: bool,
    debug_mode: bool,
    copy_non_target_files: bool,
    log_language: str,
) -> Callable[[], None]:
    """出力排他の取得後に実行するジョブ本体。

    後片付けは `cleanup` に登録して呼び出し側へ任せ、完了・中断の通知は戻り値の関数として返す。
    """

    from backend.core.worker_ops import WorkerFileResult, process_single_file
    from backend.core.format_utils import human_readable

    catalog = load_locale_catalog(log_language)

    def t(key: str, **kwargs: Any) -> str:
        return _format_message(catalog, key, **kwargs)

    input_base = Path(input_dir)
    output_base = Path(output_dir)

    def emit(event: ProgressEvent) -> None:
        if event_func is not None:
            event_func(event)

    def finish_cancelled(orig_total: int, out_total: int, processed_files: int, cancelled_files: int) -> Callable[[], None]:
        """中断を部分集計つきで通知する処理を返す。通常の完了ログ・統計は送らない。

        通知はロック解放後に呼び出し側が実行する（通知を受けて UI が再開始しても拒否されない）。
        """
        saved = orig_total - out_total
        saved_pct = (saved / orig_total * 100) if orig_total > 0 else 0.0
        message = t(
            'log_job_cancelled',
            processed_files=processed_files,
            cancelled_files=cancelled_files,
            orig_total=human_readable(orig_total),
            out_total=human_readable(out_total),
            saved=human_readable(saved),
            saved_pct=saved_pct,
        )

        def notify() -> None:
            if event_func is None:
                # 旧コールバック API にはイベント経路がないため、ログで中断理由を伝える。
                log_func(message)
            else:
                event_func(ProgressEvent(
                    kind='cancelled',
                    message=message,
                    orig_total=orig_total,
                    out_total=out_total,
                    saved=saved,
                    saved_pct=saved_pct,
                ))

        return notify

    if control.is_cancelled:
        return finish_cancelled(0, 0, 0, 0)

    # 前回の異常終了で残った作業領域は、排他を取得した今だけ安全に掃除できる。
    cleanup_stale_video_temps(output_base)
    cleanup_stale_image_temps(output_base)

    # 検出結果はジョブ開始時に 1 回だけ取得し、ワーカーへ渡して再解決させない。
    report = detect_capabilities()
    image_cfg = ImageCompressionConfig()
    video_unavailable_reason: str | None = None
    video_enabled = False
    if video_cfg is not None and video_cfg.enabled:
        video_unavailable_reason = tool_unavailable_reason(report, video_cfg, log_language)
        video_enabled = video_unavailable_reason is None

    zip_files: list[Path] = [
        path
        for path in input_base.rglob('*.zip')
        if path.is_file() and APP_WORK_DIR_NAME not in path.relative_to(input_base).parts
    ]

    # ミラー圧縮では ZIP 自体も 1 つの出力成果物として扱うため、圧縮タスクとは
    # 別に先行コピー対象を保持する。
    zip_output_plans: list[ZipOutputPlan] = [
        _build_zip_output_plan(input_base, output_base, zip_path)
        for zip_path in zip_files
    ]
    zip_output_copies: list[tuple[Path, Path, str, str]] = []
    temp_extract_root: Path | None = None
    if copy_non_target_files and not (extract_zip and zip_output_enabled):
        # ZIP を最終的に再生成する場合は、元 ZIP の別コピーは残さず 1 つの成果物にまとめる。
        for plan in zip_output_plans:
            zip_output_copies.append((
                plan.input_zip_path,
                plan.archive_output_path,
                plan.relative_zip_path.as_posix(),
                plan.relative_zip_path.as_posix(),
            ))

    # worker 側は 1 ファイル処理だけに集中させたいので、ログ/CSV に必要な入力文脈も
    # ここでタプルへ畳み込んで渡す。
    # worker task tuple:
    # (
    #   inpath, outpath, ext,
    #   pdf_engine, pdf_mode, pdf_dpi, pdf_jpeg_quality, pdf_png_quality,
    #   pdf_lossless_options, gs_preset, gs_custom_dpi,
    #   jpg_quality, png_quality, use_pngquant, resize_cfg, debug_mode,
    #   csv_input_path, csv_output_path, csv_notes, log_language,
    #   video_config, video_progress_callback, original_outpath,
    #   job_control, capabilities, video_temp_dir, image_config, image_temp_dir,
    # )
    #
    # 出力パスは全候補が出揃ってから、元拡張子のパスも含めて予約する。
    candidates: list[_TaskCandidate] = []

    def append_task(
        inpath: Path,
        outpath: Path,
        csv_input_path: str,
        csv_output_path: str,
        csv_notes: str = '',
    ) -> None:
        """タスク候補を収集する。出力パスの確定とタプル構築は全候補の収集後に行う。"""
        candidates.append(_TaskCandidate(inpath, outpath, csv_input_path, csv_output_path, csv_notes))

    rcfg = None
    if isinstance(resize_enabled, dict):
        # 新 API では resize 情報を dict で受け取るため、そのまま優先採用する。
        rcfg = resize_enabled
    elif resize_enabled and (resize_width > 0 or resize_height > 0):
        # 旧 API 互換の bool + width/height 指定も、worker には新形式 dict として渡す。
        rcfg = {
            'enabled': True,
            'mode': 'manual',
            'width': int(resize_width),
            'height': int(resize_height),
            'keep_aspect': True,
        }

    def is_video_candidate(candidate: _TaskCandidate) -> bool:
        return video_enabled and candidate.inpath.suffix.lower().lstrip('.') in VIDEO_EXTENSIONS

    def target_extension(candidate: _TaskCandidate) -> str | None:
        if is_video_candidate(candidate):
            return '.mp4'
        return converted_image_extension(candidate.inpath.suffix, image_cfg)

    # ZIP は展開有無で扱いが変わるため、通常走査からは除外して別フェーズへ回す。
    # アプリ専用作業領域は入力側にあっても処理対象にしない。
    for file_path in input_base.rglob('*'):
        if not file_path.is_file() or file_path.suffix.lower() == '.zip':
            continue
        rel_path = file_path.relative_to(input_base)
        if APP_WORK_DIR_NAME in rel_path.parts:
            continue
        outpath = output_base / rel_path
        append_task(file_path, outpath, str(rel_path), str(rel_path))

    # ZIP extraction: done in temporary workspace so input directory remains unchanged.
    if extract_zip:
        if zip_files:
            if zip_output_enabled:
                log_func(t('log_zip_output_mode_enabled'))
            log_func(t('log_zip_extract_start'))
            temp_extract_root = Path(tempfile.mkdtemp(prefix='pjp_zip_extract_'))
            cleanup.callback(shutil.rmtree, temp_extract_root, ignore_errors=True)
            temp_root = temp_extract_root
            extracted_cnt_total = 0
            failed_cnt_total = 0

            for plan in zip_output_plans:
                if control.is_cancelled:
                    break
                # 入力フォルダを直接書き換えないため、ZIP ごとに一時作業領域へ複製する。
                staged_root = plan.staged_root_for(temp_root)
                staged_root.mkdir(parents=True, exist_ok=True)
                staged_zip = staged_root / plan.input_zip_path.name
                shutil.copy2(plan.input_zip_path, staged_zip)

                extracted_cnt, failed_cnt = extract_zip_archives(staged_root, log_func, log_language=log_language)
                extracted_cnt_total += extracted_cnt
                failed_cnt_total += failed_cnt

                # 展開由来ファイルは `.../zip_stem/...` 配下へ揃えることで、出力だけ見ても
                # どの ZIP 由来かを復元できる。
                for extracted_file in staged_root.rglob('*'):
                    if not extracted_file.is_file() or extracted_file.suffix.lower() == '.zip':
                        continue
                    # CSV では「どの ZIP の中のどのファイルか」が分かるよう `zip::path` 形式で残す。
                    rel_inside_zip = extracted_file.relative_to(staged_root)
                    outpath = plan.folder_output_root / rel_inside_zip
                    csv_input = plan.csv_input_path_for(rel_inside_zip)
                    csv_output = plan.csv_output_path_for(rel_inside_zip)
                    csv_notes = plan.csv_notes_for(output_base) if zip_output_enabled else ''
                    append_task(extracted_file, outpath, csv_input, csv_output, csv_notes)

            if extracted_cnt_total == 0 and failed_cnt_total == 0:
                log_func(t('log_zip_not_found'))
            elif failed_cnt_total > 0:
                log_func(t('log_zip_extract_result_partial', extracted=extracted_cnt_total, failed=failed_cnt_total))
            else:
                log_func(t('log_zip_extract_result_success', extracted=extracted_cnt_total))
        else:
            log_func(t('log_zip_not_found'))

    if control.is_cancelled:
        return finish_cancelled(0, 0, 0, 0)

    # 進捗は「圧縮対象」と「mirror 用 ZIP コピー」の両方を 1 件として数える。
    total_len = len(candidates) + len(zip_output_copies)
    if total_len == 0:
        def notify_empty() -> None:
            log_func(t('log_empty_input'))
            log_func(t('log_complete'))
            progress_func(1, 1)
            stats_func(0, 0, 0, 0.0)

        return notify_empty

    if (
        video_unavailable_reason is not None
        and any(candidate.inpath.suffix.lower().lstrip('.') in VIDEO_EXTENSIONS for candidate in candidates)
    ):
        # 動画を処理できない理由は、動画が入力にあるときだけ通知する。
        log_func(t('video_tool_unavailable', reason=video_unavailable_reason))

    planned_outputs = _plan_converted_outputs(candidates, target_extension)

    video_job_dir: Path | None = None
    image_job_dir: Path | None = None
    general_tasks: list[tuple[Any, ...]] = []
    video_tasks: list[tuple[Any, ...]] = []

    def make_video_callback(name: str) -> Callable[[int | None], None] | None:
        callback = event_func
        if callback is None:
            return None

        def on_video_update(pct: int | None) -> None:
            # 割合不明の None も更新として扱い、開始・終了イベントとは混同させない。
            callback(ProgressEvent(kind='video_progress', message=name, current=pct, video_phase='updated'))

        return on_video_update

    for index, candidate in enumerate(candidates):
        ext = candidate.inpath.suffix.lower().lstrip('.')
        is_video = is_video_candidate(candidate)
        is_converted_image = converted_image_extension(ext, image_cfg) is not None
        planned = planned_outputs[index]
        if is_video and video_job_dir is None:
            video_job_dir = create_video_job_dir(output_base)
            cleanup.callback(shutil.rmtree, video_job_dir, ignore_errors=True)
        if is_converted_image and image_job_dir is None:
            image_job_dir = create_image_job_dir(output_base)

            def cleanup_image_dir(path: Path) -> None:
                try:
                    remove_owned_job_dir(output_base, IMAGE_WORK_SUBDIR, path, IMAGE_WORK_OWNER_TOKEN)
                except OSError as exc:
                    log_func(t('image_work_cleanup_failed', detail=str(exc)))

            cleanup.callback(cleanup_image_dir, image_job_dir)

        if pdf_lossless_options is None:
            # 可変 dict を共有すると task ごとの編集が他へ波及するため既定値は複製する。
            ll_opts = dict(PDF_LOSSLESS_OPTIONS_DEFAULT)
        else:
            ll_opts = pdf_lossless_options

        task = (
            str(candidate.inpath),
            str(planned.outpath),
            ext,
            pdf_engine,
            pdf_mode,
            pdf_dpi,
            pdf_jpeg_quality,
            pdf_png_quality,
            ll_opts,
            gs_preset,
            gs_custom_dpi,
            jpg_quality,
            png_quality,
            use_pngquant,
            rcfg,
            debug_mode,
            candidate.csv_input,
            planned.outpath.relative_to(output_base).as_posix(),
            candidate.csv_notes,
            log_language,
            video_cfg if is_video else None,
            make_video_callback(candidate.inpath.name) if is_video else None,
            str(planned.original_outpath),
            control,
            report,
            str(video_job_dir) if is_video and video_job_dir is not None else None,
            image_cfg,
            str(image_job_dir) if is_converted_image and image_job_dir is not None else None,
        )
        (video_tasks if is_video else general_tasks).append(task)

    log_func(_tool_detection_summary(catalog, report))
    max_workers = max(4, multiprocessing.cpu_count())
    log_func(t('log_parallel_start', max_workers=max_workers, total_len=total_len))

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
            csv_writer.writerow(_csv_headers(catalog))
            # 先頭にヘッダを書いておくことで、途中失敗時も解析しやすい CSV を維持する。
            log_func(t('log_csv_output', path=csv_path_obj))
        except Exception as exc:
            log_func(t('log_csv_create_failed', exc=exc))
            csv_file = None
            csv_writer = None

    cnt = 0
    orig_total = 0
    out_total = 0
    processed_files = 0
    cancelled_files = 0
    compressible_extensions = {'pdf', 'jpg', 'jpeg', 'png'}
    if video_enabled:
        compressible_extensions |= VIDEO_EXTENSIONS
    if image_cfg.avif_to_jpeg_compat:
        compressible_extensions.add('avif')

    def close_csv() -> None:
        nonlocal csv_file
        handle, csv_file = csv_file, None
        try:
            if handle:
                handle.close()
        except OSError as exc:
            log_func(t('log_csv_write_failed', exc=exc))

    cleanup.callback(close_csv)

    def rel_output(path: str | Path) -> str:
        """CSV に残す出力パスを出力ルートからの相対パスで返す。"""
        try:
            return Path(path).relative_to(output_base).as_posix()
        except ValueError:
            return str(path)

    # ミラー圧縮では、元の ZIP も出力へコピーして入力構成を保つ。
    for in_zip, out_zip, csv_input, csv_output in zip_output_copies:
        if control.is_cancelled:
            break
        try:
            out_zip.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(in_zip, out_zip)
            log_func(f"{t('log_zip_copy')}: {_safe_rel(in_zip, input_base)}")
            if csv_writer:
                timestamp = datetime.now().isoformat()
                size_val = in_zip.stat().st_size
                csv_writer.writerow([
                    timestamp,
                    csv_input,
                    csv_output,
                    'zip',
                    t('csv_action_zip_copy'),
                    size_val,
                    size_val,
                    0,
                    '0.0',
                    t('csv_note_zip_archive', archive_rel=csv_output),
                ])
        except Exception as copy_exc:
            log_func(f"{t('log_zip_copy_failed')}: {_safe_rel(in_zip, input_base)} ({copy_exc})")
        cnt += 1
        progress_func(cnt, total_len)

    def run_video_task(task: tuple[Any, ...]):
        """動画 1 件を処理する。開始・終了イベントはここで送出し、間引かない。"""
        if control.is_cancelled:
            # 未開始のまま停止された動画は、開始イベントを出さず中断結果だけ受け取る。
            return process_single_file(task)
        name = Path(task[0]).name
        emit(ProgressEvent(kind='video_progress', message=name, current=None, video_phase='started'))
        try:
            return process_single_file(task)
        finally:
            emit(ProgressEvent(kind='video_progress', message=name, current=None, video_phase='finished'))

    # future だけでは CSV 用文脈を引けないため、元 task を対応付けて保持する。
    futures: dict[Future, tuple[Any, ...]] = {}

    def handle_future(future: Future) -> None:
        """完了した future 1 件を集計・コピー・CSV・進捗へ反映する。"""
        nonlocal cnt, orig_total, out_total, processed_files, cancelled_files
        task = futures[future]
        if future.cancelled():
            # 停止要求で未開始のまま破棄された。処理エラーではなく中断件数として数える。
            cancelled_files += 1
            if task[27] is not None and csv_writer:
                try:
                    input_path = Path(task[0])
                    try:
                        input_size: int | str = input_path.stat().st_size
                    except OSError as exc:
                        input_size = ''
                        log_func(t('worker_input_stat_failed', name=input_path.name, detail=str(exc)))
                    csv_writer.writerow([
                        datetime.now().isoformat(),
                        task[16],
                        '',
                        task[2],
                        t('csv_action_cancelled'),
                        input_size,
                        '',
                        '',
                        '',
                        task[18],
                    ])
                except (OSError, csv.Error) as exc:
                    log_func(t('log_csv_write_failed', exc=exc))
            return
        try:
            inpath_task = Path(task[0])
            outpath_task = Path(task[1])
            ext_task = task[2]
            csv_input = task[16]
            csv_output = task[17]
            csv_notes = task[18]
            is_video_task = task[20] is not None
            is_image_task = ext_task in {'jpg', 'jpeg', 'png', 'avif'}
            is_converted_image_task = is_image_task and task[27] is not None
            raw_result: WorkerFileResult | tuple[str, int, int, bool]
            try:
                raw_result = future.result()
            except Exception as exc:
                if not is_converted_image_task:
                    raise
                try:
                    size = inpath_task.stat().st_size
                except OSError as stat_exc:
                    size = 0
                    log_func(t('worker_input_stat_failed', name=inpath_task.name, detail=str(stat_exc)))
                raw_result = WorkerFileResult(
                    action_key='csv_action_failed',
                    message=t('image_conversion_failed', name=inpath_task.name, detail=f'{type(exc).__name__}: {exc}'),
                    orig_size=size,
                    out_size=0,
                    processed=False,
                    cancelled=control.is_cancelled,
                )
            final_outpath: str | None = None
            cancelled_flag = False
            result_notes = ''
            if isinstance(raw_result, WorkerFileResult):
                result = raw_result
                action_key = result.action_key
                msg = result.message
                orig_size = result.orig_size
                out_size = result.out_size
                processed_flag = result.processed
                final_outpath = result.final_outpath
                cancelled_flag = result.cancelled
                result_notes = result.notes
            else:
                msg, orig_size, out_size, processed_flag = raw_result
                action_key = _csv_action_label(catalog, ext_task, processed=processed_flag)

            if processed_flag and out_size is None:
                processed_flag = False
                msg = t('image_conversion_failed', name=inpath_task.name, detail='output size could not be determined')
            elif is_converted_image_task and processed_flag and not final_outpath:
                processed_flag = False
                msg = t('image_conversion_failed', name=inpath_task.name, detail='conversion reported success without an output')

            copied_to: Path | None = None
            is_non_target = ext_task not in compressible_extensions
            if cancelled_flag:
                pass
            elif processed_flag and out_size is not None:
                orig_total += orig_size
                out_total += out_size
                processed_files += 1
            elif copy_non_target_files and final_outpath is None:
                if control.is_cancelled:
                    # 停止要求後はフォールバックコピーを始めない。
                    cancelled_flag = True
                else:
                    # 非圧縮対象や圧縮失敗ファイルもミラー圧縮では出力に揃えておく。
                    # 拡張子が変わる画像・動画は、予約済みの元拡張子へ一時領域経由で配置する。
                    copy_dest = Path(task[22]) if (is_video_task or is_converted_image_task) and task[22] else outpath_task
                    try:
                        if is_video_task:
                            placed = place_original_copy(inpath_task, copy_dest, task[25], control)
                        elif is_converted_image_task:
                            image_temp_dir = task[27]
                            if image_temp_dir is None:
                                raise ValueError('converted image task is missing its work directory')
                            placed = place_image_original_copy(inpath_task, copy_dest, image_temp_dir, control, log_language=log_language)
                        else:
                            copy_dest.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(inpath_task, copy_dest)
                            placed = True
                        if placed:
                            copied_to = copy_dest
                            if is_non_target:
                                log_func(f"{t('log_non_target_copy')}: {csv_input}")
                            else:
                                log_func(f"{t('log_fallback_copy')}: {csv_input}")
                            if is_image_task:
                                try:
                                    out_size = copied_to.stat().st_size
                                except OSError as exc:
                                    out_size = None
                                    log_func(t('image_conversion_failed', name=inpath_task.name, detail=str(exc)))
                        else:
                            cancelled_flag = True
                    except Exception as copy_exc:
                        log_func(f"{t('log_copy_failed')}: {csv_input} ({copy_exc})")
                        if control.is_cancelled:
                            cancelled_flag = True

            if cancelled_flag:
                cancelled_files += 1
            else:
                cnt += 1
            log_func(msg)

            try:
                if csv_writer:
                    action = t(action_key)
                    if cancelled_flag:
                        action = t('csv_action_cancelled')
                    elif not processed_flag:
                        if copied_to is not None:
                            action = t('csv_action_non_target_copy') if is_non_target else t('csv_action_fallback_copy')
                        else:
                            action = t('csv_action_failed')
                    # 実際に配置したファイルだけを出力パスとして記録する。
                    if cancelled_flag:
                        csv_output = ''
                    elif final_outpath:
                        csv_output = rel_output(final_outpath)
                    elif copied_to is not None:
                        csv_output = rel_output(copied_to)
                    elif (is_video_task or is_image_task) and not processed_flag:
                        csv_output = ''
                    if out_size is None or (is_image_task and not csv_output):
                        csv_out_size: int | str = ''
                        csv_saved: int | str = ''
                        csv_saved_pct = ''
                    else:
                        csv_out_size = out_size
                        saved_size = orig_size - out_size
                        csv_saved = saved_size
                        saved_pct = (saved_size / orig_size * 100) if orig_size > 0 else 0.0
                        csv_saved_pct = f"{saved_pct:.1f}"
                    timestamp = datetime.now().isoformat()
                    csv_writer.writerow([
                        timestamp,
                        csv_input,
                        csv_output,
                        ext_task,
                        action,
                        orig_size,
                        csv_out_size,
                        csv_saved,
                        csv_saved_pct,
                        ';'.join(part for part in (csv_notes, result_notes) if part),
                    ])
            except (OSError, csv.Error) as exc:
                log_func(t('log_csv_write_failed', exc=exc))

            if not cancelled_flag:
                progress_func(cnt, total_len)
        except Exception as exc:
            # 1 件の失敗で全体を止めるとバッチ処理として使いづらいため、ログへ落として
            # 残りファイルの処理を継続する。
            log_func(f"{t('log_processing_error')}: {exc}")
            cnt += 1
            progress_func(cnt, total_len)

    if (general_tasks or video_tasks) and not control.is_cancelled:
        # 動画は単一ワーカーで直列に処理する。汎用 executor と分けることで、動画待ちが
        # 画像・PDF のワーカーを塞がないようにする（同時エンコード数の制限が目的）。
        with ThreadPoolExecutor(max_workers=max_workers) as general_ex, \
                ThreadPoolExecutor(max_workers=1, thread_name_prefix='pjp-video') as video_ex:
            for task in general_tasks:
                futures[general_ex.submit(process_single_file, task)] = task
            for task in video_tasks:
                futures[video_ex.submit(run_video_task, task)] = task

            pending = set(futures)
            stop_handled = False
            while pending:
                done, pending = wait(pending, timeout=0.2, return_when=FIRST_COMPLETED)
                if control.is_cancelled and not stop_handled:
                    stop_handled = True
                    # 未開始 future を破棄し、実行中の ffmpeg / ffprobe を止める。実行中の
                    # 画像・PDF は既存処理の終了を待つ（with 終了時の待機）。
                    general_ex.shutdown(wait=False, cancel_futures=True)
                    video_ex.shutdown(wait=False, cancel_futures=True)
                    terminate_active_video_processes(control, log_func=log_func, log_language=log_language)
                # cancel_futures で破棄された future は wait() へ通知されないため、自前で回収する。
                dropped = {future for future in pending if future.cancelled()}
                pending -= dropped
                for future in done | dropped:
                    handle_future(future)
    elif general_tasks or video_tasks:
        cancelled_files += len(general_tasks) + len(video_tasks)

    if control.is_cancelled:
        close_csv()
        return finish_cancelled(orig_total, out_total, processed_files, cancelled_files)

    if extract_zip and zip_output_enabled:
        for plan in zip_output_plans:
            if control.is_cancelled:
                break
            if not plan.folder_output_root.exists():
                continue
            try:
                archived_file_count = zip_directory(plan.folder_output_root, plan.archive_output_path)
                shutil.rmtree(plan.folder_output_root, ignore_errors=True)
                log_func(t(
                    'log_zip_regenerated',
                    input_path=_safe_rel(plan.folder_output_root, output_base),
                    output_path=_safe_rel(plan.archive_output_path, output_base),
                    archived_file_count=archived_file_count,
                ))
            except Exception as exc:
                log_func(t('log_zip_regeneration_failed', path=_safe_rel(plan.folder_output_root, output_base), exc=exc))

    if temp_extract_root:
        shutil.rmtree(temp_extract_root, ignore_errors=True)

    close_csv()

    if control.is_cancelled:
        return finish_cancelled(orig_total, out_total, processed_files, cancelled_files)

    saved = orig_total - out_total
    saved_pct = (saved / orig_total * 100) if orig_total > 0 else 0.0

    def notify_complete() -> None:
        log_func(t('log_complete'))
        log_func(t(
            'log_stats_summary',
            processed_files=processed_files,
            orig_total=human_readable(orig_total),
            out_total=human_readable(out_total),
            saved=human_readable(saved),
            saved_pct=saved_pct,
        ))
        stats_func(orig_total, out_total, saved, saved_pct)

    return notify_complete


def run_compression_request(
    request: CompressionRequest,
    event_callback: Callable[[ProgressEvent], None],
    job_control: JobControl | None = None,
) -> None:
    """`CompressionRequest` ベースの新 API をイベント駆動で実行する。

    UI 側は関数コールバック 3 本よりも単一のイベントストリームの方が扱いやすい。
    この薄い変換層を置くことで、内部では旧来の `run_compression_job` シグネチャを
    維持しつつ、外側には request/event 契約を公開できる。
    """

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
            pdf_png_quality=request.pdf_png_quality,
            pdf_lossless_options=request.pdf_lossless_options,
            gs_preset=request.gs_preset,
            gs_custom_dpi=request.gs_custom_dpi,
            resize_enabled=request.resize_config,
            resize_width=request.resize_width,
            resize_height=request.resize_height,
            csv_enable=request.csv_enable,
            csv_path=request.csv_path,
            extract_zip=request.extract_zip,
            zip_output_enabled=request.zip_output_enabled,
            debug_mode=request.debug_mode,
            copy_non_target_files=request.copy_non_target_files,
            log_language=request.log_language,
            video_config=request.video_config,
            event_func=event_callback,
            job_control=job_control,
        )
    except Exception as exc:
        event_callback(ProgressEvent(kind='error', message=f"{locale_translate(request.log_language, 'log_processing_error')}: {exc}"))
