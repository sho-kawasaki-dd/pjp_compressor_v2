from __future__ import annotations

"""画像圧縮関連機能のサービス層再公開。"""

from backend.core.image_utils import (
    compress_image_pillow,
    compress_png_pngquant,
)

__all__ = [
    'compress_image_pillow',
    'compress_png_pngquant',
]
