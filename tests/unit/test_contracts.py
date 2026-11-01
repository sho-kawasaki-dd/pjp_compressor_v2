from __future__ import annotations

"""contract dataclass が橋渡し層として壊れていないか確認する unit test。"""

import pytest
from dataclasses import replace

from backend.contracts import (
    CapabilityReport,
    CompressionRequest,
    JobControl,
    ProgressEvent,
    VideoCompressionConfig,
)


pytestmark = pytest.mark.unit


def test_video_config_defaults_and_validation() -> None:
    config = VideoCompressionConfig()

    assert (config.codec, config.crf, config.preset, config.audio_mode) == ('libx264', 24, 'medium', 'copy')
    assert config.audio_bitrate is None and config.max_long_edge == 0
    assert VideoCompressionConfig.from_mapping({'codec': 'libx264', 'crf': 30, 'audio_bitrate': '192k'}).crf == 30


@pytest.mark.parametrize(
    'payload',
    [
        {'codec': 'vp9'},
        {'codec': 'libx265'},
        {'crf': 52},
        {'crf': -1},
        {'crf': '24'},
        {'crf': True},
        {'preset': 'turbo'},
        {'audio_mode': 'opus'},
        {'audio_bitrate': '128'},
        {'audio_bitrate': 'fast'},
        {'max_long_edge': -1},
        {'enabled': 1},
        {'bogus': 1},
    ],
)
def test_video_config_rejects_invalid_values(payload: dict) -> None:
    with pytest.raises(ValueError):
        VideoCompressionConfig.from_mapping(payload)


def test_video_config_from_mapping_rejects_non_mapping() -> None:
    with pytest.raises(ValueError):
        VideoCompressionConfig.from_mapping('libx264')  # type: ignore[arg-type]


def test_capability_report_video_properties() -> None:
    base = dict(fitz_available=True, pikepdf_available=True, ghostscript_path=None, pngquant_path=None)
    ready = CapabilityReport(
        **base,
        ffmpeg_path='ffmpeg', ffmpeg_source='system', ffmpeg_encoders=frozenset({'libx264', 'libx265'}),
        ffprobe_path='ffprobe', ffprobe_source='system',
    )
    assert ready.video_available

    no_hevc = CapabilityReport(**base, ffmpeg_path='ffmpeg', ffmpeg_encoders=frozenset({'libx264'}), ffprobe_path='ffprobe')
    assert no_hevc.video_available

    no_probe = CapabilityReport(**base, ffmpeg_path='ffmpeg', ffmpeg_encoders=frozenset({'libx264'}))
    assert no_probe.ffmpeg_available and not no_probe.ffprobe_available and not no_probe.video_available

    failed = CapabilityReport(
        **base, ffmpeg_path='ffmpeg', ffmpeg_encoders=frozenset({'libx264'}), ffmpeg_detection_error='boom',
        ffprobe_path='ffprobe',
    )
    assert not failed.ffmpeg_available and not failed.video_available

    no_x264 = CapabilityReport(**base, ffmpeg_path='ffmpeg', ffmpeg_encoders=frozenset({'libx265'}), ffprobe_path='ffprobe')
    assert not no_x264.ffmpeg_available


def test_progress_event_video_phase_defaults_to_none() -> None:
    assert ProgressEvent(kind='progress').video_phase is None
    event = ProgressEvent(kind='video_progress', message='a.mp4', video_phase='started', current=None)
    assert event.video_phase == 'started' and event.current is None
    assert ProgressEvent(kind='cancelled', message='stopped').kind == 'cancelled'


def test_job_control_tracks_processes_and_cancel() -> None:
    control = JobControl()
    proc = object()

    assert control.is_cancelled is False
    control.register(proc)  # type: ignore[arg-type]
    assert control.snapshot() == (proc,)
    control.request_cancel()
    assert control.is_cancelled is True and control.cancel_event.is_set()
    control.unregister(proc)  # type: ignore[arg-type]
    control.unregister(proc)  # type: ignore[arg-type]
    assert control.snapshot() == ()
    assert not control.launch_lock.locked()
    assert JobControl().cancel_event is not control.cancel_event


def test_capability_report_properties_reflect_detected_paths() -> None:
    report = CapabilityReport(
        fitz_available=False,
        pikepdf_available=True,
        ghostscript_path='C:/gs/gswin64c.exe',
        pngquant_path=None,
        ghostscript_source='bundled',
        pngquant_source='unavailable',
    )

    assert report.ghostscript_available is True
    assert report.pngquant_available is False
    assert report.native_pdf_available is True
    assert report.ghostscript_source == 'bundled'


def test_progress_event_defaults_are_optional() -> None:
    event = ProgressEvent(kind='log', message='hello')

    assert event.message == 'hello'
    assert event.current is None
    assert event.saved_pct is None


def test_compression_request_to_legacy_kwargs_includes_debug_mode() -> None:
    request = CompressionRequest(
        input_dir='input',
        output_dir='output',
        jpg_quality=72,
        png_quality=61,
        use_pngquant=True,
        pdf_engine='native',
        pdf_mode='both',
        pdf_dpi=144,
        pdf_jpeg_quality=60,
        pdf_png_quality=58,
        pdf_lossless_options={'linearize': True},
        gs_preset='/screen',
        gs_custom_dpi=None,
        resize_config={'enabled': True, 'mode': 'long_edge', 'long_edge': 1280},
        resize_width=0,
        resize_height=0,
        csv_enable=True,
        csv_path='out/log.csv',
        extract_zip=True,
        zip_output_enabled=False,
        debug_mode=True,
        copy_non_target_files=False,
        log_language='ja',
    )

    log_messages: list[str] = []
    progress_calls: list[tuple[int, int]] = []
    stats_calls: list[tuple[int, int, int, float]] = []
    kwargs = request.to_legacy_kwargs(
        log_func=log_messages.append,
        progress_func=lambda current, total: progress_calls.append((current, total)),
        stats_func=lambda orig, out, saved, pct: stats_calls.append((orig, out, saved, pct)),
    )

    assert kwargs['debug_mode'] is True
    assert kwargs['zip_output_enabled'] is False
    assert kwargs['pdf_png_quality'] == 58
    assert kwargs['resize_enabled'] == {'enabled': True, 'mode': 'long_edge', 'long_edge': 1280}
    assert kwargs['video_config'] is None
    request_with_video = replace(request, video_config=VideoCompressionConfig(crf=28))
    assert request_with_video.to_legacy_kwargs(print, lambda c, t: None, lambda *a: None)['video_config'].crf == 28
    assert request.log_language == 'ja'
    assert kwargs['log_func'].__self__ is log_messages
    assert callable(kwargs['progress_func'])
    assert callable(kwargs['stats_func'])
