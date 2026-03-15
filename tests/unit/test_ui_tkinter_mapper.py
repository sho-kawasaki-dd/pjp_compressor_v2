from __future__ import annotations

import pytest

from frontend.ui_tkinter_mapper import (
    build_compression_request,
    build_resize_config,
    resolve_pdf_lossless_options,
    to_non_negative_int,
)


pytestmark = pytest.mark.unit


class DummyVar:
    def __init__(self, value):
        self._value = value

    def get(self):
        return self._value

    def set(self, value):
        self._value = value


class DummyApp:
    def __init__(self) -> None:
        self.input_dir = DummyVar('input')
        self.output_dir = DummyVar('output')
        self.jpg_quality = DummyVar(70)
        self.png_quality = DummyVar(60)
        self.use_pngquant = DummyVar(True)
        self.pdf_engine = DummyVar('native')
        self.pdf_mode = DummyVar('both')
        self.pdf_dpi = DummyVar(144)
        self.pdf_jpeg_quality = DummyVar(65)
        self.pdf_png_quality = DummyVar(62)
        self.pdf_ll_linearize = DummyVar(True)
        self.pdf_ll_object_streams = DummyVar(True)
        self.pdf_ll_clean_metadata = DummyVar(True)
        self.pdf_ll_recompress_streams = DummyVar(False)
        self.pdf_ll_remove_unreferenced = DummyVar(True)
        self.gs_preset = DummyVar('/screen')
        self.gs_custom_dpi = DummyVar(0)
        self.gs_use_lossless = DummyVar(False)
        self.resize_enabled = DummyVar(True)
        self.resize_mode = DummyVar('long_edge')
        self.resize_width = DummyVar('0')
        self.resize_height = DummyVar('0')
        self.resize_keep_aspect = DummyVar(True)
        self.long_edge_value_str = DummyVar('1024')
        self.csv_enable = DummyVar(True)
        self.csv_path = DummyVar('  out/log.csv  ')
        self.extract_zip = DummyVar(True)
        self.debug_mode = DummyVar(True)
        self.copy_non_target_files = DummyVar(False)


def test_to_non_negative_int_normalizes_invalid_values() -> None:
    assert to_non_negative_int('42') == 42
    assert to_non_negative_int('-4') == 0
    assert to_non_negative_int('3.8') == 3
    assert to_non_negative_int('abc') == 0


def test_build_resize_config_supports_long_edge_mode() -> None:
    app = DummyApp()

    resize_config, resize_width, resize_height = build_resize_config(app)

    assert resize_config == {
        'enabled': True,
        'mode': 'long_edge',
        'long_edge': 1024,
        'keep_aspect': True,
    }
    assert resize_width == 0
    assert resize_height == 0


def test_resolve_pdf_lossless_options_respects_engine() -> None:
    app = DummyApp()
    options = {'linearize': True}

    assert resolve_pdf_lossless_options(app, options) == options
    app.pdf_engine.set('gs')
    app.gs_use_lossless.set(False)
    assert resolve_pdf_lossless_options(app, options) is None
    app.gs_use_lossless.set(True)
    assert resolve_pdf_lossless_options(app, options) == options


def test_build_compression_request_includes_debug_mode_and_trimmed_csv() -> None:
    app = DummyApp()
    result = build_compression_request(app)

    assert result.request.debug_mode is True
    assert result.request.pdf_png_quality == 62
    assert result.request.csv_path == 'out/log.csv'
    assert result.request.resize_config == {
        'enabled': True,
        'mode': 'long_edge',
        'long_edge': 1024,
        'keep_aspect': True,
    }