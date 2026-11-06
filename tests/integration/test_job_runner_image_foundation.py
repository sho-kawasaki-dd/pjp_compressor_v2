from __future__ import annotations

import csv
import threading
import zipfile
from pathlib import Path
from typing import Any, Callable

import pytest

from backend.contracts import CapabilityReport, ImageCompressionConfig, JobControl, ProgressEvent
from backend.core import image_utils, job_files, worker_ops
from backend.orchestrator import job_runner
from backend.orchestrator.job_lock import OutputLockError, acquire_output_lock
from backend.settings import IMAGE_WORK_SUBDIR, VIDEO_WORK_OWNER_MARKER
from shared.locale_catalog import translate as tlog


pytestmark = pytest.mark.integration


class ImageJobHarness:
    def __init__(self, sample_paths) -> None:
        self.paths = sample_paths
        self.logs: list[str] = []
        self.progress: list[tuple[int, int]] = []
        self.stats: list[tuple[int, int, int, float]] = []
        self.events: list[ProgressEvent] = []

    def run(self, **kwargs: Any) -> None:
        params: dict[str, Any] = {
            'input_dir': str(self.paths.input_dir),
            'output_dir': str(self.paths.output_dir),
            'jpg_quality': 70,
            'png_quality': 70,
            'use_pngquant': False,
            'log_func': self.logs.append,
            'progress_func': lambda current, total: self.progress.append((current, total)),
            'stats_func': lambda *values: self.stats.append(values),
            'event_func': self.events.append,
            'csv_enable': True,
            'csv_path': str(self.paths.csv_path),
            'log_language': 'ja',
        }
        params.update(kwargs)
        job_runner.run_compression_job(**params)

    def row(self) -> dict[str, str]:
        with self.paths.csv_path.open(newline='', encoding='utf-8') as handle:
            rows = list(csv.DictReader(handle))
        assert len(rows) == 1
        return rows[0]

    def assert_workspace_clean(self) -> None:
        root = self.paths.output_dir / '.pjp_work' / IMAGE_WORK_SUBDIR
        assert not root.exists() or not any(root.iterdir())
        with acquire_output_lock(self.paths.output_dir):
            pass


@pytest.fixture
def harness(sample_paths, monkeypatch: pytest.MonkeyPatch) -> ImageJobHarness:
    monkeypatch.setattr(job_runner, 'detect_capabilities', lambda: CapabilityReport(True, True, None, None))
    return ImageJobHarness(sample_paths)


def image_config(input_ext: str) -> ImageCompressionConfig:
    if input_ext == 'avif':
        return ImageCompressionConfig(avif_to_jpeg_compat=True)
    return ImageCompressionConfig(output_format='avif')


def install_simulated_encoder(
    monkeypatch: pytest.MonkeyPatch,
    config: ImageCompressionConfig,
    encode: Callable[[Path, JobControl], image_utils.ImageEncodeOutcome],
) -> list[ImageCompressionConfig]:
    """後続フェーズの codec だけを模擬し、配置・worker・ジョブ処理は実際に実行する。"""
    seen: list[ImageCompressionConfig] = []
    monkeypatch.setattr(job_runner, 'ImageCompressionConfig', lambda: config)

    def fake_image_task(
        inpath: Path,
        outpath: Path,
        original_outpath: Path,
        ext: str,
        *,
        image_config: ImageCompressionConfig,
        job_control: JobControl | None,
        temp_dir: Path | None,
        log_language: str,
        **_kwargs: Any,
    ) -> image_utils.ImageCompressResult:
        assert job_control is not None and temp_dir is not None
        seen.append(image_config)
        return image_utils.save_converted_image(
            inpath,
            outpath,
            original_outpath,
            encode=lambda path: encode(path, job_control),
            keep_if_not_smaller=ext != 'avif',
            job_control=job_control,
            temp_dir=temp_dir,
            log_language=log_language,
        )

    monkeypatch.setattr(worker_ops, '_process_image_task', fake_image_task)
    return seen


def candidate(name: str, csv_input: str | None = None) -> job_runner._TaskCandidate:
    path = Path('out') / name
    return job_runner._TaskCandidate(Path('in') / name, path, csv_input or name, name, '')


