from __future__ import annotations

"""外部コマンド実行まわりの共通ユーティリティ。"""

from pathlib import Path

SUBPROCESS_ERROR_MAX_LENGTH = 240


def sanitize_subprocess_error(message: str, *paths: Path) -> str:
    """外部コマンドのエラーを短く整形し、内部パス露出を抑える。"""
    sanitized = ' '.join((message or '').split())
    for path in paths:
        path_str = str(path)
        if path_str:
            sanitized = sanitized.replace(path_str, path.name)
    return sanitized[:SUBPROCESS_ERROR_MAX_LENGTH]
