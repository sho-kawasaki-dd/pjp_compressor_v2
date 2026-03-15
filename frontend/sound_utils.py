from __future__ import annotations

"""
sound_utils.py

pygame を使った簡易な効果音再生ユーティリティ。
目的:
- UI から非同期で効果音を再生できるようにする。
- pygame が無い環境でも致命的にならない設計（任意依存）。

注意:
- 本モジュールは pygame の初期化に失敗しても例外を外へ投げず、
    戻り値で状態を返し、警告表示などのUI責務は呼び出し側に委譲する。
"""

import sys
import threading
from pathlib import Path
from typing import Any, cast

# pygame は任意依存。未インストールでも動作可能にする。
try:
    import pygame
    PYGAME_AVAILABLE = True
except Exception:
    pygame = None
    PYGAME_AVAILABLE = False


PathLike = str | Path


# ------------- サウンド再生ユーティリティ -------------
def init_mixer() -> tuple[bool, str | None]:
    """pygame ミキサーの初期化。

    サウンドは補助機能なので、失敗時も例外ではなく戻り値で通知し、呼び出し側が
    警告表示の要否を決められるようにしている。
    """
    pygame_module = pygame
    if not PYGAME_AVAILABLE or pygame_module is None:
        return False, "pygame が利用できないため、サウンド再生は無効化されます。"
    try:
        # pre_init: 44100Hz, 16bit, ステレオ, バッファ512
        pygame_module.mixer.pre_init(44100, -16, 2, 512)
        pygame_module.mixer.init()
        return True, None
    except Exception:
        return False, "pygame ミキサーの初期化に失敗しました。サウンド再生は無効化されます。"


def play_sound(sound_file: PathLike) -> None:
    """
    指定されたサウンドファイルを非同期で再生。
    pygame を使用。ファイルが無い場合は無視。
    
        引数:
        - sound_file: 再生するファイルパス。存在しない場合は何もしない。
    
        実装詳細:
        - 別スレッドで `pygame.mixer.music` を使用して再生し、
            UI の応答性を保つ。
        
        - pygame が利用不可の場合や初期化に失敗している場合は何もしない。

        - アプリケーションが実行ファイル化されている場合にも対応。
    """
    pygame_module = pygame
    if not PYGAME_AVAILABLE or pygame_module is None:
        return
    sound_path = resource_path(sound_file)
    if not sound_path.exists():
        return

    def _play() -> None:
        try:
            # mixer.music は単一ストリーム前提だが、短い通知音用途には十分で実装が簡単。
            pygame_module.mixer.music.load(str(sound_path))
            pygame_module.mixer.music.play()
            while pygame_module.mixer.music.get_busy():
                pygame_module.time.Clock().tick(10)
        except Exception:
            pass

    threading.Thread(target=_play, daemon=True).start()


# ------------- PyInstaller リソースパスヘルパー -------------
def resource_path(relative_path: PathLike) -> Path:
    """PyInstaller がパッケージ化した時でも外部リソースにアクセス可能にする。"""
    path = Path(relative_path)
    if path.is_absolute():
        return path
    if hasattr(sys, '_MEIPASS'):
        return Path(cast(Any, sys)._MEIPASS) / path
    base_dir = Path(__file__).resolve().parent
    return base_dir / path
