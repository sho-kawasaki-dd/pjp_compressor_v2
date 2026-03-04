from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal

EventKind = Literal['log', 'progress', 'stats', 'status', 'error']


@dataclass(frozen=True)
class ProgressEvent:
    kind: EventKind
    message: str | None = None
    current: int | None = None
    total: int | None = None
    orig_total: int | None = None
    out_total: int | None = None
    saved: int | None = None
    saved_pct: float | None = None


@dataclass(frozen=True)
class CapabilityReport:
    fitz_available: bool
    pikepdf_available: bool
    ghostscript_path: str | None
    pngquant_path: str | None

    @property
    def ghostscript_available(self) -> bool:
        return bool(self.ghostscript_path)

    @property
    def pngquant_available(self) -> bool:
        return bool(self.pngquant_path)

    @property
    def native_pdf_available(self) -> bool:
        return self.fitz_available or self.pikepdf_available


@dataclass(frozen=True)
class CompressionResult:
    processed_files: int
    orig_total: int
    out_total: int
    saved: int
    saved_pct: float


@dataclass(frozen=True)
class CompressionRequest:
    input_dir: str
    output_dir: str
    jpg_quality: int
    png_quality: int
    use_pngquant: bool
    pdf_engine: str
    pdf_mode: str
    pdf_dpi: int
    pdf_jpeg_quality: int
    pdf_png_to_jpeg: bool
    pdf_lossless_options: dict[str, Any] | None
    gs_preset: str
    gs_custom_dpi: int | None
    resize_config: dict[str, Any] | bool
    resize_width: int
    resize_height: int
    csv_enable: bool
    csv_path: str | None
    extract_zip: bool

    def to_legacy_kwargs(
        self,
        log_func: Callable[[str], None],
        progress_func: Callable[[int, int], None],
        stats_func: Callable[[int, int, int, float], None],
    ) -> dict[str, Any]:
        return {
            'input_dir': self.input_dir,
            'output_dir': self.output_dir,
            'jpg_quality': self.jpg_quality,
            'png_quality': self.png_quality,
            'use_pngquant': self.use_pngquant,
            'log_func': log_func,
            'progress_func': progress_func,
            'stats_func': stats_func,
            'pdf_engine': self.pdf_engine,
            'pdf_mode': self.pdf_mode,
            'pdf_dpi': self.pdf_dpi,
            'pdf_jpeg_quality': self.pdf_jpeg_quality,
            'pdf_png_to_jpeg': self.pdf_png_to_jpeg,
            'pdf_lossless_options': self.pdf_lossless_options,
            'gs_preset': self.gs_preset,
            'gs_custom_dpi': self.gs_custom_dpi,
            'resize_enabled': self.resize_config,
            'resize_width': self.resize_width,
            'resize_height': self.resize_height,
            'csv_enable': self.csv_enable,
            'csv_path': self.csv_path,
            'extract_zip': self.extract_zip,
        }
