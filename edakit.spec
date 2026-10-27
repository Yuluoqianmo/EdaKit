import runpy
runpy.run_path("tools/build_web.py")["build"](check=True)

# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 打包配置 —— 在 Windows 上执行 `pyinstaller edakit.spec` 产出单文件 exe。
# 注意: PyInstaller 不能跨平台打包，必须在 Windows 上跑 (见 build_exe.bat)。

block_cipher = None

a = Analysis(
    # 入口必须是这个「绝对导入」的启动脚本，不能是 src/edakit/__main__.py
    # —— 后者被 PyInstaller 当独立顶层脚本编译时，`from .cli import main`
    #    会报 "attempted relative import with no known parent package"。
    ["entry.py"],
    pathex=["src"],
    binaries=[],
    datas=[
        ("LICENSE", "."),
        ("NOTICE", "."),
        ("licenses/*.txt", "licenses"),
        # Capture TCL 模板 (deploy 时拷进 Cadence 安装树)
        ("src/edakit/install/templates/*.tcl", "edakit/install/templates"),
        ("src/edakit/install/templates/*.il", "edakit/install/templates"),
        ("src/edakit/ibom/UPSTREAM.md", "edakit/ibom"),
        ("src/edakit/ibom/view3d.js", "edakit/ibom"),
        ("src/edakit/ibom/mobile.js", "edakit/ibom"),
        ("src/edakit/ibom/mobile.css", "edakit/ibom"),
        ("src/edakit/ibom/vendor/*", "edakit/ibom/vendor"),
        # 商城网页界面 —— 必须打进包，运行时 server/app.py 按 __file__ 相对定位
        ("src/edakit/server/web/*.html", "edakit/server/web"),
        ("src/edakit/server/web/*.css", "edakit/server/web"),
        ("src/edakit/server/web/*.js", "edakit/server/web"),
        # Capture 真方言的 DefaultValues 模板（生成的 XML 要原样带上它）
        ("src/edakit/symbol/templates/*.xml", "edakit/symbol/templates"),
        # 一个元件样例 —— 给 `selftest` 用（不联网也能验证解析/生成/渲染真的可用）
        ("tests/data/C2040.json", "edakit/samples"),
        ("tests/data/C165948.json", "edakit/samples"),
    ],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "pytest",
        # requests 会**可选**地用 pyOpenSSL/cryptography 做 SSL 后端；我们只用 stdlib 的 ssl，
        # 这条可选路径会把 cryptography 的 rust 动态库（4 MB+，上千个文件）整个拖进包里。
        # 排掉它：包小很多，PyInstaller 的 analysis 也少扫一大堆文件。
        "cryptography",
        "OpenSSL",
        "pyopenssl",
        "bcrypt",
        "cffi",
        "_cffi_backend",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="edakit",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,         # Capture launches services and olb-merge without a console.
    disable_windowed_traceback=True,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

# Explicit diagnostics entry; Capture always invokes the windowed edakit.exe.
cli_exe = EXE(
    pyz, a.scripts, a.binaries, a.zipfiles, a.datas, [],
    name="edakit-cli", debug=False, strip=False, upx=True,
    console=True, icon=None,
)
