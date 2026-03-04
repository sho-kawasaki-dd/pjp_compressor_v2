from __future__ import annotations


def human_readable(n):
    """バイト数を人間可読な単位へ変換する補助関数。"""
    if n < 0:
        return f"-{human_readable(-n)}"
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if abs(n) < 1024.0:
            return f"{n:.1f}{unit}"
        n /= 1024.0
    return f"{n:.1f}PB"
