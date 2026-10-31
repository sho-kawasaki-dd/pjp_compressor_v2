from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import pytest

from backend.contracts import CapabilityReport, JobControl, ProgressEvent, VideoCompressionConfig
from backend.core import worker_ops
from backend.core.video_utils import VideoCompressResult
from backend.orchestrator import job_runner
from backend.orchestrator.job_lock import OutputLockError, acquire_output_lock
from backend.settings import APP_WORK_DIR_NAME, VIDEO_WORK_SUBDIR
from shared.locale_catalog import translate as tlog

pytestmark = pytest.mark.integration

VIDEO_CAPS = CapabilityReport(
    True,
    True,
    None,
    None,
    ffmpeg_path='ffmpeg',
    ffmpeg_source='system',
    ffmpeg_encoders=frozenset({'libx264', 'aac'}),
    ffprobe_path='ffprobe',
    ffprobe_source='system',
)


class JobHarness:
    """run_compression_job の通知先をまとめて記録する。"""

    def __init__(self, sample_paths) -> None:
        self.sample_paths = sample_paths
        self.logs: list[str] = []
        self.events: list[ProgressEvent] = []
        self.progress: list[tuple[int, int]] = []
        self.stats: list[tuple[int, int, int, float]] = []

    def run(self, **kwargs: Any) -> None:
        params: dict[str, Any] = dict(
            input_dir=str(self.sample_paths.input_dir),
            output_dir=str(self.sample_paths.output_dir),
            jpg_quality=70,
            png_quality=70,
            use_pngquant=False,
            log_func=self.logs.append,
            progress_func=lambda current, total: self.progress.append((current, total)),
            stats_func=lambda *values: self.stats.append(values),
            csv_enable=True,
            csv_path=str(self.sample_paths.csv_path),
            log_language='ja',
        )
        params.update(kwargs)
        job_runner.run_compression_job(**params)

    def csv_rows(self) -> list[dict[str, str]]:
        with open(self.sample_paths.csv_path, newline='', encoding='utf-8') as handle:
            return list(csv.DictReader(handle))


@pytest.fixture
def harness(sample_paths, monkeypatch: pytest.MonkeyPatch) -> JobHarness:
    monkeypatch.setattr(job_runner, 'detect_capabilities', lambda: VIDEO_CAPS)
    return JobHarness(sample_paths)


def write_video(path: Path, size: int = 100) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'v' * size)
    return path


def install_fake_compress(monkeypatch: pytest.MonkeyPatch, behavior) -> list[str]:
    calls: list[str] = []

    def fake(inpath, outpath, original_outpath, config, *, capabilities, job_control, temp_dir, progress_callback=None, log_language='ja'):
        calls.append(Path(inpath).name)
        return behavior(
            Path(inpath), Path(outpath), Path(original_outpath), progress_callback, job_control,
        )

    monkeypatch.setattr(worker_ops, 'compress_video_ffmpeg', fake)
    return calls


def compress_ok(inpath: Path, outpath: Path, original_outpath: Path, progress_callback, job_control) -> VideoCompressResult:
    if progress_callback:
        progress_callback(None)
        progress_callback(50)
    outpath.parent.mkdir(parents=True, exist_ok=True)
    outpath.write_bytes(b'c' * 10)
    return VideoCompressResult(ok=True, message=f'ok {inpath.name}', final_outpath=str(outpath), notes=('dropped_data_streams=tmcd',))


def assert_workspace_released(output_dir: Path) -> None:
    video_root = output_dir / APP_WORK_DIR_NAME / VIDEO_WORK_SUBDIR
    assert not video_root.exists() or not any(video_root.iterdir())
    with acquire_output_lock(output_dir):
        pass


def test_video_outputs_are_named_deterministically_and_reported(harness: JobHarness, sample_paths, monkeypatch) -> None:
    write_video(sample_paths.input_dir / 'sample.mp4')
    write_video(sample_paths.input_dir / 'sample.mov')
    calls = install_fake_compress(monkeypatch, compress_ok)

    for _ in range(2):  # 再実行しても出力名は変わらず、同じファイルを上書きする
        harness.run(video_config=VideoCompressionConfig(), event_func=harness.events.append)

    assert sorted(calls) == ['sample.mov', 'sample.mov', 'sample.mp4', 'sample.mp4']
    assert sorted(p.name for p in sample_paths.output_dir.glob('*.mp4')) == ['sample.mp4', 'sample_mov.mp4']
    rows = harness.csv_rows()
    assert sorted(row[tlog('ja', 'csv_header_output_path')] for row in rows) == ['sample.mp4', 'sample_mov.mp4']
    assert {row[tlog('ja', 'csv_header_action')] for row in rows} == {tlog('ja', 'csv_action_video')}
    assert all(row[tlog('ja', 'csv_header_notes')] == 'dropped_data_streams=tmcd' for row in rows)
    assert len(harness.stats) == 2
    assert_workspace_released(sample_paths.output_dir)


