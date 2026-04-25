from __future__ import annotations

"""任意依存と外部ツールの利用可否を収集する。

UI 側は詳細な import 例外や PATH 探索を知らなくてよいように、ここで各依存の
検出結果を `CapabilityReport` にまとめる。

このモジュールの役割は「導入済みかどうか」を調べることだけで、未導入時の代替動作
そのものは持たない。後段はこの結果を見て UI 無効化やフォールバック経路を選ぶ。
"""

import importlib

from .contracts import CapabilityReport
from shared.runtime_paths import resolve_ghostscript_executable, resolve_pngquant_executable


def _has_module(module_name: str) -> bool:
    """モジュール import 成否だけを見て利用可否を判定する。"""
    try:
        importlib.import_module(module_name)
        return True
    except Exception:
        return False


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


def detect_capabilities() -> CapabilityReport:
    """UI 初期化で使う能力レポートを構築する。

    起動時に一度まとめて検出しておくことで、個々の UI イベントや圧縮処理が毎回
    import や PATH 探索を繰り返さずに済む。依存が無いこと自体は異常ではないため、
    例外ではなく単なる状態として返す。
    """
    ghostscript = _detect_ghostscript()
    pngquant = _detect_pngquant()
    return CapabilityReport(
        fitz_available=_has_module('fitz'),
        pikepdf_available=_has_module('pikepdf'),
        ghostscript_path=ghostscript.path,
        pngquant_path=pngquant.path,
        ghostscript_source=ghostscript.source,
        pngquant_source=pngquant.source,
    )
