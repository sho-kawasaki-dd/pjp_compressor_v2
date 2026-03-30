from __future__ import annotations

"""任意依存の検出順序と劣化起動判定を確認する unit test。"""

import pytest

from backend import capabilities


pytestmark = pytest.mark.unit


def test_detect_ghostscript_path_prefers_windows_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    lookup = {
        'gswin64c': 'C:/Ghostscript/bin/gswin64c.exe',
        'gswin32c': None,
        'gs': 'C:/Ghostscript/bin/gs.exe',
    }
    monkeypatch.setattr(capabilities.shutil, 'which', lookup.get)

    assert capabilities._detect_ghostscript_path() == 'C:/Ghostscript/bin/gswin64c.exe'


def test_detect_capabilities_handles_missing_optional_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_import(name: str):
        if name == 'fitz':
            return object()
        raise ImportError(name)

    monkeypatch.setattr(capabilities.importlib, 'import_module', fake_import)
    monkeypatch.setattr(capabilities.shutil, 'which', lambda name: 'C:/tools/pngquant.exe' if name == 'pngquant' else None)

    report = capabilities.detect_capabilities()

    assert report.fitz_available is True
    assert report.pikepdf_available is False
    assert report.ghostscript_available is False
    assert report.pngquant_available is True
    assert report.native_pdf_available is True
