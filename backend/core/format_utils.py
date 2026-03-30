from __future__ import annotations

"""表示用フォーマットの小さな補助関数を置く。

見た目上は小さい補助だが、ログ・統計・テスト期待値の単位表現を揃えるために
共通化している。表示揺れを防ぐことが、このモジュールの主目的である。
"""


def human_readable(n):
    """バイト数を人間可読な単位へ変換する補助関数。

    ログと統計表示の双方で使うため、単位変換ルールを一箇所に固定して
    画面表示と CSV 補助ログの表現差を減らす。
    """
    if n < 0:
        return f"-{human_readable(-n)}"
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if abs(n) < 1024.0:
            return f"{n:.1f}{unit}"
        n /= 1024.0
    return f"{n:.1f}PB"
