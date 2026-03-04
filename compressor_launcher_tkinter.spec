# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['compressor_launcher_tkinter.py'],
    pathex=[],
    binaries=[],
    datas=[('sounds', 'sounds')],
    hiddenimports=[
        'frontend.bootstrap',
        'backend.contracts',
        'backend.capabilities',
        'backend.orchestrator.job_runner',
        'backend.services.pdf_service',
        'backend.services.image_service',
        'backend.services.archive_service',
        'backend.services.cleanup_service',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='compressor_launcher_tkinter',
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
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='compressor_launcher',
)
