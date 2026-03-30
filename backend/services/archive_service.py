from __future__ import annotations

"""ZIP 展開機能のサービス層再公開。

段階的な層分離のため、UI や orchestrator は core 実装へ直接依存せず、この窓口から
参照できるようにしている。

この層は薄いが、将来 service 単位で認可、計測、差し替えを入れる余地を残すために
存在している。
"""

from backend.core.archive_utils import extract_zip_archives

__all__ = ['extract_zip_archives']
