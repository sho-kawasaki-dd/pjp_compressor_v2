#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
compressor_launcher.py

tkinter 版 GUI のエントリポイント（起動スクリプト）。

背後の構成:
- GUI ロジック: `ui_tkinter.py`
- 圧縮ロジック: `compressor_utils.py`
- 設定・定数: `configs.py`
- 効果音ユーティリティ: `sound_utils.py`

注意:
- 本ファイルは最小限の起動処理のみを行い、設定や検証は各モジュールに委譲する。
- PySide6 版は `compressor_launcher_pyside.py` を使用してください。
"""
import os

from ui_tkinter import App
from sound_utils import play_sound
from configs import SOUNDS_DIR

# ------------- アプリ起動 -------------
if __name__ == "__main__":
    app = App()
    play_sound(os.path.join(SOUNDS_DIR, 'open_window.wav'))
    app.mainloop()