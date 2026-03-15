from __future__ import annotations

"""backend 全体で共有するデータ契約を定義する。

UI と orchestrator は生の関数引数を直接やり取りせず、このモジュールの
データクラスを介して進捗通知や実行要求を受け渡す。これにより、
呼び出し元が増えてもイベント形式と request 形式を一箇所で保守できる。
"""

from dataclasses import dataclass
from typing import Any, Callable, Literal

EventKind = Literal['log', 'progress', 'stats', 'status', 'error']


@dataclass(frozen=True)
class ProgressEvent:
    """バックグラウンド処理から UI へ渡す単一イベント。

    `kind` ごとに利用するフィールドが変わるため、未使用フィールドは None のまま
    にして payload を簡潔に保つ。
    """

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
    """実行環境で利用可能な任意依存と外部ツールの検出結果。"""

    fitz_available: bool
    pikepdf_available: bool
    ghostscript_path: str | None
    pngquant_path: str | None

    @property
    def ghostscript_available(self) -> bool:
        """Ghostscript 実行可能ファイルが見つかったかを返す。"""
        return bool(self.ghostscript_path)

    @property
    def pngquant_available(self) -> bool:
        """pngquant 実行可能ファイルが見つかったかを返す。"""
        return bool(self.pngquant_path)

    @property
    def native_pdf_available(self) -> bool:
        """PyMuPDF か pikepdf の少なくとも片方が使えるかを返す。"""
        return self.fitz_available or self.pikepdf_available


@dataclass(frozen=True)
class CompressionResult:
    """圧縮ジョブ完了後に参照する集計値。"""

    processed_files: int
    orig_total: int
    out_total: int
    saved: int
    saved_pct: float


@dataclass(frozen=True)
class CompressionRequest:
    """UI から orchestrator へ渡す圧縮実行パラメータ一式。"""

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
    copy_non_target_files: bool

    def to_legacy_kwargs(
        self,
        log_func: Callable[[str], None],
        progress_func: Callable[[int, int], None],
        stats_func: Callable[[int, int, int, float], None],
    ) -> dict[str, Any]:
        """旧 `run_compression_job` 呼び出し形式へ橋渡しする。

        orchestrator 移行中も既存 API を壊さないため、dataclass を一度辞書へ展開して
        従来のキーワード引数構造を維持する。
        """
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
            'copy_non_target_files': self.copy_non_target_files,
        }