def test_video_events_distinguish_started_updated_and_finished(harness: JobHarness, sample_paths, monkeypatch) -> None:
    write_video(sample_paths.input_dir / 'clip.mov')
    install_fake_compress(monkeypatch, compress_ok)

    harness.run(video_config=VideoCompressionConfig(), event_func=harness.events.append)

    video_events = [(e.video_phase, e.current, e.message) for e in harness.events if e.kind == 'video_progress']
    assert video_events == [
        ('started', None, 'clip.mov'),
        ('updated', None, 'clip.mov'),
        ('updated', 50, 'clip.mov'),
        ('finished', None, 'clip.mov'),
    ]


def test_kept_original_is_recorded_with_original_extension_and_reason(harness: JobHarness, sample_paths, monkeypatch) -> None:
    write_video(sample_paths.input_dir / 'clip.mov')

    def keep(inpath, outpath, original_outpath, progress_callback, job_control):
        original_outpath.parent.mkdir(parents=True, exist_ok=True)
        original_outpath.write_bytes(inpath.read_bytes())
        return VideoCompressResult(
            ok=True, message='kept', final_outpath=str(original_outpath),
            kept_original=True, kept_original_reason='retention', notes=('hdr',),
        )

    install_fake_compress(monkeypatch, keep)

    harness.run(video_config=VideoCompressionConfig())

    (row,) = harness.csv_rows()
    assert row[tlog('ja', 'csv_header_output_path')] == 'clip.mov'
    assert row[tlog('ja', 'csv_header_action')] == tlog('ja', 'csv_action_video_kept_retention')
    assert row[tlog('ja', 'csv_header_notes')] == 'hdr'
    assert not (sample_paths.output_dir / 'clip.mp4').exists()
    assert harness.stats[0][0] == 100  # 元維持も配置できたので processed として集計する


def failing(inpath, outpath, original_outpath, progress_callback, job_control) -> VideoCompressResult:
    return VideoCompressResult(ok=False, message='boom', final_outpath=None)


def test_failed_video_is_copied_with_original_extension_in_mirror_mode(harness: JobHarness, sample_paths, monkeypatch) -> None:
    source = write_video(sample_paths.input_dir / 'clip.mov')
    install_fake_compress(monkeypatch, failing)

    harness.run(video_config=VideoCompressionConfig(), copy_non_target_files=True)

    assert (sample_paths.output_dir / 'clip.mov').read_bytes() == source.read_bytes()
    assert not (sample_paths.output_dir / 'clip.mp4').exists()
    (row,) = harness.csv_rows()
    assert row[tlog('ja', 'csv_header_output_path')] == 'clip.mov'
    assert row[tlog('ja', 'csv_header_action')] == tlog('ja', 'csv_action_fallback_copy')
    assert_workspace_released(sample_paths.output_dir)


def test_failed_video_leaves_no_output_without_mirror_mode(harness: JobHarness, sample_paths, monkeypatch) -> None:
    write_video(sample_paths.input_dir / 'clip.mov')
    install_fake_compress(monkeypatch, failing)

    harness.run(video_config=VideoCompressionConfig())

    assert not (sample_paths.output_dir / 'clip.mov').exists()
    (row,) = harness.csv_rows()
    assert row[tlog('ja', 'csv_header_output_path')] == ''
    assert row[tlog('ja', 'csv_header_action')] == tlog('ja', 'csv_action_failed')


def test_video_is_non_target_when_video_config_is_absent(harness: JobHarness, sample_paths, monkeypatch) -> None:
    write_video(sample_paths.input_dir / 'clip.mov')
    calls = install_fake_compress(monkeypatch, compress_ok)

    harness.run(copy_non_target_files=True)

    assert calls == []
    assert (sample_paths.output_dir / 'clip.mov').exists()
    assert any(tlog('ja', 'log_non_target_copy') in message for message in harness.logs)


