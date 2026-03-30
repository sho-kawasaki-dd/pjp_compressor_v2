from __future__ import annotations

"""画像圧縮関連機能のサービス層再公開。

現時点では単なる再公開だが、画像系だけ別ポリシーや計測を入れたくなったときに
呼び出し側を張り替えずに済むよう、service 境界を残している。
"""

from backend.core.image_utils import (
    compress_image_pillow,
    compress_png_pngquant,
)

__all__ = [
    'compress_image_pillow',
    'compress_png_pngquant',
]