def test_converted_output_planning_reserves_all_originals_and_is_deterministic() -> None:
    names = ['photo.jpg', 'photo.jpeg', 'photo.avif', 'photo_jpg.avif', 'photo.mov', 'photo.mp4']
    config = ImageCompressionConfig(output_format='avif')
    mappings: list[dict[str, tuple[str, str]]] = []

    for ordering in (names, list(reversed(names)), names[2:] + names[:2]):
        candidates = [candidate(name) for name in ordering]

        def target(item: job_runner._TaskCandidate) -> str | None:
            if item.inpath.suffix.lower() in {'.mov', '.mp4'}:
                return '.mp4'
            return image_utils.converted_image_extension(item.inpath.suffix, config)

        planned = job_runner._plan_converted_outputs(candidates, target)
        mappings.append({
            candidates[index].inpath.name: (result.outpath.name, result.original_outpath.name)
            for index, result in planned.items()
        })

    assert mappings[0] == mappings[1] == mappings[2]
    assert mappings[0]['photo.jpg'] == ('photo_jpg_2.avif', 'photo.jpg')
    assert mappings[0]['photo.jpeg'] == ('photo_jpeg.avif', 'photo.jpeg')
    assert mappings[0]['photo.avif'] == ('photo.avif', 'photo.avif')
    assert mappings[0]['photo.mov'] == ('photo_mov.mp4', 'photo.mov')
    assert mappings[0]['photo.mp4'] == ('photo.mp4', 'photo.mp4')


def test_compat_output_planning_avoids_existing_original_and_case_collisions() -> None:
    candidates = [candidate('PHOTO.AVIF'), candidate('photo.jpg'), candidate('photo_avif.jpg')]
    config = ImageCompressionConfig(avif_to_jpeg_compat=True)
    planned = job_runner._plan_converted_outputs(
        candidates,
        lambda item: image_utils.converted_image_extension(item.inpath.suffix, config),
    )

    assert planned[0].outpath.name == 'PHOTO_avif_2.jpg'
    assert planned[0].original_outpath.name == 'PHOTO.AVIF'
    assert len({str(result.outpath).casefold() for result in planned.values()}) == len(candidates)


def test_planning_disambiguates_duplicate_original_paths_from_zip_and_regular_input() -> None:
    candidates = [candidate('photo.jpg', 'pack.zip::photo.jpg'), candidate('photo.jpg', 'pack/photo.jpg')]
    config = ImageCompressionConfig(output_format='avif')

    def plan(items):
        outputs = job_runner._plan_converted_outputs(
            items, lambda item: image_utils.converted_image_extension(item.inpath.suffix, config),
        )
        return {items[index].csv_input: output for index, output in outputs.items()}

    forward = plan(candidates)
    backward = plan(list(reversed(candidates)))
    assert forward == backward
    assert len({str(output.original_outpath).casefold() for output in forward.values()}) == 2
    assert len({str(output.outpath).casefold() for output in forward.values()}) == 2
    assert all(output.original_outpath.suffix == '.jpg' and output.outpath.suffix == '.avif' for output in forward.values())


