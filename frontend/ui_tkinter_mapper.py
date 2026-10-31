from __future__ import annotations

"""UI 状態を backend 向け `CompressionRequest` へ正規化する。

controller は widget 操作、backend は request 契約に集中したいので、その間の値変換を
このモジュールへ分離している。文字列入力の補正や engine ごとの採用ルールもここで
吸収し、controller に細かな if 文を増やさない。
"""

from dataclasses import dataclass

from backend.contracts import CompressionRequest, VideoCompressionConfig
from backend.settings import VIDEO_ALLOWED_AUDIO_MODES, VIDEO_ALLOWED_CODECS, VIDEO_ALLOWED_PRESETS
from frontend.i18n import get_current_language
from frontend.settings import PDF_LOSSY_DPI_RANGE
from frontend.ui_contracts import CompressionRequestAppProtocol


MAX_RESIZE_DIMENSION = 65535

# x265 は同じ CRF でも x264 より強く圧縮されるため、同じ品質値では +4 して見た目を揃える。
_X265_CRF_OFFSET = 4
_CRF_SPAN = 22


def quality_to_crf(q: int, codec: str = 'libx264') -> int:
    """UI の品質値 (0〜100) を CRF へ変換する。品質が高いほど CRF は小さい。"""
    base = round(40 - (max(0, min(100, int(q))) / 100.0) * _CRF_SPAN)
    return min(51, base + (_X265_CRF_OFFSET if codec == 'libx265' else 0))


@dataclass(frozen=True)
class RequestBuildResult:
    """request 本体と、UI 表示やログに使う派生値をまとめた戻り値。"""

    request: CompressionRequest
    resize_config: dict[str, int | bool | str] | bool
    resize_width: int
    resize_height: int


def to_non_negative_int(value: str, max_value: int | None = None) -> int:
    """入力欄文字列を非負整数へ丸める。

    UI 入力欄は空文字や小数を含みうるため、例外を出さず backend が扱える整数へ揃える。
    """
    try:
        parsed = int(float(value.strip()))
        normalized = parsed if parsed >= 0 else 0
        if max_value is not None:
            return min(normalized, max_value)
        return normalized
    except Exception:
        return 0


def build_resize_config(app: CompressionRequestAppProtocol) -> tuple[dict[str, int | bool | str] | bool, int, int]:
    """UI のリサイズ入力を backend が理解しやすい辞書へ変換する。

    `manual` と `long_edge` の UI は入力形態が異なるが、backend には 1 つの設定オブジェクト
    として渡したいので、ここで mode ごとの差を吸収する。
    """
    mode = app.resize_mode.get()
    resize_width = to_non_negative_int(app.resize_width.get(), max_value=MAX_RESIZE_DIMENSION)
    resize_height = to_non_negative_int(app.resize_height.get(), max_value=MAX_RESIZE_DIMENSION)

    try:
        long_edge = to_non_negative_int(app.long_edge_value_str.get(), max_value=MAX_RESIZE_DIMENSION)
    except Exception:
        long_edge = 0

    resize_config: dict[str, int | bool | str] | bool = False
    if app.resize_enabled.get():
        if mode == 'long_edge' and long_edge > 0:
            # 長辺指定は縦横のどちらが長い画像でも同じ設定で再利用できる。
            resize_config = {
                'enabled': True,
                'mode': 'long_edge',
                'long_edge': long_edge,
                'keep_aspect': True,
            }
        elif mode == 'manual' and (resize_width > 0 or resize_height > 0):
            # manual では未入力側を 0 のまま渡し、画像側で片辺指定を解決する。
            resize_config = {
                'enabled': True,
                'mode': 'manual',
                'width': resize_width,
                'height': resize_height,
                'keep_aspect': app.resize_keep_aspect.get(),
            }

    return resize_config, resize_width, resize_height


def build_lossless_options(app: CompressionRequestAppProtocol) -> dict[str, bool]:
    """可逆圧縮オプション群を UI から抽出する。

    UI のチェックボックス集合を 1 箇所で辞書化しておくと、native/GS の採用判定を後段で
    共有しやすい。
    """
    return {
        'linearize': app.pdf_ll_linearize.get(),
        'object_streams': app.pdf_ll_object_streams.get(),
        'clean_metadata': app.pdf_ll_clean_metadata.get(),
        'recompress_streams': app.pdf_ll_recompress_streams.get(),
        'remove_unreferenced': app.pdf_ll_remove_unreferenced.get(),
    }


