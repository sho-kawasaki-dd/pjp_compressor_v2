#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
compressor_launcher.py

アプリのエントリポイント（起動スクリプト）。
役割:
- 引数または環境変数で GUI 実装（tkinter / PySide6）を切り替え可能。
- デフォルトは tkinter 版（`ui_tkinter.App`）。
- `--pyside` 引数または環境変数 `PJP_UI=pyside` で PySide6 版を使用。

背後の構成:
- GUI ロジック (tkinter): `ui_tkinter.py`
- GUI ロジック (PySide6): `ui_pyside.py`
- GUI ロジック (旧):      `ui_app.py`  （参照用に残存）
- 圧縮ロジック: `compressor_utils.py`
- 設定・定数: `configs.py`
- 効果音ユーティリティ: `sound_utils.py`

依存関係（主要）:
- Pillow（画像圧縮）
- PyMuPDF（PDF 非可逆圧縮）
- pikepdf（PDF 可逆圧縮）
- Ghostscript（PDF GS エンジン。推奨・任意）
- pngquant（PNG 高圧縮。任意）
- tkinterdnd2（tkinter 版 D&D。任意）
- PySide6（Qt 版 GUI。任意）

注意:
- 本ファイルは最小限の起動処理のみを行い、設定や検証は各モジュールに委譲する。
"""
import os
import sys

from sound_utils import play_sound
from configs import SOUNDS_DIR


def _select_ui() -> str:
    """引数／環境変数から使用する UI バックエンドを決定する。"""
    if '--pyside' in sys.argv:
        return 'pyside'
    if '--tkinter' in sys.argv:
        return 'tkinter'
    return os.environ.get('PJP_UI', 'tkinter').lower()


def _run_tkinter():
    """tkinter 版 GUI を起動する。"""
    from ui_tkinter import App
    app = App()
    play_sound(os.path.join(SOUNDS_DIR, 'open_window.wav'))
    app.mainloop()


def _run_pyside():
    """PySide6 版 GUI を起動する。"""
    from PySide6.QtWidgets import QApplication
    from ui_pyside import App

    qt_app = QApplication(sys.argv)
    window = App()
    window.show()
    play_sound(os.path.join(SOUNDS_DIR, 'open_window.wav'))
    sys.exit(qt_app.exec())


# ------------- アプリ起動 -------------
if __name__ == "__main__":
    ui = _select_ui()
    if ui == 'pyside':
        _run_pyside()
    else:
        _run_tkinter()