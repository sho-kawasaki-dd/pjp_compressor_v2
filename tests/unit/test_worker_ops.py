from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from backend.contracts import CapabilityReport, ImageCompressionConfig, JobControl, VideoCompressionConfig
from backend.core import worker_ops
from backend.core.video_utils import VideoCompressResult

pytestmark = pytest.mark.unit


def build_task(inpath: Path, outpath: Path, ext: str, *extra: Any) -> tuple[Any, ...]:
    base = (
        str(inpath), str(outpath), ext,
        'native', 'both', 144, 70, 70, {}, 'ebook', None,
        70, 70, False, None, False,
        inpath.name, outpath.name, '', 'ja',
    )
    return base + tuple(extra)


def video_extra(**overrides: Any) -> tuple[Any, ...]:
    values: dict[str, Any] = {
        'video_config': VideoCompressionConfig(),
        'callback': None,
        'original_outpath': None,
        'job_control': JobControl(),
        'capabilities': CapabilityReport(False, False, None, None),
        'video_temp_dir': None,
    }
    values.update(overrides)
    return tuple(values.values())


def test_process_single_file_accepts_legacy_twenty_element_tasks(tmp_path: Path) -> None:
    source = tmp_path / 'note.txt'
    source.write_text('hello', encoding='utf-8')

    result = worker_ops.process_single_file(build_task(source, tmp_path / 'out' / 'note.txt', 'txt'))

    assert result.processed is False
    assert result.cancelled is False
    assert result.final_outpath is None


def test_process_single_file_returns_cancelled_result_without_creating_output(tmp_path: Path) -> None:
    source = tmp_path / 'photo.jpg'
    source.write_bytes(b'0' * 10)
    control = JobControl()
    control.request_cancel()
    outpath = tmp_path / 'out' / 'photo.jpg'

    result = worker_ops.process_single_file(
        build_task(source, outpath, 'jpg', None, None, str(outpath), control, None, None)
    )

    assert result.cancelled is True
    assert result.processed is False
    assert result.action_key == 'csv_action_cancelled'
    assert not outpath.parent.exists()


def test_process_single_file_rejects_video_task_without_required_context(tmp_path: Path) -> None:
    source = tmp_path / 'clip.mov'
    source.write_bytes(b'0' * 10)

    with pytest.raises(ValueError, match='video_temp_dir'):
        worker_ops.process_single_file(
            build_task(source, tmp_path / 'out' / 'clip.mp4', 'mov', *video_extra())
        )


@pytest.mark.parametrize(
    ('input_ext', 'output_ext', 'config'),
    [
        ('jpg', 'avif', ImageCompressionConfig(output_format='avif')),
        ('avif', 'jpg', ImageCompressionConfig(avif_to_jpeg_compat=True)),
    ],
)
def test_new_image_codecs_remain_explicitly_unavailable_until_later_phases(
    tmp_path: Path,
    input_ext: str,
    output_ext: str,
    config: ImageCompressionConfig,
) -> None:
    source = tmp_path / f'photo.{input_ext}'
    source.write_bytes(b'original')
    output = tmp_path / 'out' / f'photo.{output_ext}'
    original = output.parent / source.name

    result = worker_ops.process_single_file(
        build_task(source, output, input_ext, None, None, str(original), JobControl(), None, None, config, str(tmp_path / 'work'))
    )

    assert not result.processed and result.final_outpath is None
    assert result.action_key == 'csv_action_failed'
    assert 'まだ利用できません' in result.message
    assert not output.exists() and not original.exists()


def test_process_single_file_preserves_hevc_prohibition_in_csv_notes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / 'clip.mov'
    source.write_bytes(b'original')
    original_outpath = tmp_path / 'out' / source.name

    def fake_compress(*_args, **_kwargs):
        return VideoCompressResult(
            ok=True,
            message='original kept because H.265/HEVC use is prohibited',
            final_outpath=str(original_outpath),
            kept_original=True,
            kept_original_reason='retention',
            notes=('hevc_input_prohibited',),
        )

    monkeypatch.setattr(worker_ops, 'compress_video_ffmpeg', fake_compress)
    outcome = worker_ops.process_single_file(
        build_task(
            source,
            tmp_path / 'out' / 'clip.mp4',
            'mov',
            *video_extra(original_outpath=str(original_outpath), video_temp_dir=str(tmp_path / 'work')),
        )
    )

    assert outcome.action_key == 'csv_action_video_kept_retention'
    assert outcome.processed is True
    assert outcome.notes == 'hevc_input_prohibited'


@pytest.mark.parametrize(
    ('result', 'expected_key', 'expected_processed'),
    [
        (dict(ok=True, kept_original=False), 'csv_action_video', True),
        (dict(ok=True, kept_original=True, kept_original_reason='no_gain'), 'csv_action_video_kept_original', True),
        (dict(ok=True, kept_original=True, kept_original_reason='retention'), 'csv_action_video_kept_retention', True),
        (dict(ok=False), 'csv_action_failed', False),
        (dict(ok=False, cancelled=True), 'csv_action_cancelled', False),
    ],
)
def test_process_single_file_maps_video_results(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    result: dict[str, Any],
    expected_key: str,
    expected_processed: bool,
) -> None:
    source = tmp_path / 'clip.mov'
    source.write_bytes(b'0' * 100)
    placed = tmp_path / 'out' / 'clip.mp4'
    calls: list[dict[str, Any]] = []

    def fake_compress(inpath, outpath, original_outpath, config, **kwargs):
        calls.append({'original_outpath': original_outpath, **kwargs})
        final = None
        if result['ok']:
            placed.parent.mkdir(parents=True, exist_ok=True)
            placed.write_bytes(b'1' * 40)
            final = str(placed)
        return VideoCompressResult(final_outpath=final, message='msg', notes=('a=1', 'b'), **result)

    monkeypatch.setattr(worker_ops, 'compress_video_ffmpeg', fake_compress)
    control = JobControl()

    outcome = worker_ops.process_single_file(
        build_task(
            source, placed, 'mov',
            *video_extra(original_outpath=str(tmp_path / 'out' / 'clip.mov'), job_control=control, video_temp_dir=str(tmp_path / 'work')),
        )
    )

    assert outcome.action_key == expected_key
    assert outcome.processed is expected_processed
    assert outcome.notes == 'a=1;b'
    assert outcome.cancelled is bool(result.get('cancelled'))
    assert outcome.out_size == (40 if result['ok'] else 100)
    assert calls[0]['original_outpath'] == str(tmp_path / 'out' / 'clip.mov')
    assert calls[0]['job_control'] is control