def resolve_pdf_lossless_options(
    app: CompressionRequestAppProtocol,
    base_options: dict[str, bool],
) -> dict[str, bool] | None:
    """PDF エンジンとモードに応じて可逆オプションの採用可否を決める。

    UI 上では常に可逆オプション群が見えていても、実際に意味を持つのは engine/mode に
    よって異なる。その差分を request 化の段階で明示的に `None` へ落とし込む。
    """
    engine = app.pdf_engine.get()
    if engine == 'gs':
        # Ghostscript 系では追加の pikepdf 最適化を明示的に有効化した時だけ適用する。
        return base_options if app.gs_use_lossless.get() else None

    mode = app.pdf_mode.get()
    return base_options if mode in ('lossless', 'both') else None


def build_video_config(app: CompressionRequestAppProtocol) -> VideoCompressionConfig | None:
    """動画設定を CRF 確定済みの `VideoCompressionConfig` へ変換する。動画無効時は None。

    Combobox の表示名は view 側で backend 値へ変換済みの変数に保持するが、想定外の値が
    入っても backend の検証エラーにせず、安全な既定値へ寄せる。
    """
    if not app.video_enabled.get():
        return None

    codec = app.video_codec.get()
    if codec not in VIDEO_ALLOWED_CODECS:
        codec = 'libx264'
    preset = app.video_preset.get()
    if preset not in VIDEO_ALLOWED_PRESETS:
        preset = 'medium'
    audio_mode = app.video_audio_mode.get()
    if audio_mode not in VIDEO_ALLOWED_AUDIO_MODES:
        audio_mode = 'copy'

    return VideoCompressionConfig(
        enabled=True,
        codec=codec,  # type: ignore[arg-type]
        crf=quality_to_crf(app.video_quality.get(), codec),
        preset=preset,
        audio_mode=audio_mode,  # type: ignore[arg-type]
        # 固定ビットレートは UI に出さず、チャンネル数に応じた自動値に任せる。
        audio_bitrate=None,
        max_long_edge=to_non_negative_int(app.video_max_long_edge.get(), max_value=MAX_RESIZE_DIMENSION),
    )


def build_compression_request(app: CompressionRequestAppProtocol) -> RequestBuildResult:
    """現在の UI 状態から `CompressionRequest` を構築する。

    controller が backend 用の詳細知識を持たなくてよいように、UI 状態から request 契約へ
    正規化する最後の関門として振る舞う。
    """
    resize_config, resize_width, resize_height = build_resize_config(app)
    lossless_options = build_lossless_options(app)
    pdf_lossless_options = resolve_pdf_lossless_options(app, lossless_options)

    gs_custom_dpi = None
    if app.gs_preset.get() == 'custom':
        # Ghostscript custom DPI は UI と backend の両方で clamp し、極端値でも request を
        # 安全側へ寄せる。
        gs_custom_dpi = max(PDF_LOSSY_DPI_RANGE[0], min(PDF_LOSSY_DPI_RANGE[1], int(app.gs_custom_dpi.get())))
    # カスタム以外のプリセットでは DPI を使わないため、不要な値は None に揃える。

    extract_zip = app.extract_zip.get()
    zip_output_enabled = extract_zip and app.zip_output_enabled.get()

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
        pdf_png_quality=app.pdf_png_quality.get(),
        pdf_lossless_options=pdf_lossless_options,
        gs_preset=app.gs_preset.get(),
        gs_custom_dpi=gs_custom_dpi,
        resize_config=resize_config,
        resize_width=resize_width,
        resize_height=resize_height,
        csv_enable=app.csv_enable.get(),
        csv_path=app.csv_path.get().strip() or None,
        extract_zip=extract_zip,
        zip_output_enabled=zip_output_enabled,
        debug_mode=app.debug_mode.get(),
        copy_non_target_files=app.copy_non_target_files.get(),
        log_language=get_current_language(),
        video_config=build_video_config(app),
    )

    return RequestBuildResult(
        request=request,
        resize_config=resize_config,
        resize_width=resize_width,
        resize_height=resize_height,
    )
