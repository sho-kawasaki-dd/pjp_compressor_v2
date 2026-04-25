from __future__ import annotations

"""contract dataclass が橋渡し層として壊れていないか確認する unit test。"""

import pytest

from backend.contracts import CapabilityReport, CompressionRequest, ProgressEvent


pytestmark = pytest.mark.unit


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
        debug_mode=True,
        copy_non_target_files=False,
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
    assert kwargs['pdf_png_quality'] == 58
    assert kwargs['resize_enabled'] == {'enabled': True, 'mode': 'long_edge', 'long_edge': 1280}
    assert kwargs['log_func'].__self__ is log_messages
    assert callable(kwargs['progress_func'])
    assert callable(kwargs['stats_func'])
