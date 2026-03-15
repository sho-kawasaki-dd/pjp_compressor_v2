from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import pytest
from PIL import Image

from backend.contracts import CapabilityReport


@dataclass
class SamplePaths:
    input_dir: Path
    output_dir: Path
    csv_path: Path


@pytest.fixture
def sample_paths(tmp_path: Path) -> SamplePaths:
    input_dir = tmp_path / 'input'
    output_dir = tmp_path / 'output'
    input_dir.mkdir()
    output_dir.mkdir()
    return SamplePaths(
        input_dir=input_dir,
        output_dir=output_dir,
        csv_path=output_dir / 'compression.csv',
    )


@pytest.fixture
def image_factory() -> Callable[..., Path]:
    def _create_image(
        path: Path,
        *,
        size: tuple[int, int] = (320, 240),
        color: tuple[int, int, int] = (255, 0, 0),
        fmt: str = 'JPEG',
        quality: int = 95,
    ) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        image = Image.new('RGB', size, color=color)
        save_kwargs: dict[str, Any] = {}
        if fmt.upper() == 'JPEG':
            save_kwargs['quality'] = quality
        image.save(path, fmt, **save_kwargs)
        return path

    return _create_image


@pytest.fixture
def zip_factory() -> Callable[[Path, dict[str, bytes]], Path]:
    def _create_zip(path: Path, members: dict[str, bytes]) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for name, data in members.items():
                archive.writestr(name, data)
        return path

    return _create_zip


@pytest.fixture
def jpeg_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new('RGB', (240, 180), color=(12, 34, 56)).save(buffer, 'JPEG', quality=95)
    return buffer.getvalue()


@pytest.fixture
def png_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new('RGB', (240, 180), color=(56, 120, 220)).save(buffer, 'PNG')
    return buffer.getvalue()


@pytest.fixture
def capability_report() -> CapabilityReport:
    return CapabilityReport(
        fitz_available=True,
        pikepdf_available=True,
        ghostscript_path='C:/tools/gswin64c.exe',
        pngquant_path='C:/tools/pngquant.exe',
    )


@pytest.fixture
def tk_regression_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    pytest.importorskip('tkinterdnd2')

    import tkinter as tk
    import frontend.ui_tkinter as ui_module

    input_dir = tmp_path / 'input'
    output_dir = tmp_path / 'output'
    input_dir.mkdir()
    output_dir.mkdir()

    monkeypatch.setattr(ui_module, 'init_mixer', lambda: (True, None))
    monkeypatch.setattr(ui_module, 'detect_capabilities', lambda: CapabilityReport(True, True, None, None))
    monkeypatch.setattr(ui_module, 'get_default_dirs', lambda: (str(input_dir), str(output_dir)))
    monkeypatch.setattr(ui_module.messagebox, 'showwarning', lambda *args, **kwargs: None)
    monkeypatch.setattr(ui_module.messagebox, 'askquestion', lambda *args, **kwargs: 'no')

    try:
        app = ui_module.App()
        app.withdraw()
    except tk.TclError as exc:
        pytest.skip(f'Tk runtime unavailable: {exc}')

    try:
        yield app, input_dir, output_dir
    finally:
        try:
            app.destroy()
        except Exception:
            pass
