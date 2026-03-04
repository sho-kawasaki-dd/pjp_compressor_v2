#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ui_tkinter.py

tkinter + ttk ベースの GUI を提供するモジュール。圧縮ロジックは `compressor_utils`
に委譲し、ユーザー操作（フォルダ選択、PDF エンジン切替、品質設定、プリセット、
進捗表示、CSV ログの有効化など）を受け付ける。

レイアウト構成:
- フォルダ選択行（常時表示、D&D 対応）
- タブ（圧縮設定 / ログ）
    - 圧縮設定: PDF操作エリア / 画像操作エリア（圧縮・リサイズ・出力）
    - ログ: 統計 / ログテキスト
- 進捗行（常時表示）: 状態文言 / プログレスバー
- アクションボタン行（常時表示）

設計ポイント:
- 処理はスレッドで非同期化し、UI の応答性を保持。
- PDF エンジン（ネイティブ / GhostScript）を UI から選択可能。
- エンジン未検出時は対応ラジオを自動的に無効化。
- ドラッグ＆ドロップは `tkinterdnd2` を必須依存として有効化。
"""
import os
import threading
from tkinter import messagebox
from tkinterdnd2 import DND_FILES, TkinterDnD

from frontend.sound_utils import init_mixer, play_sound
from backend.capabilities import detect_capabilities
from frontend.ui_tkinter_controller import TkUiControllerMixin
from frontend.ui_tkinter_state import TkUiStateMixin
from frontend.ui_tkinter_view import TkUiViewMixin
from shared.configs import (
    APP_DEFAULT_INPUT_DIR,
    APP_DEFAULT_OUTPUT_DIR,
    APP_DEFAULT_WINDOW_SIZE,
    SOUNDS_DIR,
)

# ------------- 高DPI対応（Windowsのみ） -------------
if os.name == 'nt':
    import ctypes
    ctypes.windll.shcore.SetProcessDpiAwareness(1)


def get_default_dirs():
    """デフォルト入出力フォルダを返す。Windows では Desktop 配下を優先する。"""
    default_input = APP_DEFAULT_INPUT_DIR
    default_output = APP_DEFAULT_OUTPUT_DIR

    if os.name != 'nt':
        return default_input, default_output

    user_profile = os.environ.get('USERPROFILE')
    if not user_profile:
        return default_input, default_output

    desktop = os.path.join(user_profile, 'Desktop')
    input_dir = os.path.join(desktop, 'これから圧縮')
    output_dir = os.path.join(desktop, '圧縮済みファイル')

    missing_targets = []
    if not os.path.exists(input_dir):
        missing_targets.append(('これから圧縮', input_dir))
    if not os.path.exists(output_dir):
        missing_targets.append(('圧縮済みファイル', output_dir))

    if missing_targets:
        missing_names = '」「'.join(name for name, _ in missing_targets)
        play_sound(os.path.join(SOUNDS_DIR, 'notice.wav'))
        if messagebox.askquestion(
            "Desktopフォルダ作成",
            f"デスクトップに「{missing_names}」フォルダを作成してよいですか？"
        ) == 'yes':
            for _, path in missing_targets:
                try:
                    os.makedirs(path, exist_ok=True)
                except Exception:
                    pass

    if os.path.exists(input_dir):
        default_input = input_dir
    if os.path.exists(output_dir):
        default_output = output_dir

    return default_input, default_output


class App(
    TkUiStateMixin,
    TkUiViewMixin,
    TkUiControllerMixin,
    TkinterDnD.Tk,
):
    """フォルダ一括圧縮アプリケーションのメインウィンドウクラス (tkinter 版)。"""

    dnd_available = True
    DND_FILES = DND_FILES

    # ------------------------------------------------------------------
    #  コンストラクタ
    # ------------------------------------------------------------------
    def __init__(self):
        super().__init__()
        self.title("フォルダ一括圧縮アプリ v2")
        self.geometry(self._expanded_window_size(APP_DEFAULT_WINDOW_SIZE, 60, 120))

        self.threads: list[threading.Thread] = []
        self._initialize_runtime_side_effects()
        self.default_input_dir, self.default_output_dir = self._resolve_default_dirs()
        self.capabilities = detect_capabilities()

        self.initialize_ui_state()
        self.build_layout()

        # ── 初期状態更新 ──
        self._refresh_pdf_engine_status()
        self._update_pdf_controls()
        self._update_resize_controls()

        self.protocol("WM_DELETE_WINDOW", self.on_exit)

    def _initialize_runtime_side_effects(self):
        mixer_ok, mixer_message = init_mixer()
        os.makedirs(APP_DEFAULT_INPUT_DIR, exist_ok=True)
        os.makedirs(APP_DEFAULT_OUTPUT_DIR, exist_ok=True)
        if not mixer_ok and mixer_message:
            try:
                messagebox.showwarning("警告", mixer_message)
            except Exception:
                pass

    def _resolve_default_dirs(self):
        try:
            return get_default_dirs()
        except Exception:
            return APP_DEFAULT_INPUT_DIR, APP_DEFAULT_OUTPUT_DIR

    # ==================================================================
    #  ヘルパー
    # ==================================================================

    @staticmethod
    def _expanded_window_size(base_size: str, add_width: int, add_height: int) -> str:
        """既定ウィンドウサイズ文字列を少し拡張した geometry 文字列へ変換する。"""
        try:
            size_part = base_size.split('+', 1)[0]
            w_str, h_str = size_part.lower().split('x', 1)
            width = max(640, int(w_str) + int(add_width))
            height = max(520, int(h_str) + int(add_height))
            return f"{width}x{height}"
        except Exception:
            return "1200x980"

    @staticmethod
    def _to_non_negative_int(s: str) -> int:
        """文字列を非負整数へ変換。空欄や非数値は 0 を返す。"""
        try:
            val = int(float(s.strip()))
            return val if val >= 0 else 0
        except Exception:
            return 0
