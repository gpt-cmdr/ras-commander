# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['assistant.py'],
    pathex=[],
    binaries=[],
    datas=[('web/templates', 'web/templates'), ('web/static', 'web/static')],
    hiddenimports=[
        'together',  
        'tiktoken',
        'tiktoken.core',
        'tiktoken.registry',
        'tiktoken.model',
        'tiktoken_ext',
        'tiktoken_ext.openai_public',  # This contains cl100k_base and other encodings
        'utils.context_integration',
        'utils.context_preprocessor'
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
    a.binaries,
    a.datas,
    [],
    name='assistant',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)