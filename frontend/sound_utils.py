import os
import sys
import threading
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

# pygame は任意依存。未インストールでも動作可能にする。
try:
    import pygame
    PYGAME_AVAILABLE = True
except Exception:
    pygame = None
    PYGAME_AVAILABLE = False

# ------------- サウンド再生ユーティリティ -------------
def init_mixer():
    """pygame ミキサーの初期化。"""
    if not PYGAME_AVAILABLE:
        return False, "pygame が利用できないため、サウンド再生は無効化されます。"
    try:
        # pre_init: 44100Hz, 16bit, ステレオ, バッファ512
        pygame.mixer.pre_init(44100, -16, 2, 512)
        pygame.mixer.init()
        return True, None
    except Exception:
        return False, "pygame ミキサーの初期化に失敗しました。サウンド再生は無効化されます。"
def play_sound(sound_file):
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
    if not PYGAME_AVAILABLE:
        return
    if not os.path.exists(resource_path(sound_file)):
        return

    def _play():
        try:
            pygame.mixer.music.load(resource_path(sound_file))
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                pygame.time.Clock().tick(10)
        except Exception:
            pass

    threading.Thread(target=_play, daemon=True).start()

# ------------- PyInstaller リソースパスヘルパー -------------
def resource_path(relative_path):
    """PyInstallerがパッケージ化した時でも外部リソースにアクセス可能にするヘルパー関数"""
    if os.path.isabs(relative_path):
        return relative_path
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    base_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_dir, relative_path)
