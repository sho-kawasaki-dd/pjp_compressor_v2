from __future__ import annotations

"""backend 全体で共有するデータ契約を定義する。

UI と orchestrator は生の関数引数を直接やり取りせず、このモジュールの
データクラスを介して進捗通知や実行要求を受け渡す。これにより、
呼び出し元が増えてもイベント形式と request 形式を一箇所で保守できる。
"""

from dataclasses import dataclass
import re
import subprocess
import threading
from typing import Any, Callable, Literal, Mapping

from .settings import (
    VIDEO_ALLOWED_AUDIO_MODES,
    VIDEO_ALLOWED_CODECS,
    VIDEO_ALLOWED_PRESETS,
    VIDEO_CRF_DEFAULT,
    VIDEO_CRF_RANGE,
)

EventKind = Literal['log', 'progress', 'stats', 'status', 'error', 'video_progress', 'cancelled']
VideoPhase = Literal['started', 'updated', 'finished']
ToolSource = Literal['system', 'bundled', 'unavailable']

_AUDIO_BITRATE_PATTERN = re.compile(r'^[1-9]\d{0,3}k$')


@dataclass(frozen=True)
class ProgressEvent:
    """バックグラウンド処理から UI へ渡す単一イベント。

    `kind` ごとに利用するフィールドが変わるため、未使用フィールドは None のまま
    にして payload を簡潔に保つ。

    動画イベントは `kind='video_progress'`、`message=<ファイル名>`、`video_phase=<段階>`、
    `current=<pct | None>` で表す。`current=None` は割合不明のみを表し、表示のクリアは
    `video_phase='finished'` で行う。`cancelled` はジョブの終端イベントで、途中までの
    集計値と中断メッセージを持つ。
    """

    kind: EventKind
    message: str | None = None
    current: int | None = None
    total: int | None = None
    orig_total: int | None = None
    out_total: int | None = None
    saved: int | None = None
    saved_pct: float | None = None
    video_phase: VideoPhase | None = None


@dataclass(frozen=True)
class VideoCompressionConfig:
    """動画圧縮設定。backend は CRF のみを正とし、UI の品質値は保持しない。"""

    enabled: bool = True
    codec: Literal['libx264'] = 'libx264'
    crf: int = VIDEO_CRF_DEFAULT
    preset: str = 'medium'
    audio_mode: Literal['aac', 'copy', 'none'] = 'copy'
    audio_bitrate: str | None = None
    max_long_edge: int = 0

    def __post_init__(self) -> None:
        """Literal は実行時に検証されないため、backend の入口で値を検証する。"""
        if not isinstance(self.enabled, bool):
            raise ValueError(f'enabled must be bool: {self.enabled!r}')
        if self.codec not in VIDEO_ALLOWED_CODECS:
            raise ValueError(f'unsupported video codec: {self.codec!r}')
        if isinstance(self.crf, bool) or not isinstance(self.crf, int):
            raise ValueError(f'crf must be int: {self.crf!r}')
        crf_min, crf_max = VIDEO_CRF_RANGE
        if not crf_min <= self.crf <= crf_max:
            raise ValueError(f'crf must be within {crf_min}-{crf_max}: {self.crf}')
        if self.preset not in VIDEO_ALLOWED_PRESETS:
            raise ValueError(f'unsupported video preset: {self.preset!r}')
        if self.audio_mode not in VIDEO_ALLOWED_AUDIO_MODES:
            raise ValueError(f'unsupported audio mode: {self.audio_mode!r}')
        if self.audio_bitrate is not None and (
            not isinstance(self.audio_bitrate, str) or not _AUDIO_BITRATE_PATTERN.match(self.audio_bitrate)
        ):
            raise ValueError(f'audio_bitrate must look like "128k": {self.audio_bitrate!r}')
        if isinstance(self.max_long_edge, bool) or not isinstance(self.max_long_edge, int) or self.max_long_edge < 0:
            raise ValueError(f'max_long_edge must be a non-negative int: {self.max_long_edge!r}')

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> 'VideoCompressionConfig':
        """dict から構築する。未知キーは typo を見逃さないよう明示的なエラーにする。"""
        if not isinstance(payload, Mapping):
            raise ValueError('video config must be a mapping')
        unknown = set(payload) - set(cls.__dataclass_fields__)
        if unknown:
            raise ValueError(f'unknown video config keys: {sorted(unknown)}')
        return cls(**payload)