@pytest.mark.parametrize(('input_ext', 'target_ext'), [('jpg', 'avif'), ('avif', 'jpg')])
@pytest.mark.parametrize('failure', ['encode', 'publish', 'retention_copy'])
@pytest.mark.parametrize('mirror', [False, True])
def test_image_failures_preserve_previous_outputs_and_use_original_extension_for_fallback(
    harness: ImageJobHarness,
    monkeypatch: pytest.MonkeyPatch,
    input_ext: str,
    target_ext: str,
    failure: str,
    mirror: bool,
) -> None:
    source = harness.paths.input_dir / f'photo.{input_ext}'
    source.write_bytes(b's' * 100)
    original_dest = harness.paths.output_dir / source.name
    target_dest = harness.paths.output_dir / f'photo.{target_ext}'
    original_dest.write_bytes(b'previous original')
    target_dest.write_bytes(b'previous conversion')

    def encode(path: Path, _control: JobControl) -> image_utils.ImageEncodeOutcome:
        if failure == 'retention_copy':
            return image_utils.ImageEncodeOutcome('retain', retention=True, notes=('retention_reason',))
        path.write_bytes(b'partial' if failure == 'encode' else b'c' * 40)
        if failure == 'encode':
            raise OSError('simulated encoding failure')
        return image_utils.ImageEncodeOutcome('encoded')

    config = image_config(input_ext)
    seen = install_simulated_encoder(monkeypatch, config, encode)
    if failure == 'publish':
        original_publish = job_files.publish

        def fail_converted_publish(staged: Path, dest: Path, control: JobControl) -> None:
            if dest == target_dest:
                raise PermissionError('simulated placement failure')
            original_publish(staged, dest, control)

        monkeypatch.setattr(job_files, 'publish', fail_converted_publish)
    elif failure == 'retention_copy':
        original_copy = job_files.copy_with_cancel
        copy_calls = 0

        def fail_first_copy(src: Path, dest: Path, control: JobControl, **kwargs: Any) -> None:
            nonlocal copy_calls
            copy_calls += 1
            if copy_calls == 1:
                dest.write_bytes(b'partial')
                raise OSError('simulated retention copy failure')
            original_copy(src, dest, control, **kwargs)

        monkeypatch.setattr(job_files, 'copy_with_cancel', fail_first_copy)

    harness.run(copy_non_target_files=mirror)

    assert seen == [config]
    assert target_dest.read_bytes() == b'previous conversion'
    assert original_dest.read_bytes() == (source.read_bytes() if mirror else b'previous original')
    row = harness.row()
    assert row[tlog('ja', 'csv_header_output_path')] == (source.name if mirror else '')
    assert row[tlog('ja', 'csv_header_out_size')] == (str(source.stat().st_size) if mirror else '')
    assert row[tlog('ja', 'csv_header_action')] == tlog('ja', 'csv_action_fallback_copy' if mirror else 'csv_action_failed')
    assert harness.stats == [(0, 0, 0, 0.0)]
    assert harness.progress[-1] == (1, 1)
    assert any('simulated' in message for message in harness.logs)
    if failure == 'retention_copy':
        assert row[tlog('ja', 'csv_header_notes')] == 'retention_reason'
    harness.assert_workspace_clean()


@pytest.mark.parametrize(('input_ext', 'target_ext'), [('jpg', 'avif'), ('avif', 'jpg')])
def test_fallback_copy_failure_has_no_output_path_or_size(
    harness: ImageJobHarness,
    monkeypatch: pytest.MonkeyPatch,
    input_ext: str,
    target_ext: str,
) -> None:
    source = harness.paths.input_dir / f'photo.{input_ext}'
    source.write_bytes(b's' * 100)
    original_dest = harness.paths.output_dir / source.name
    target_dest = harness.paths.output_dir / f'photo.{target_ext}'
    original_dest.write_bytes(b'previous original')
    target_dest.write_bytes(b'previous conversion')

    def fail_encoding(path: Path, _control: JobControl) -> image_utils.ImageEncodeOutcome:
        path.write_bytes(b'partial')
        raise OSError('encoding failed')

    def fail_copy(_src: Path, dest: Path, _control: JobControl, **_kwargs: Any) -> None:
        dest.write_bytes(b'partial copy')
        raise OSError('fallback copy failed')

    install_simulated_encoder(monkeypatch, image_config(input_ext), fail_encoding)
    monkeypatch.setattr(job_files, 'copy_with_cancel', fail_copy)
    harness.run(copy_non_target_files=True)

    assert original_dest.read_bytes() == b'previous original'
    assert target_dest.read_bytes() == b'previous conversion'
    row = harness.row()
    assert row[tlog('ja', 'csv_header_output_path')] == ''
    assert row[tlog('ja', 'csv_header_out_size')] == ''
    assert row[tlog('ja', 'csv_header_action')] == tlog('ja', 'csv_action_failed')
    assert any('fallback copy failed' in message for message in harness.logs)
    assert harness.stats == [(0, 0, 0, 0.0)]
    harness.assert_workspace_clean()


