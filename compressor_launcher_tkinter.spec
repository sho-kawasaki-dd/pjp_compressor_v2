# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


tkdnd_datas = collect_data_files('tkinterdnd2')
tkdnd_hiddenimports = collect_submodules('tkinterdnd2')
project_root = Path.cwd()
sys.path.insert(0, str(project_root))
from scripts.verify_ffmpeg_distribution import verify_ffmpeg_vendor

vendor_root = project_root / 'vendor'
ffmpeg_vendor_root = vendor_root / 'ffmpeg-windows'
if ffmpeg_vendor_root.exists():
    verify_ffmpeg_vendor(project_root)
vendor_datas = [
    (str(path), str(Path('vendor') / path.relative_to(vendor_root).parent))
    for path in vendor_root.rglob('*')
    if path.is_file()
]


a = Analysis(
    ['compressor_launcher_tkinter.py'],
    pathex=[],
    binaries=[],
    datas=[('sounds', 'sounds'), ('images', 'images'), ('frontend/config_data', 'frontend/config_data'), *vendor_datas, *tkdnd_datas],
    hiddenimports=[
        'frontend.bootstrap',
        'backend.contracts',
        'backend.capabilities',
        'backend.orchestrator.job_runner',
        'backend.services.archive_service',
        'backend.core.pdf_utils',
        'backend.core.image_utils',
        'backend.core.worker_ops',
        'tkinterdnd2',
        *tkdnd_hiddenimports,
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PySide6'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='PDF_JPG_PNG_Compressor',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='images/pjp_compressor_icon.ico',
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='PDF_JPG_PNG_Compressor',
)
