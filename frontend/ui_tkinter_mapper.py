from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.contracts import CompressionRequest


@dataclass(frozen=True)
class RequestBuildResult:
    request: CompressionRequest
    resize_config: dict[str, Any] | bool
    resize_width: int
    resize_height: int


def to_non_negative_int(value: str) -> int:
    try:
        parsed = int(float(value.strip()))
        return parsed if parsed >= 0 else 0
    except Exception:
        return 0


def build_resize_config(app: Any) -> tuple[dict[str, Any] | bool, int, int]:
    mode = app.resize_mode.get()
    resize_width = to_non_negative_int(app.resize_width.get())
    resize_height = to_non_negative_int(app.resize_height.get())

    try:
        long_edge = max(0, int(app.long_edge_value_str.get().strip()))
    except Exception:
        long_edge = 0

    resize_config: dict[str, Any] | bool = False
    if app.resize_enabled.get():
        if mode == 'long_edge' and long_edge > 0:
            resize_config = {
                'enabled': True,
                'mode': 'long_edge',
                'long_edge': long_edge,
                'keep_aspect': True,
            }
        elif mode == 'manual' and (resize_width > 0 or resize_height > 0):
            resize_config = {
                'enabled': True,
                'mode': 'manual',
                'width': resize_width,
                'height': resize_height,
                'keep_aspect': app.resize_keep_aspect.get(),
            }

    return resize_config, resize_width, resize_height


def build_lossless_options(app: Any) -> dict[str, bool]:
    return {
        'linearize': app.pdf_ll_linearize.get(),
        'object_streams': app.pdf_ll_object_streams.get(),
        'clean_metadata': app.pdf_ll_clean_metadata.get(),
        'recompress_streams': app.pdf_ll_recompress_streams.get(),
        'remove_unreferenced': app.pdf_ll_remove_unreferenced.get(),
    }


def resolve_pdf_lossless_options(app: Any, base_options: dict[str, bool]) -> dict[str, bool] | None:
    engine = app.pdf_engine.get()
    if engine == 'gs':
        return base_options if app.gs_use_lossless.get() else None

    mode = app.pdf_mode.get()
    return base_options if mode in ('lossless', 'both') else None


def build_compression_request(app: Any) -> RequestBuildResult:
    resize_config, resize_width, resize_height = build_resize_config(app)
    lossless_options = build_lossless_options(app)
    pdf_lossless_options = resolve_pdf_lossless_options(app, lossless_options)

    gs_custom_dpi = app.gs_custom_dpi.get() if app.gs_preset.get() == 'custom' else None

    request = CompressionRequest(
        input_dir=app.input_dir.get(),
        output_dir=app.output_dir.get(),
        jpg_quality=app.jpg_quality.get(),
        png_quality=app.png_quality.get(),
        use_pngquant=app.use_pngquant.get(),
        pdf_engine=app.pdf_engine.get(),
        pdf_mode=app.pdf_mode.get(),
        pdf_dpi=app.pdf_dpi.get(),
        pdf_jpeg_quality=app.pdf_jpeg_quality.get(),
        pdf_png_to_jpeg=app.pdf_png_to_jpeg.get(),
        pdf_lossless_options=pdf_lossless_options,
        gs_preset=app.gs_preset.get(),
        gs_custom_dpi=gs_custom_dpi,
        resize_config=resize_config,
        resize_width=resize_width,
        resize_height=resize_height,
        csv_enable=app.csv_enable.get(),
        csv_path=app.csv_path.get().strip() or None,
        extract_zip=app.extract_zip.get(),
    )

    return RequestBuildResult(
        request=request,
        resize_config=resize_config,
        resize_width=resize_width,
        resize_height=resize_height,
    )
