# PyInstaller spec for Suchi backend server
# Produces a single-directory bundle that Tauri embeds as a sidecar

import sys
from pathlib import Path

block_cipher = None

a = Analysis(
    ['suchi-server.py'],
    pathex=[str(Path('src'))],
    binaries=[],
    datas=[
        # Include CSL citation style files
        ('src/suchi/citations/styles/*.csl', 'suchi/citations/styles'),
    ],
    hiddenimports=[
        'suchi',
        'suchi.api',
        'suchi.cli',
        'suchi.config',
        'suchi.library',
        'suchi.models',
        'suchi.search',
        'suchi.collections',
        'suchi.routes',
        'suchi.routes.entries',
        'suchi.routes.search',
        'suchi.routes.export',
        'suchi.routes.collections',
        'suchi.routes.settings',
        'suchi.routes.chat',
        'suchi.routes.citations',
        'suchi.routes.references',
        'suchi.routes.pdf_finder',
        'suchi.routes.annotations',
        'suchi.translators',
        'suchi.translators.crossref',
        'suchi.translators.arxiv',
        'suchi.translators.openlibrary',
        'suchi.translators.openalex',
        'suchi.translators.semantic_scholar',
        'suchi.translators.pdf_extract',
        'suchi.translators.references',
        'suchi.translators.resolver',
        'suchi.translators.zotero_rdf',
        'suchi.translators.pdf_finder',
        'suchi.translators.grobid',
        'suchi.pageindex',
        'suchi.pageindex.indexer',
        'suchi.pageindex.retriever',
        'suchi.citations',
        'suchi.citations.processor',
        'suchi.routes.discovery',
        'suchi.routes.sync',
        'suchi.sync',
        'suchi.sync.base',
        'suchi.sync.gdrive',
        'suchi.sync.engine',
        'suchi.sync.state',
        'suchi.connector',
        'suchi.connector.server',
        'uvicorn',
        'uvicorn.logging',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
        'yaml',
        'fitz',
        'httpx',
        'multipart',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'PIL.ImageTk'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# Build a single-file executable so it can be bundled as a Tauri externalBin.
# At runtime, PyInstaller extracts the embedded files to a temp directory and
# then runs the Python interpreter from there. Startup is ~1-2s slower than a
# directory bundle but it's a single file that Tauri can bundle directly.
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='suchi-server',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # No console window on Windows
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
