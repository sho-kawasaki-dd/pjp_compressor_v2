from __future__ import annotations

"""任意依存の検出順序と劣化起動判定を確認する unit test。"""

from pathlib import Path

import pytest

from backend import capabilities
from shared import runtime_paths


pytestmark = pytest.mark.unit


def test_detect_ghostscript_prefers_system_over_bundled(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    bundled = tmp_path / 'vendor' / 'Ghostscript-windows' / 'bin' / 'gswin64c.exe'
    bundled.parent.mkdir(parents=True)
    bundled.write_text('stub', encoding='utf-8')

    lookup = {
        'gswin64c': 'C:/Ghostscript/bin/gswin64c.exe',
        'gswin32c': None,
        'gs': 'C:/Ghostscript/bin/gs.exe',
    }
    monkeypatch.setattr(runtime_paths, 'APP_BASE_DIR', tmp_path)
    monkeypatch.setattr(runtime_paths.shutil, 'which', lookup.get)

    resolution = capabilities._detect_ghostscript()

    assert resolution.path == 'C:/Ghostscript/bin/gswin64c.exe'
    assert resolution.source == 'system'


def test_detect_pngquant_falls_back_to_bundled(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    bundled = tmp_path / 'vendor' / 'pngquant-windows' / 'pngquant' / 'pngquant.exe'
    bundled.parent.mkdir(parents=True)
    bundled.write_text('stub', encoding='utf-8')

    monkeypatch.setattr(runtime_paths, 'APP_BASE_DIR', tmp_path)
    monkeypatch.setattr(runtime_paths.shutil, 'which', lambda _name: None)

    resolution = capabilities._detect_pngquant()

    assert resolution.path == str(bundled.resolve())
    assert resolution.source == 'bundled'


def test_detect_capabilities_handles_missing_optional_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_import(name: str):
        if name == 'fitz':
            return object()
        raise ImportError(name)

    monkeypatch.setattr(capabilities.importlib, 'import_module', fake_import)
    monkeypatch.setattr(runtime_paths.shutil, 'which', lambda name: 'C:/tools/pngquant.exe' if name == 'pngquant' else None)
    monkeypatch.setattr(runtime_paths, '_resolve_bundled_executable', lambda _candidates: None)

    report = capabilities.detect_capabilities()

    assert report.fitz_available is True
    assert report.pikepdf_available is False
    assert report.ghostscript_available is False
    assert report.pngquant_available is True
    assert report.native_pdf_available is True
    assert report.ghostscript_source == 'unavailable'
    assert report.pngquant_source == 'system'