def test_video_is_skipped_with_reason_when_tools_are_unavailable(sample_paths, monkeypatch) -> None:
    monkeypatch.setattr(job_runner, 'detect_capabilities', lambda: CapabilityReport(True, True, None, None))
    harness = JobHarness(sample_paths)
    write_video(sample_paths.input_dir / 'clip.mov')
    calls = install_fake_compress(monkeypatch, compress_ok)

    harness.run(video_config=VideoCompressionConfig(), copy_non_target_files=True)

    assert calls == []
    expected = tlog('ja', 'video_tool_unavailable', reason=tlog('ja', 'video_ffmpeg_missing'))
    assert expected in harness.logs
    assert (sample_paths.output_dir / 'clip.mov').exists()
    assert not (sample_paths.output_dir / APP_WORK_DIR_NAME / VIDEO_WORK_SUBDIR).exists()


def test_input_work_dir_is_never_scanned(harness: JobHarness, sample_paths, monkeypatch) -> None:
    write_video(sample_paths.input_dir / APP_WORK_DIR_NAME / 'video' / 'leftover.mov')
    calls = install_fake_compress(monkeypatch, compress_ok)

    harness.run(video_config=VideoCompressionConfig())

    assert calls == []
    assert harness.progress == [(1, 1)]


def test_job_rejects_overlapping_input_and_output(harness: JobHarness, sample_paths) -> None:
    with pytest.raises(ValueError):
        harness.run(output_dir=str(sample_paths.input_dir / 'out'))
    assert not (sample_paths.input_dir / 'out').exists()


def test_job_rejects_output_folder_in_use_without_side_effects(harness: JobHarness, sample_paths) -> None:
    write_video(sample_paths.input_dir / 'clip.mov')

    with acquire_output_lock(sample_paths.output_dir):
        with pytest.raises(OutputLockError):
            harness.run(video_config=VideoCompressionConfig())

    assert not sample_paths.csv_path.exists()
    assert harness.logs == []


def test_stop_request_cancels_remaining_videos_and_skips_completion(harness: JobHarness, sample_paths, monkeypatch) -> None:
    for name in ('a.mov', 'b.mov', 'c.mov'):
        write_video(sample_paths.input_dir / name)
    control = JobControl()

    def cancel_on_first(inpath, outpath, original_outpath, progress_callback, job_control):
        job_control.request_cancel()
        return VideoCompressResult(ok=False, message='cancelled', final_outpath=None, cancelled=True)

    calls = install_fake_compress(monkeypatch, cancel_on_first)

    harness.run(video_config=VideoCompressionConfig(), event_func=harness.events.append, job_control=control)

    assert len(calls) == 1
    cancelled = [event for event in harness.events if event.kind == 'cancelled']
    assert len(cancelled) == 1
    assert cancelled[0].message
    assert harness.stats == []
    assert tlog('ja', 'log_complete') not in harness.logs
    assert list(sample_paths.output_dir.glob('*.mp4')) == []
    assert_workspace_released(sample_paths.output_dir)
    # 中断された動画は成果物のないまま CSV へ中断として残る。
    assert all(row[tlog('ja', 'csv_header_output_path')] == '' for row in harness.csv_rows())


def test_pre_cancelled_job_does_nothing_and_reports_via_log_for_legacy_api(harness: JobHarness, sample_paths, monkeypatch) -> None:
    write_video(sample_paths.input_dir / 'a.mov')
    calls = install_fake_compress(monkeypatch, compress_ok)
    control = JobControl()
    control.request_cancel()

    harness.run(video_config=VideoCompressionConfig(), job_control=control)

    assert calls == []
    assert harness.stats == []
    assert any('中断' in message for message in harness.logs)
    assert not sample_paths.csv_path.exists()


def test_plan_video_outputs_avoids_case_insensitive_collisions_in_any_order() -> None:
    def candidate(name: str) -> job_runner._TaskCandidate:
        base = Path('out') / name
        return job_runner._TaskCandidate(Path('in') / name, base, name, name, '')

    names = ['Sample.mp4', 'sample.mov', 'SAMPLE.m4v', 'sample_mov.mp4']
    results: set[tuple[str, ...]] = set()
    for ordering in (names, list(reversed(names)), [names[2], names[0], names[3], names[1]]):
        candidates = [candidate(name) for name in ordering]
        planned = job_runner._plan_video_outputs(candidates, lambda c: c.inpath.suffix != '')
        by_input = {candidates[i].inpath.name: planned[i].name for i in planned}
        results.add(tuple(sorted(by_input.items())))

    assert len(results) == 1
    mapping = dict(next(iter(results)))
    assert mapping['sample.mov'] == 'sample_mov_2.mp4'  # sample_mov.mp4 は別入力の既定出力先として予約済み
    assert mapping['SAMPLE.m4v'] == 'SAMPLE_m4v.mp4'
    assert mapping['Sample.mp4'] == 'Sample.mp4'