def test_output_stat_failure_keeps_actual_path_and_does_not_start_fallback(
    harness: ImageJobHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = harness.paths.input_dir / 'photo.jpg'
    source.write_bytes(b's' * 100)
    target = harness.paths.output_dir / 'photo.avif'

    def encode(path: Path, _control: JobControl) -> image_utils.ImageEncodeOutcome:
        path.write_bytes(b'c' * 20)
        return image_utils.ImageEncodeOutcome('encoded')

    install_simulated_encoder(monkeypatch, image_config('jpg'), encode)
    original_stat = Path.stat

    def fail_output_stat(path: Path, *args: Any, **kwargs: Any):
        if path == target:
            raise PermissionError('output stat failed')
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'stat', fail_output_stat)
    monkeypatch.setattr(job_runner, 'place_image_original_copy', lambda *_args, **_kwargs: pytest.fail('output was already placed'))
    harness.run(copy_non_target_files=True)

    row = harness.row()
    assert row[tlog('ja', 'csv_header_action')] == tlog('ja', 'csv_action_failed')
    assert row[tlog('ja', 'csv_header_output_path')] == 'photo.avif'
    assert row[tlog('ja', 'csv_header_out_size')] == ''
    assert target.read_bytes() == b'c' * 20
    assert any('output stat failed' in message for message in harness.logs)
    assert harness.stats == [(0, 0, 0, 0.0)]
    harness.assert_workspace_clean()


@pytest.mark.parametrize('mirror', [False, True])
def test_failed_legacy_image_does_not_count_an_old_output(
    harness: ImageJobHarness,
    mirror: bool,
) -> None:
    source = harness.paths.input_dir / 'broken.jpg'
    source.write_bytes(b'not a jpeg')
    old_output = harness.paths.output_dir / source.name
    old_output.write_bytes(b'previous image')

    harness.run(copy_non_target_files=mirror)

    row = harness.row()
    assert row[tlog('ja', 'csv_header_output_path')] == (source.name if mirror else '')
    assert row[tlog('ja', 'csv_header_out_size')] == (str(source.stat().st_size) if mirror else '')
    assert row[tlog('ja', 'csv_header_action')] == tlog('ja', 'csv_action_fallback_copy' if mirror else 'csv_action_failed')
    assert old_output.read_bytes() == (source.read_bytes() if mirror else b'previous image')
    assert harness.stats == [(0, 0, 0, 0.0)]


