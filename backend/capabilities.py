from __future__ import annotations

"""任意依存と外部ツールの利用可否を収集する。

UI 側は詳細な import 例外や PATH 探索を知らなくてよいように、ここで各依存の
検出結果を `CapabilityReport` にまとめる。

このモジュールの役割は「導入済みかどうか」を調べることだけで、未導入時の代替動作
そのものは持たない。後段はこの結果を見て UI 無効化やフォールバック経路を選ぶ。
"""

import importlib
import shutil

from .contracts import CapabilityReport


def _has_module(module_name: str) -> bool:
    """モジュール import 成否だけを見て利用可否を判定する。"""
    try:
        importlib.import_module(module_name)
        return True
    except Exception:
        return False


def _detect_ghostscript_path() -> str | None:
    """Windows と Unix 系の代表的な Ghostscript コマンド名を順に探索する。"""
    for cmd in ('gswin64c', 'gswin32c', 'gs'):
        path = shutil.which(cmd)
        if path:
            return path
    return None


def _detect_pngquant_path() -> str | None:
    """pngquant が PATH 上に存在する場合のみ実行パスを返す。"""
    return shutil.which('pngquant')


def detect_capabilities() -> CapabilityReport:
    """UI 初期化で使う能力レポートを構築する。

    起動時に一度まとめて検出しておくことで、個々の UI イベントや圧縮処理が毎回
    import や PATH 探索を繰り返さずに済む。依存が無いこと自体は異常ではないため、
    例外ではなく単なる状態として返す。
    """
    return CapabilityReport(
        fitz_available=_has_module('fitz'),
        pikepdf_available=_has_module('pikepdf'),
        ghostscript_path=_detect_ghostscript_path(),
        pngquant_path=_detect_pngquant_path(),
    )
