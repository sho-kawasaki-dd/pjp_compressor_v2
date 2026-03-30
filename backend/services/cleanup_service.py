from __future__ import annotations

"""クリーンアップ関連機能のサービス層再公開。

削除系 API は呼び出し境界を明示した方が安全なので、core への直接依存ではなく
service 名義の入口を残している。
"""

from backend.core.file_ops import cleanup_folder, count_target_files

__all__ = [
    'cleanup_folder',
    'count_target_files',
]