class JobControl:
    """ジョブごとの停止要求と実行中サブプロセスを保持する実行制御オブジェクト。

    圧縮設定や永続化対象ではないため `CompressionRequest` の設定値には含めない。
    停止要求と動画サブプロセスの起動・登録は `launch_lock` で直列化し、競合を防ぐ。
    executor / 子プロセスの停止待ちは呼び出し側がロック外で行う。
    """

    def __init__(self) -> None:
        self.cancel_event = threading.Event()
        self.launch_lock = threading.Lock()
        self._active: set[subprocess.Popen] = set()

    @property
    def is_cancelled(self) -> bool:
        return self.cancel_event.is_set()

    def request_cancel(self) -> None:
        with self.launch_lock:
            self.cancel_event.set()

    def register(self, proc: subprocess.Popen) -> None:
        """実行中サブプロセスを登録する。`launch_lock` を保持した状態で呼ぶ。"""
        self._active.add(proc)

    def unregister(self, proc: subprocess.Popen) -> None:
        self._active.discard(proc)

    def snapshot(self) -> tuple[subprocess.Popen, ...]:
        return tuple(self._active)


@dataclass(frozen=True)
class CapabilityReport:
    """実行環境で利用可能な任意依存と外部ツールの検出結果。"""

    fitz_available: bool
    pikepdf_available: bool
    ghostscript_path: str | None
    pngquant_path: str | None
    ghostscript_source: ToolSource = 'unavailable'
    pngquant_source: ToolSource = 'unavailable'
    ffmpeg_path: str | None = None
    ffmpeg_source: ToolSource = 'unavailable'
    ffmpeg_encoders: frozenset[str] = frozenset()
    ffprobe_path: str | None = None
    ffprobe_source: ToolSource = 'unavailable'
    ffmpeg_detection_error: str | None = None
    ffprobe_detection_error: str | None = None

    @property
    def ghostscript_available(self) -> bool:
        """Ghostscript 実行可能ファイルが見つかったかを返す。"""
        return bool(self.ghostscript_path)

    @property
    def pngquant_available(self) -> bool:
        """pngquant 実行可能ファイルが見つかったかを返す。"""
        return bool(self.pngquant_path)

    @property
    def ffmpeg_available(self) -> bool:
        """ffmpeg が起動でき、H.264 エンコーダを持つかを返す。"""
        return bool(self.ffmpeg_path) and not self.ffmpeg_detection_error and 'libx264' in self.ffmpeg_encoders

    @property
    def ffprobe_available(self) -> bool:
        """ffprobe が起動できたかを返す。"""
        return bool(self.ffprobe_path) and not self.ffprobe_detection_error

    @property
    def video_available(self) -> bool:
        """動画圧縮に必要な ffmpeg / ffprobe が揃っているかを返す。"""
        return self.ffmpeg_available and self.ffprobe_available

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
    pdf_png_quality: int
    pdf_lossless_options: dict[str, Any] | None
    gs_preset: str
    gs_custom_dpi: int | None
    resize_config: dict[str, Any] | bool
    resize_width: int
    resize_height: int
    csv_enable: bool
    csv_path: str | None
    extract_zip: bool
    zip_output_enabled: bool
    debug_mode: bool
    copy_non_target_files: bool
    log_language: str
    video_config: VideoCompressionConfig | None = None

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
            'pdf_png_quality': self.pdf_png_quality,
            'pdf_lossless_options': self.pdf_lossless_options,
            'gs_preset': self.gs_preset,
            'gs_custom_dpi': self.gs_custom_dpi,
            'resize_enabled': self.resize_config,
            'resize_width': self.resize_width,
            'resize_height': self.resize_height,
            'csv_enable': self.csv_enable,
            'csv_path': self.csv_path,
            'extract_zip': self.extract_zip,
            'zip_output_enabled': self.zip_output_enabled,
            'debug_mode': self.debug_mode,
            'copy_non_target_files': self.copy_non_target_files,
            'video_config': self.video_config,
        }
