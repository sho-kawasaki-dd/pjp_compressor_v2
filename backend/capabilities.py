from __future__ import annotations

import importlib
import shutil

from .contracts import CapabilityReport


def _has_module(module_name: str) -> bool:
    try:
        importlib.import_module(module_name)
        return True
    except Exception:
        return False


def _detect_ghostscript_path() -> str | None:
    for cmd in ('gswin64c', 'gswin32c', 'gs'):
        path = shutil.which(cmd)
        if path:
            return path
    return None


def _detect_pngquant_path() -> str | None:
    return shutil.which('pngquant')


def detect_capabilities() -> CapabilityReport:
    return CapabilityReport(
        fitz_available=_has_module('fitz'),
        pikepdf_available=_has_module('pikepdf'),
        ghostscript_path=_detect_ghostscript_path(),
        pngquant_path=_detect_pngquant_path(),
    )
