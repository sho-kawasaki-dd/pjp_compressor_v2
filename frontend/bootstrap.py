from __future__ import annotations

from tkinter import Label, PhotoImage, TclError, Toplevel


_SPLASH_MIN_VISIBLE_MS = 700


def _build_startup_splash(app) -> Toplevel | None:
    """起動時スプラッシュを作成して返す。生成失敗時は None を返す。"""
    from shared.configs import IMAGES_DIR

    splash_path = IMAGES_DIR / "pjp_compressor_splash.png"
    if not splash_path.exists():
        return None

    try:
        splash_image = PhotoImage(file=str(splash_path))
    except TclError:
        return None

    splash = Toplevel(app)
    splash.overrideredirect(True)
    try:
        splash.attributes("-topmost", True)
    except TclError:
        pass

    label = Label(splash, image=splash_image, borderwidth=0, highlightthickness=0)
    label.pack()

    # PhotoImage が GC されると表示が消えるためウィンドウ側で参照を保持する。
    splash._splash_image = splash_image  # type: ignore[attr-defined]

    splash.update_idletasks()
    width = splash.winfo_width() or splash_image.width()
    height = splash.winfo_height() or splash_image.height()
    x = max((splash.winfo_screenwidth() - width) // 2, 0)
    y = max((splash.winfo_screenheight() - height) // 2, 0)
    splash.geometry(f"{width}x{height}+{x}+{y}")
    # メインループ開始直後に破棄されても見えるよう、ここで一度描画を確定する。
    splash.update()
    return splash


def run_tkinter_app() -> int:
    """Tkinter UI の起動順序を集約する。"""
    from shared.configs import SOUNDS_DIR
    from frontend.sound_utils import play_sound
    from frontend.ui_tkinter import App

    app = App()

    splash = _build_startup_splash(app)

    def _show_main_window() -> None:
        if splash is not None:
            try:
                if splash.winfo_exists():
                    splash.destroy()
            except TclError:
                pass

        app.lift()
        try:
            app.focus_force()
        except TclError:
            pass

    if splash is None:
        _show_main_window()
    else:
        app.after(_SPLASH_MIN_VISIBLE_MS, _show_main_window)

    startup_sound = SOUNDS_DIR / "open_window.wav"
    app.after(120, lambda: play_sound(startup_sound))
    app.mainloop()
    return 0
