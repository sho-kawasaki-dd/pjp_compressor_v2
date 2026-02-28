#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
compressor_launcher.py

アプリのエントリポイント（起動スクリプト）。
役割:
- GUI 実装を持つ `ui_app.App` をインスタンス化して `mainloop()` を開始する。
- 起動時に効果音（存在すれば）を再生し、ユーザーに起動を通知する。

背後の構成:
- GUI ロジック: `ui_app.py`
- 圧縮ロジック: `compressor_utils.py`
- 設定・定数: `configs.py`
- 効果音ユーティリティ: `sound_utils.py`

依存関係（主要）:
- Pillow（画像圧縮）
- pypdf / PyPDF2（PDF簡易圧縮の代替）
- Ghostscript（PDF高品質圧縮。推奨）
- pngquant（PNG 高圧縮。任意）
- tkinterdnd2（ドラッグ＆ドロップ。任意）

注意:
- 本ファイルは最小限の起動処理のみを行い、設定や検証は各モジュールに委譲する。
"""
import os

# ------------- アプリ本体インポート -------------
# App GUI は ui_app.py に移動しました
from ui_app import App, SOUNDS_DIR, play_sound

# 起動処理の流れ:
# 1. `App()` を作成（ウィンドウ・UI 構築）
# 2. 効果音があれば再生（非同期）
# 3. Tk の `mainloop()` を開始してイベントループに入る

# ------------- アプリ起動 -------------
if __name__ == "__main__":
    app = App()
    play_sound(os.path.join(SOUNDS_DIR, 'open_window.wav'))
    app.mainloop()