def test_csv_close_failure_is_logged(
    harness: ImageJobHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (harness.paths.input_dir / 'broken.jpg').write_bytes(b'not a jpeg')
    real_open = open

    class FailingClose:
        def __init__(self, handle) -> None:
            self.handle = handle

        def write(self, text: str) -> int:
            return self.handle.write(text)

        def close(self) -> None:
            self.handle.close()
            raise OSError('CSV flush failed')

    def fake_open(path, *args, **kwargs):
        handle = real_open(path, *args, **kwargs)
        if Path(path) == harness.paths.csv_path:
            return FailingClose(handle)
        return handle

    monkeypatch.setattr(job_runner, 'open', fake_open, raising=False)
    harness.run()

    assert any('CSV flush failed' in message for message in harness.logs)
    assert harness.stats == [(0, 0, 0, 0.0)]


@pytest.mark.parametrize(
    ('input_ext', 'target_ext', 'size', 'retention', 'action', 'notes'),
    [
        ('jpg', 'avif', 30, False, 'csv_action_avif', 'encoder_note'),
        ('jpg', 'avif', 100, False, 'csv_action_image_kept_original', 'encoder_note'),
        ('avif', 'jpg', 200, False, 'csv_action_compat_jpeg', 'compat_conversion;size_increased'),
        ('avif', 'jpg', 0, True, 'csv_action_image_kept_retention', 'animated_avif'),
    ],
)
def test_image_result_propagates_actual_path_reason_notes_and_totals(
    harness: ImageJobHarness,
    monkeypatch: pytest.MonkeyPatch,
    input_ext: str,
    target_ext: str,
    size: int,
    retention: bool,
    action: str,
    notes: str,
) -> None:
    source = harness.paths.input_dir / f'photo.{input_ext}'
    source.write_bytes(b's' * 100)

    def encode(path: Path, _control: JobControl) -> image_utils.ImageEncodeOutcome:
        if retention:
            return image_utils.ImageEncodeOutcome('retain', retention=True, notes=('animated_avif',))
        path.write_bytes(b'c' * size)
        initial_note = 'compat_conversion' if input_ext == 'avif' else 'encoder_note'
        return image_utils.ImageEncodeOutcome('encoded', notes=(initial_note,))

    config = image_config(input_ext)
    seen = install_simulated_encoder(monkeypatch, config, encode)
    harness.run()

    kept = retention or (input_ext == 'jpg' and size >= 100)
    expected_name = source.name if kept else f'photo.{target_ext}'
    expected_size = 100 if kept else size
    row = harness.row()
    assert seen == [config]
    assert row[tlog('ja', 'csv_header_output_path')] == expected_name
    assert row[tlog('ja', 'csv_header_out_size')] == str(expected_size)
    assert row[tlog('ja', 'csv_header_action')] == tlog('ja', action)
    assert row[tlog('ja', 'csv_header_notes')] == notes
    assert (harness.paths.output_dir / expected_name).stat().st_size == expected_size
    assert harness.stats == [(100, expected_size, 100 - expected_size, float(100 - expected_size))]
    assert any('圧縮対象 1 件' in message for message in harness.logs)
    harness.assert_workspace_clean()


@pytest.mark.parametrize(('input_ext', 'target_ext'), [('jpg', 'avif'), ('avif', 'jpg')])
def test_stop_prevents_image_placement_and_fallback(
    harness: ImageJobHarness,
    monkeypatch: pytest.MonkeyPatch,
    input_ext: str,
    target_ext: str,
) -> None:
    source = harness.paths.input_dir / f'photo.{input_ext}'
    source.write_bytes(b's' * 100)
    original_dest = harness.paths.output_dir / source.name
    target_dest = harness.paths.output_dir / f'photo.{target_ext}'
    original_dest.write_bytes(b'previous original')
    target_dest.write_bytes(b'previous conversion')
    control = JobControl()

    def encode(path: Path, job_control: JobControl) -> image_utils.ImageEncodeOutcome:
        path.write_bytes(b'new')
        job_control.request_cancel()
        return image_utils.ImageEncodeOutcome('encoded')

    install_simulated_encoder(monkeypatch, image_config(input_ext), encode)
    monkeypatch.setattr(job_runner, 'place_image_original_copy', lambda *_args, **_kwargs: pytest.fail('fallback after stop'))
    harness.run(copy_non_target_files=True, job_control=control)

    assert original_dest.read_bytes() == b'previous original'
    assert target_dest.read_bytes() == b'previous conversion'
    row = harness.row()
    assert row[tlog('ja', 'csv_header_action')] == tlog('ja', 'csv_action_cancelled')
    assert row[tlog('ja', 'csv_header_output_path')] == ''
    assert row[tlog('ja', 'csv_header_out_size')] == ''
    assert harness.stats == []
    assert any(event.kind == 'cancelled' for event in harness.events)
    harness.assert_workspace_clean()


@pytest.mark.parametrize(('input_ext', 'target_ext'), [('jpg', 'avif'), ('avif', 'jpg')])
def test_stop_during_retention_copy_preserves_existing_files(
    harness: ImageJobHarness,
    monkeypatch: pytest.MonkeyPatch,
    input_ext: str,
    target_ext: str,
) -> None:
    source = harness.paths.input_dir / f'photo.{input_ext}'
    source.write_bytes(b's' * 100)
    original_dest = harness.paths.output_dir / source.name
    target_dest = harness.paths.output_dir / f'photo.{target_ext}'
    original_dest.write_bytes(b'previous original')
    target_dest.write_bytes(b'previous conversion')

    def retain(_path: Path, _control: JobControl) -> image_utils.ImageEncodeOutcome:
        return image_utils.ImageEncodeOutcome('retain', retention=True, notes=('retention_reason',))

    original_copy = job_files.copy_with_cancel

    def stop_during_copy(src: Path, dest: Path, control: JobControl, **kwargs: Any) -> None:
        dest.write_bytes(b'partial copy')
        control.request_cancel()
        original_copy(src, dest, control, **kwargs)

    install_simulated_encoder(monkeypatch, image_config(input_ext), retain)
    monkeypatch.setattr(job_files, 'copy_with_cancel', stop_during_copy)
    monkeypatch.setattr(job_runner, 'place_image_original_copy', lambda *_args, **_kwargs: pytest.fail('fallback after stop'))
    harness.run(copy_non_target_files=True)

    row = harness.row()
    assert row[tlog('ja', 'csv_header_action')] == tlog('ja', 'csv_action_cancelled')
    assert row[tlog('ja', 'csv_header_output_path')] == ''
    assert row[tlog('ja', 'csv_header_notes')] == 'retention_reason'
    assert original_dest.read_bytes() == b'previous original'
    assert target_dest.read_bytes() == b'previous conversion'
    assert harness.stats == []
    harness.assert_workspace_clean()


@pytest.mark.parametrize(('input_ext', 'target_ext'), [('jpg', 'avif'), ('avif', 'jpg')])
def test_stop_wins_race_before_image_publication(
    harness: ImageJobHarness,
    monkeypatch: pytest.MonkeyPatch,
    input_ext: str,
    target_ext: str,
) -> None:
    source = harness.paths.input_dir / f'photo.{input_ext}'
    source.write_bytes(b's' * 100)
    original_dest = harness.paths.output_dir / source.name
    target_dest = harness.paths.output_dir / f'photo.{target_ext}'
    original_dest.write_bytes(b'previous original')
    target_dest.write_bytes(b'previous conversion')
    control = JobControl()
    before_publish = threading.Event()
    release_publish = threading.Event()
    errors: list[Exception] = []
    original_publish = job_files.publish

    def encode(path: Path, _control: JobControl) -> image_utils.ImageEncodeOutcome:
        path.write_bytes(b'new')
        return image_utils.ImageEncodeOutcome('encoded')

    def delayed_publish(staged: Path, dest: Path, job_control: JobControl) -> None:
        before_publish.set()
        assert release_publish.wait(timeout=10)
        original_publish(staged, dest, job_control)

    def run() -> None:
        try:
            harness.run(copy_non_target_files=True, job_control=control)
        except Exception as exc:
            errors.append(exc)

    install_simulated_encoder(monkeypatch, image_config(input_ext), encode)
    monkeypatch.setattr(job_files, 'publish', delayed_publish)
    monkeypatch.setattr(job_runner, 'place_image_original_copy', lambda *_args, **_kwargs: pytest.fail('fallback after stop'))
    thread = threading.Thread(target=run)
    thread.start()
    try:
        assert before_publish.wait(timeout=10)
        control.request_cancel()
    finally:
        release_publish.set()
        thread.join(timeout=10)

    assert not thread.is_alive() and not errors
    assert original_dest.read_bytes() == b'previous original'
    assert target_dest.read_bytes() == b'previous conversion'
    row = harness.row()
    assert row[tlog('ja', 'csv_header_action')] == tlog('ja', 'csv_action_cancelled')
    assert row[tlog('ja', 'csv_header_output_path')] == ''
    assert harness.stats == []
    harness.assert_workspace_clean()


def test_queued_cancelled_image_tasks_have_empty_csv_outputs(
    harness: ImageJobHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for index in range(12):
        (harness.paths.input_dir / f'{index}.jpg').write_bytes(b's' * 100)
    control = JobControl()
    all_started = threading.Event()
    all_submitted = threading.Event()
    shutdown_started = threading.Event()
    release = threading.Event()
    guard = threading.Lock()
    active = 0
    errors: list[Exception] = []
    base_executor = job_runner.ThreadPoolExecutor

    class TrackingExecutor(base_executor):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self.general = kwargs.get('thread_name_prefix') != 'pjp-video'
            self.submitted = 0

        def submit(self, *args: Any, **kwargs: Any):
            future = super().submit(*args, **kwargs)
            if self.general:
                self.submitted += 1
                if self.submitted == 12:
                    all_submitted.set()
            return future

        def shutdown(self, wait: bool = True, *, cancel_futures: bool = False) -> None:
            super().shutdown(wait=wait, cancel_futures=cancel_futures)
            if self.general and cancel_futures:
                shutdown_started.set()

    def encode(path: Path, _control: JobControl) -> image_utils.ImageEncodeOutcome:
        nonlocal active
        path.write_bytes(b'partial')
        with guard:
            active += 1
            if active == 4:
                all_started.set()
        assert release.wait(timeout=10)
        return image_utils.ImageEncodeOutcome('encoded')

    def run() -> None:
        try:
            harness.run(copy_non_target_files=True, job_control=control)
        except Exception as exc:
            errors.append(exc)

    install_simulated_encoder(monkeypatch, image_config('jpg'), encode)
    monkeypatch.setattr(job_runner.multiprocessing, 'cpu_count', lambda: 1)
    monkeypatch.setattr(job_runner, 'ThreadPoolExecutor', TrackingExecutor)
    monkeypatch.setattr(job_runner, 'place_image_original_copy', lambda *_args, **_kwargs: pytest.fail('fallback after stop'))
    thread = threading.Thread(target=run)
    thread.start()
    try:
        assert all_started.wait(timeout=10) and all_submitted.wait(timeout=10)
        control.request_cancel()
        assert shutdown_started.wait(timeout=10)
    finally:
        release.set()
        thread.join(timeout=10)

    assert not thread.is_alive() and not errors
    with harness.paths.csv_path.open(newline='', encoding='utf-8') as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 12
    assert {row[tlog('ja', 'csv_header_action')] for row in rows} == {tlog('ja', 'csv_action_cancelled')}
    assert all(row[tlog('ja', 'csv_header_output_path')] == '' for row in rows)
    assert all(row[tlog('ja', 'csv_header_out_size')] == '' for row in rows)
    assert not list(harness.paths.output_dir.glob('*.avif'))
    assert harness.stats == []
    harness.assert_workspace_clean()


@pytest.mark.parametrize(('input_ext', 'target_ext'), [('jpg', 'avif'), ('avif', 'jpg')])
def test_unexpected_image_worker_exception_still_uses_safe_mirror_fallback(
    harness: ImageJobHarness,
    monkeypatch: pytest.MonkeyPatch,
    input_ext: str,
    target_ext: str,
) -> None:
    source = harness.paths.input_dir / f'photo.{input_ext}'
    source.write_bytes(b'original')
    config = image_config(input_ext)
    monkeypatch.setattr(job_runner, 'ImageCompressionConfig', lambda: config)

    def fail_worker(*_args: Any, **_kwargs: Any) -> image_utils.ImageCompressResult:
        raise RuntimeError('unexpected image worker error')

    monkeypatch.setattr(worker_ops, '_process_image_task', fail_worker)
    harness.run(copy_non_target_files=True)

    row = harness.row()
    assert row[tlog('ja', 'csv_header_output_path')] == source.name
    assert row[tlog('ja', 'csv_header_action')] == tlog('ja', 'csv_action_fallback_copy')
    assert (harness.paths.output_dir / source.name).read_bytes() == source.read_bytes()
    assert not (harness.paths.output_dir / f'photo.{target_ext}').exists()
    assert any('unexpected image worker error' in message for message in harness.logs)
    assert harness.stats == [(0, 0, 0, 0.0)]
    harness.assert_workspace_clean()


def test_failed_image_can_be_retried_without_reusing_old_output(
    harness: ImageJobHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = harness.paths.input_dir / 'photo.jpg'
    source.write_bytes(b's' * 100)
    old_target = harness.paths.output_dir / 'photo.avif'
    old_target.write_bytes(b'previous result')
    failing = True

    def encode(path: Path, _control: JobControl) -> image_utils.ImageEncodeOutcome:
        path.write_bytes(b'new output' * 3)
        if failing:
            raise OSError('first run failed')
        return image_utils.ImageEncodeOutcome('encoded')

    install_simulated_encoder(monkeypatch, image_config('jpg'), encode)
    harness.run()
    assert old_target.read_bytes() == b'previous result'
    assert harness.row()[tlog('ja', 'csv_header_output_path')] == ''
    failing = False
    harness.run()

    assert old_target.read_bytes() == b'new output' * 3
    assert harness.row()[tlog('ja', 'csv_header_output_path')] == 'photo.avif'
    assert harness.stats == [(0, 0, 0, 0.0), (100, 30, 70, 70.0)]
    harness.assert_workspace_clean()


def test_cleanup_failure_is_logged_and_owned_leftovers_are_recovered_on_restart(
    harness: ImageJobHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = harness.paths.input_dir / 'photo.jpg'
    source.write_bytes(b's' * 100)

    def encode(path: Path, _control: JobControl) -> image_utils.ImageEncodeOutcome:
        path.write_bytes(b'c' * 20)
        return image_utils.ImageEncodeOutcome('encoded')

    install_simulated_encoder(monkeypatch, image_config('jpg'), encode)
    original_remove = job_runner.remove_owned_job_dir
    left_behind: list[Path] = []

    def fail_cleanup(_output, _subdir, work: Path, _token) -> None:
        left_behind.append(work)
        (work / '.pjp_tmp_abandoned').write_bytes(b'partial')
        raise OSError('cleanup failed')

    monkeypatch.setattr(job_runner, 'remove_owned_job_dir', fail_cleanup)
    harness.run()
    assert len(left_behind) == 1 and (left_behind[0] / '.pjp_tmp_abandoned').exists()
    assert any('cleanup failed' in message for message in harness.logs)

    monkeypatch.setattr(job_runner, 'remove_owned_job_dir', original_remove)
    harness.run()
    assert not left_behind[0].exists()
    assert harness.stats == [(100, 20, 80, 80.0), (100, 20, 80, 80.0)]
    harness.assert_workspace_clean()


def test_job_cleans_only_owned_stale_image_work_after_acquiring_output_lock(
    harness: ImageJobHarness,
) -> None:
    output = harness.paths.output_dir
    with acquire_output_lock(output):
        owned = image_utils.create_image_job_dir(output, 'abandoned')
        (owned / '.pjp_tmp_abandoned').write_bytes(b'temporary')
        unknown = output / '.pjp_work' / IMAGE_WORK_SUBDIR / 'unknown'
        unknown.mkdir()
        (unknown / VIDEO_WORK_OWNER_MARKER).write_text('not ours', encoding='utf-8')
        (unknown / '.pjp_tmp_unknown').write_bytes(b'keep')
        with pytest.raises(OutputLockError):
            harness.run()
        assert owned.exists()

    harness.run()
    assert not owned.exists()
    assert (unknown / '.pjp_tmp_unknown').read_bytes() == b'keep'


@pytest.mark.parametrize('mirror', [False, True])
def test_zip_image_conversion_reserves_non_target_original_name(
    harness: ImageJobHarness,
    monkeypatch: pytest.MonkeyPatch,
    mirror: bool,
) -> None:
    archive_path = harness.paths.input_dir / 'pack.zip'
    with zipfile.ZipFile(archive_path, 'w') as archive:
        archive.writestr('photo.jpg', b'j' * 100)
        archive.writestr('photo.avif', b'original avif')

    def encode(path: Path, _control: JobControl) -> image_utils.ImageEncodeOutcome:
        path.write_bytes(b'converted' * 3)
        return image_utils.ImageEncodeOutcome('encoded')

    install_simulated_encoder(monkeypatch, image_config('jpg'), encode)
    harness.run(extract_zip=True, copy_non_target_files=mirror)

    converted = harness.paths.output_dir / 'pack' / 'photo_jpg.avif'
    original_avif = harness.paths.output_dir / 'pack' / 'photo.avif'
    assert converted.read_bytes() == b'converted' * 3
    assert original_avif.exists() is mirror
    if mirror:
        assert original_avif.read_bytes() == b'original avif'
    with harness.paths.csv_path.open(newline='', encoding='utf-8') as handle:
        rows = list(csv.DictReader(handle))
    jpg_row = next(row for row in rows if row[tlog('ja', 'csv_header_input_path')] == 'pack.zip::photo.jpg')
    assert jpg_row[tlog('ja', 'csv_header_output_path')] == 'pack/photo_jpg.avif'
    assert jpg_row[tlog('ja', 'csv_header_action')] == tlog('ja', 'csv_action_avif')
    assert harness.stats == [(100, 27, 73, 73.0)]
    harness.assert_workspace_clean()
