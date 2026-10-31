from __future__ import annotations

"""任意依存と外部ツールの利用可否を収集する。

UI 側は詳細な import 例外や PATH 探索を知らなくてよいように、ここで各依存の
検出結果を `CapabilityReport` にまとめる。

このモジュールの役割は「導入済みかどうか」を調べることだけで、未導入時の代替動作
そのものは持たない。後段はこの結果を見て UI 無効化やフォールバック経路を選ぶ。
"""

import functools
import importlib
import subprocess
import sys
from typing import NamedTuple

from .contracts import CapabilityReport
from shared.runtime_paths import (
    ToolSource,
    resolve_ffmpeg_executable,
    resolve_ffprobe_executable,
    resolve_ghostscript_executable,
    resolve_pngquant_executable,
)

TOOL_PROBE_TIMEOUT_SECONDS = 10
_TRACKED_ENCODERS = ('libx264', 'libx265', 'aac')
_ERROR_DETAIL_MAX_LENGTH = 240


class FfmpegDetection(NamedTuple):
    """ffmpeg の解決結果とエンコーダ検出結果。失敗時は理由を保持する。"""

    path: str | None
    source: ToolSource
    encoders: frozenset[str]
    error: str | None


class FfprobeDetection(NamedTuple):
    """ffprobe の解決結果と起動確認結果。失敗時は理由を保持する。"""

    path: str | None
    source: ToolSource
    error: str | None


def _has_module(module_name: str) -> bool:
    """モジュール import 成否だけを見て利用可否を判定する。"""
    try:
        importlib.import_module(module_name)
        return True
    except Exception:
        return False


def _sanitize_probe_error(message: str, tool_path: str) -> str:
    """検出コマンドのエラーを短く整形し、内部パス露出を抑える。"""
    sanitized = ' '.join((message or '').split())
    if tool_path:
        sanitized = sanitized.replace(tool_path, tool_path.replace('\\', '/').rsplit('/', 1)[-1])
    return sanitized[:_ERROR_DETAIL_MAX_LENGTH]


def _run_tool_probe(tool_path: str, args: list[str]) -> subprocess.CompletedProcess:
    """外部ツールの検出コマンドをウィンドウなしで実行する。"""
    kwargs: dict = {}
    if sys.platform == 'win32':
        kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
    return subprocess.run(
        [tool_path, *args],
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        timeout=TOOL_PROBE_TIMEOUT_SECONDS,
        **kwargs,
    )


def _parse_encoder_names(output: str) -> frozenset[str]:
    """`ffmpeg -encoders` の出力から追跡対象エンコーダ名を抽出する。"""
    found: set[str] = set()
    for line in output.splitlines():
        fields = line.split()
        # 行形式は `<flags> <name> <description>`。flags は V....D のような 6 文字。
        if len(fields) >= 2 and len(fields[0]) == 6 and fields[1] in _TRACKED_ENCODERS:
            found.add(fields[1])
    return frozenset(found)


def _detect_ghostscript():
    """Ghostscript の実行パスと供給元を解決する。"""
    return resolve_ghostscript_executable()


def _detect_ghostscript_path() -> str | None:
    """Ghostscript 実行パスだけを返す互換ラッパー。"""
    return _detect_ghostscript().path


def _detect_pngquant():
    """pngquant の実行パスと供給元を解決する。"""
    return resolve_pngquant_executable()


def _detect_pngquant_path() -> str | None:
    """pngquant 実行パスだけを返す互換ラッパー。"""
    return _detect_pngquant().path


@functools.lru_cache(maxsize=1)
def _detect_ffmpeg() -> FfmpegDetection:
    """ffmpeg を解決し、`-encoders` を1回だけ実行してエンコーダ有無を収集する。

    結果はアプリ起動中キャッシュされる。PATH やビルドを変更した場合は再起動が必要で、
    テストでは `cache_clear()` で初期化する。
    """
    resolution = resolve_ffmpeg_executable()
    if not resolution.path:
        return FfmpegDetection(None, resolution.source, frozenset(), None)
    try:
        result = _run_tool_probe(resolution.path, ['-hide_banner', '-encoders'])
    except subprocess.TimeoutExpired:
        return FfmpegDetection(resolution.path, resolution.source, frozenset(), 'ffmpeg -encoders timed out')
    except OSError as exc:
        return FfmpegDetection(
            resolution.path, resolution.source, frozenset(),
            _sanitize_probe_error(f'ffmpeg failed to start: {exc}', resolution.path),
        )
    if result.returncode != 0:
        detail = _sanitize_probe_error(result.stderr, resolution.path) or f'ffmpeg_exit_{result.returncode}'
        return FfmpegDetection(resolution.path, resolution.source, frozenset(), detail)
    return FfmpegDetection(resolution.path, resolution.source, _parse_encoder_names(result.stdout), None)


@functools.lru_cache(maxsize=1)
def _detect_ffprobe() -> FfprobeDetection:
    """ffprobe を解決し、`-version` で起動可否を確認する。未検出と起動失敗を区別する。"""
    resolution = resolve_ffprobe_executable()
    if not resolution.path:
        return FfprobeDetection(None, resolution.source, None)
    try:
        result = _run_tool_probe(resolution.path, ['-version'])
    except subprocess.TimeoutExpired:
        return FfprobeDetection(resolution.path, resolution.source, 'ffprobe -version timed out')
    except OSError as exc:
        return FfprobeDetection(
            resolution.path, resolution.source,
            _sanitize_probe_error(f'ffprobe failed to start: {exc}', resolution.path),
        )
    if result.returncode != 0:
        detail = _sanitize_probe_error(result.stderr, resolution.path) or f'ffprobe_exit_{result.returncode}'
        return FfprobeDetection(resolution.path, resolution.source, detail)
    return FfprobeDetection(resolution.path, resolution.source, None)


def clear_video_tool_cache() -> None:
    """動画ツール検出キャッシュを破棄する（主にテスト用）。"""
    _detect_ffmpeg.cache_clear()
    _detect_ffprobe.cache_clear()


def detect_capabilities() -> CapabilityReport:
    """UI 初期化で使う能力レポートを構築する。

    起動時に一度まとめて検出しておくことで、個々の UI イベントや圧縮処理が毎回
    import や PATH 探索を繰り返さずに済む。依存が無いこと自体は異常ではないため、
    例外ではなく単なる状態として返す。ジョブ開始ごとにも呼ばれるため、動画ツールの
    検出結果はキャッシュされる。
    """
    ghostscript = _detect_ghostscript()
    pngquant = _detect_pngquant()
    ffmpeg = _detect_ffmpeg()
    ffprobe = _detect_ffprobe()
    return CapabilityReport(
        fitz_available=_has_module('fitz'),
        pikepdf_available=_has_module('pikepdf'),
        ghostscript_path=ghostscript.path,
        pngquant_path=pngquant.path,
        ghostscript_source=ghostscript.source,
        pngquant_source=pngquant.source,
        ffmpeg_path=ffmpeg.path,
        ffmpeg_source=ffmpeg.source,
        ffmpeg_encoders=ffmpeg.encoders,
        ffprobe_path=ffprobe.path,
        ffprobe_source=ffprobe.source,
        ffmpeg_detection_error=ffmpeg.error,
        ffprobe_detection_error=ffprobe.error,
    )
