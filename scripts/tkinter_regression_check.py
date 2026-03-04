from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PIL import Image

from frontend.ui_tkinter import App
from frontend.ui_tkinter_mapper import build_compression_request
from backend.orchestrator.job_runner import run_compression_request
from tkinter import filedialog, messagebox


def wait_threads(app: App, timeout: float = 15.0) -> None:
    start = time.time()
    while time.time() - start < timeout:
        app.update()
        app.update_idletasks()
        alive = [t for t in app.threads if t.is_alive()]
        if not alive:
            return
        time.sleep(0.05)
    raise TimeoutError("worker thread timeout")


def main() -> None:
    root_tmp = Path(tempfile.mkdtemp(prefix="tkreg_", dir=str(Path.cwd())))
    try:
        input_dir = root_tmp / "input"
        output_dir = root_tmp / "output"
        input_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)

        jpg_path = input_dir / "sample.jpg"
        png_path = input_dir / "sample.png"
        Image.new("RGB", (320, 240), color=(255, 0, 0)).save(jpg_path, "JPEG", quality=95)
        Image.new("RGB", (320, 240), color=(0, 255, 0)).save(png_path, "PNG")

        app = App()
        app.withdraw()

        # patch dialogs
        askdirectory_orig = filedialog.askdirectory
        asksaveasfilename_orig = filedialog.asksaveasfilename
        askyesno_orig = messagebox.askyesno
        askquestion_orig = messagebox.askquestion
        showwarning_orig = messagebox.showwarning
        showerror_orig = messagebox.showerror

        try:
            filedialog.askdirectory = lambda initialdir=None: str(input_dir)
            app.choose_input()
            assert Path(app.input_dir.get()) == input_dir, "choose_input failed"

            filedialog.askdirectory = lambda initialdir=None: str(output_dir)
            app.choose_output()
            assert Path(app.output_dir.get()) == output_dir, "choose_output failed"

            # D&D
            event = SimpleNamespace(data="{" + str(jpg_path) + "}")
            app._on_drop_input(event)
            assert Path(app.input_dir.get()) == input_dir, "drop input failed"

            # CSV path chooser
            csv_file = output_dir / "check.csv"
            filedialog.asksaveasfilename = lambda **kwargs: str(csv_file)
            app._choose_csv_path()
            assert Path(app.csv_path.get()) == csv_file, "csv chooser failed"

            # request mapping check
            app.input_dir.set(str(input_dir))
            app.output_dir.set(str(output_dir))
            app.jpg_quality.set(75)
            app.png_quality.set(70)
            app.resize_enabled.set(True)
            app.resize_mode.set("long_edge")
            app.long_edge_value_str.set("256")
            app.csv_enable.set(True)
            app.csv_path.set(str(csv_file))
            app.extract_zip.set(False)

            request = build_compression_request(app).request
            captured: list[object] = []
            run_compression_request(request=request, event_callback=lambda e: captured.append(e))

            out_jpg = output_dir / "sample.jpg"
            out_png = output_dir / "sample.png"
            assert out_jpg.exists() and out_png.exists(), "compressed outputs missing"
            assert any(getattr(evt, "kind", "") == "progress" for evt in captured), "progress event missing"
            assert any(getattr(evt, "kind", "") == "stats" for evt in captured), "stats event missing"

            # start_compress wiring check (without real backend thread side effects)
            import frontend.ui_tkinter_controller as controller_module

            original_runner = controller_module.run_compression_request
            try:
                def fake_runner(request, event_callback):
                    event_callback(SimpleNamespace(kind="log", message="dummy"))
                    event_callback(SimpleNamespace(kind="progress", current=1, total=1))
                    event_callback(SimpleNamespace(kind="stats", orig_total=1, out_total=1, saved=0, saved_pct=0.0))

                controller_module.run_compression_request = fake_runner

                # patch UI-thread-sensitive methods during background callback
                app.log = lambda msg: None
                app.update_progress = lambda current, total: None
                app.update_stats = lambda a, b, c, d: None
                app._set_status = lambda text: None

                app.start_compress()
                wait_threads(app)
            finally:
                controller_module.run_compression_request = original_runner

            # cleanup check
            messagebox.askyesno = lambda *args, **kwargs: True
            messagebox.showerror = lambda *args, **kwargs: None
            app.cleanup_output()
            wait_threads(app)
            assert not out_jpg.exists() and not out_png.exists(), "cleanup_output failed"

            # overlap guard
            app.input_dir.set(str(input_dir))
            app.output_dir.set(str(input_dir))
            messagebox.showwarning = lambda *args, **kwargs: None
            app._validate_and_fix_dirs()
            assert app.input_dir.get() != app.output_dir.get(), "overlap guard failed"

            print("manual-regression-simulated: PASS")
        finally:
            filedialog.askdirectory = askdirectory_orig
            filedialog.asksaveasfilename = asksaveasfilename_orig
            messagebox.askyesno = askyesno_orig
            messagebox.askquestion = askquestion_orig
            messagebox.showwarning = showwarning_orig
            messagebox.showerror = showerror_orig
            try:
                app.destroy()
            except Exception:
                pass
    finally:
        shutil.rmtree(root_tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
