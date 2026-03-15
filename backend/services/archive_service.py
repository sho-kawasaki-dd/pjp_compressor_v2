from __future__ import annotations

"""ZIP 展開機能のサービス層再公開。

段階的な層分離のため、UI や orchestrator は core 実装へ直接依存せず、この窓口から
参照できるようにしている。
"""

from backend.core.archive_utils import extract_zip_archives

__all__ = ['extract_zip_archives']
