#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tkinter + ttk ベースの GUI ファサードを提供する。

圧縮ロジックは backend へ委譲し、このモジュールは mixin 合成で 1 つの `App` として
UI を束ねる。ユーザー操作、起動時副作用、既定値解決、能力検出の順序を固定することで、
新規参加者が「どこで何が起きるか」を追いやすくしている。

レイアウト構成:
- メイン画面全体を縦スクロール可能なコンテナ
    - フォルダ選択行（D&D 対応）
    - タブ（圧縮設定 / ログ）
    - 圧縮設定: PDF操作エリア / 画像操作エリア（圧縮・リサイズ・出力）
    - ログ: 統計 / 進捗 / ログテキスト
    - アクションボタン行

設計ポイント:
- 処理はスレッドで非同期化し、UI の応答性を保持。
- PDF エンジン（ネイティブ / Ghostscript）を UI から選択可能。
- エンジン未検出時は対応ラジオを自動的に無効化。
- ドラッグ＆ドロップは `tkinterdnd2` を必須依存として有効化。
"""
import os
import threading
from pathlib import Path
from tkinter import messagebox
from tkinterdnd2 import DND_FILES, TkinterDnD

from frontend.sound_utils import init_mixer, play_sound
from backend.capabilities import detect_capabilities
from frontend.ui_tkinter_controller import TkUiControllerMixin
from frontend.settings import (
    APP_DEFAULT_INPUT_DIR,
    APP_DEFAULT_OUTPUT_DIR,
    APP_DEFAULT_WINDOW_SIZE,
    IMAGES_DIR,
    SOUNDS_DIR,
    load_app_settings,
)
from frontend.ui_tkinter_state import TkUiStateMixin
from frontend.ui_tkinter_view import TkUiViewMixin

# ------------- 高DPI対応（Windowsのみ） -------------
if os.name == 'nt':
    import ctypes
    # Windows の高 DPI 環境では座標系がぼやけやすいため、起動時に明示設定しておく。
    ctypes.windll.shcore.SetProcessDpiAwareness(1)


def get_default_dirs():
    """デフォルト入出力フォルダを返す。Windows では Desktop 配下を優先する。

        初回利用者が場所を見失いにくいよう Windows では Desktop を優先するが、勝手に
        作成すると驚かせるため、未作成時は確認付きで生成する。
    """
    default_input = APP_DEFAULT_INPUT_DIR
    default_output = APP_DEFAULT_OUTPUT_DIR

    if os.name != 'nt':
        return str(default_input), str(default_output)

    desktop = Path.home() / 'Desktop'
    input_dir = desktop / 'これから圧縮'
    output_dir = desktop / '圧縮済みファイル'

    missing_targets = []
    if not input_dir.exists():
        missing_targets.append(('これから圧縮', input_dir))
    if not output_dir.exists():
        missing_targets.append(('圧縮済みファイル', output_dir))

    if missing_targets:
        app_settings = load_app_settings()
        missing_names = '」「'.join(name for name, _ in missing_targets)
        if app_settings['play_startup_sound']:
            play_sound(SOUNDS_DIR / 'notice.wav')
        if messagebox.askquestion(
            "Desktopフォルダ作成",
            f"デスクトップに「{missing_names}」フォルダを作成してよいですか？"
        ) == 'yes':
            # ユーザーが意図しない場所へ出力しないよう、自動作成前に必ず確認する。
            for _, path in missing_targets:
                try:
                    path.mkdir(parents=True, exist_ok=True)
                except Exception:
                    pass

    if input_dir.exists():
        default_input = input_dir
    if output_dir.exists():
        default_output = output_dir

    return str(default_input), str(default_output)


class App(
    TkUiStateMixin,
    TkUiViewMixin,
    TkUiControllerMixin,
    TkinterDnD.Tk,
):
    """PDF&JPEG&PNG 圧縮アプリ（フォルダ一括）のメインウィンドウクラス (tkinter 版)。

    `TkUiStateMixin`、`TkUiViewMixin`、`TkUiControllerMixin` を合成し、状態・見た目・
    イベント制御を 1 クラスへ統合する。責務は分離しつつ、実行時には 1 つの Tk root と
    して扱いたいのでこの形を取っている。
    """

    dnd_available = True
    DND_FILES = DND_FILES

    # ------------------------------------------------------------------
    #  コンストラクタ
    # ------------------------------------------------------------------
    def __init__(self):
        super().__init__()
        self._set_window_icon()
        self.title("PDF&JPEG&PNG 圧縮アプリ（フォルダ一括） v2")
        self.geometry(self._expanded_window_size(APP_DEFAULT_WINDOW_SIZE, 60, 140))

        self.threads: list[threading.Thread] = []
        self.app_settings = load_app_settings()
        # 起動時副作用、既定値決定、能力検出、UI 構築の順で進めると責務が追いやすい。
        self._initialize_runtime_side_effects()
        self.default_input_dir, self.default_output_dir = self._resolve_default_dirs()
        self.capabilities = detect_capabilities()

        self.initialize_ui_state()
        self.build_layout()

        # ── 初期状態更新 ──
        self._refresh_pdf_engine_status()
        self._update_pdf_controls()
        self._update_png_engine_labels()
        self._update_resize_controls()

        self.protocol("WM_DELETE_WINDOW", self.on_exit)

    def _set_window_icon(self):
        """ウィンドウアイコンを設定する。失敗時は既定アイコンのまま継続する。"""
        icon_path = IMAGES_DIR / "pjp_compressor_icon.ico"
        if not icon_path.exists():
            return
        try:
            self.iconbitmap(default=str(icon_path))
        except Exception:
            pass

    def _initialize_runtime_side_effects(self):
        """サウンド初期化と既定フォルダの作成をまとめて行う。

        これらは UI 構築前に 1 回だけ済ませたい副作用なので、`__init__` の先頭寄りへ
        まとめている。失敗しても本体起動は継続し、警告だけを UI へ返す。
        """
        mixer_ok, mixer_message = init_mixer()
        APP_DEFAULT_INPUT_DIR.mkdir(parents=True, exist_ok=True)
        APP_DEFAULT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        if not mixer_ok and mixer_message:
            try:
                messagebox.showwarning("警告", mixer_message)
            except Exception:
                pass

    def _resolve_default_dirs(self):
        """既定入出力フォルダ解決の失敗時に安全なフォールバックを返す。

        Desktop 解決やダイアログ確認に失敗してもアプリ全体を止めないため、最後は
        プロジェクト既定ディレクトリへ戻す。
        """
        try:
            return get_default_dirs()
        except Exception:
            return str(APP_DEFAULT_INPUT_DIR), str(APP_DEFAULT_OUTPUT_DIR)

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
