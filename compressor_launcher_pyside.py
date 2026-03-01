#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
compressor_launcher_pyside.py

PySide6 版 GUI のエントリポイント（起動スクリプト）。

背後の構成:
- GUI ロジック: `ui_pyside.py`
- 圧縮ロジック: `compressor_utils.py`
- 設定・定数: `configs.py`
- 効果音ユーティリティ: `sound_utils.py`

注意:
- 本ファイルは最小限の起動処理のみを行い、設定や検証は各モジュールに委譲する。
- PySide6 が必要です（`uv pip install PySide6` または `uv sync --extra qt`）。
- tkinter 版は `compressor_launcher.py` を使用してください。
"""
import os
import sys

from PySide6.QtWidgets import QApplication

from ui_pyside import App
from sound_utils import play_sound
from configs import SOUNDS_DIR

# ------------- アプリ起動 -------------
if __name__ == "__main__":
    qt_app = QApplication(sys.argv)
    window = App()
    window.show()
    play_sound(os.path.join(SOUNDS_DIR, 'open_window.wav'))
    sys.exit(qt_app.exec())
