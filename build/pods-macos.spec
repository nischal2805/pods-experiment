# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

# Collect all data/binaries/hiddenimports for these packages
datas = []
binaries = []
hiddenimports = []

for pkg in ['uvicorn', 'fastapi', 'starlette', 'httpx', 'pydantic', 'click', 'huggingface_hub']:
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hiddenimports += h

# Explicit hidden imports that PyInstaller misses
hiddenimports += [
    'pods',
    'pods.cli',
    'pods.cli.init',
    'pods.cli.join',
    'pods.cli.attach',
    'pods.cli.invite',
    'pods.cli.keygen',
    'pods.cli.status',
    'pods.cli.logs',
    'pods.cli.ping',
    'pods.cli.model',
    'pods.gateway',
    'pods.gateway.app',
    'pods.gateway.auth',
    'pods.gateway.router',
    'pods.gateway.proxy',
    'pods.gateway.routes_external',
    'pods.gateway.routes_internal',
    'pods.agent',
    'pods.agent.heartbeat',
    'pods.agent.server',
    'pods.inference.llamacpp',
    'pods.inference.exo',
    'pods.inference.ollama',
    'pods.inference.fallback',
    'pods.inference.detector',
    'pods.models.registry',
    'pods.models.downloader',
    'pods.models.manager',
    'pods.network.tailscale',
    'pods.network.invite',
    'pods.platform.detect',
    'pods.platform.setup',
    'pods.platform.windows',
    'pods.state.schema',
    'pods.state.store',
    'pods.state.defaults',
    'pods.preflight',
    'pods.errors',
    'uvicorn.logging',
    'uvicorn.loops',
    'uvicorn.loops.auto',
    'uvicorn.loops.asyncio',
    'uvicorn.protocols',
    'uvicorn.protocols.http',
    'uvicorn.protocols.http.auto',
    'uvicorn.protocols.websockets',
    'uvicorn.protocols.websockets.auto',
    'uvicorn.lifespan',
    'uvicorn.lifespan.on',
    'anyio',
    'anyio._backends._asyncio',
]

a = Analysis(
    ['../pods/__main__.py'],
    pathex=['..'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='pods',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=True,
    target_arch='universal2',
    codesign_identity=None,
    entitlements_file=None,
)
