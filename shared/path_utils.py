from __future__ import annotations

"""UI と backend が共用するパス判定ユーティリティ。"""

from pathlib import Path


def paths_overlap(a: str | Path, b: str | Path) -> bool:
    """同一または内包関係のパスかを判定する。解決できない場合は False を返す。"""
    try:
        pa = Path(a).resolve()
        pb = Path(b).resolve()
        return pa == pb or pa in pb.parents or pb in pa.parents
    except Exception:
        return False
