from __future__ import annotations

"""Tkinter frontend の起動順序を束ねる。

エントリポイントから見ると GUI 起動は 1 関数で十分だが、実際にはスプラッシュ、前面化、
起動音、mainloop 開始の順序が重要なので、このモジュールで順番を固定する。
"""

from tkinter import Label, PhotoImage, TclError, Toplevel

from frontend.settings import IMAGES_DIR, SOUNDS_DIR


_SPLASH_MIN_VISIBLE_MS = 700


def _build_startup_splash(app) -> Toplevel | None:
    """起動時スプラッシュを作成して返す。生成失敗時は None を返す。

    スプラッシュ表示は装飾だが、画像読込や Tk 制約で失敗しうるため、本体起動を止めずに
    任意機能として扱う。
    """
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
    """Tkinter UI の起動順序を集約する。

    スプラッシュ表示、本体ウィンドウの前面化、起動音再生をここでまとめることで、
    エントリポイント側は例外処理だけに集中できる。

    起動音やスプラッシュは見た目の改善要素だが、順序を誤ると「画面が出ない」「音だけ鳴る」
    といった誤解を招くため、ここで最小限の起動体験を保証する。
    """
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
        # 画像が一瞬で消えると起動失敗と誤認しやすいため、最低表示時間を設ける。
        app.after(_SPLASH_MIN_VISIBLE_MS, _show_main_window)

    startup_sound = SOUNDS_DIR / "open_window.wav"
    if app.play_startup_sound.get():
        app.after(120, lambda: play_sound(startup_sound))
    app.mainloop()
    return 0
