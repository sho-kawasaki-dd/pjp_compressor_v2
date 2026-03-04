from __future__ import annotations

import os


def run_tkinter_app() -> int:
    """Tkinter UI の起動順序を集約する。"""
    from shared.configs import SOUNDS_DIR
    from frontend.sound_utils import play_sound
    from frontend.ui_tkinter import App

    app = App()
    startup_sound = os.path.join(SOUNDS_DIR, "open_window.wav")
    app.after(120, lambda: play_sound(startup_sound))
    app.mainloop()
    return 0
