# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for AutoVtuber.
#
# 設計原則 (與 docs/MVP3_PLAN.md M3-6 對齊):
#   - --onedir 模式 (model 太多, --onefile 啟動會炸)
#   - 不打包大型 ML 權重 (SDXL/IP-Adapter/TripoSR ckpt) — 使用者跑 setup wizard 第一次啟動下載
#   - 打包 mediapipe / diffusers / pyrender 等 ML 套件的 hidden imports + binary deps
#   - 處理 PySide6 plugins (Qt platforms / imageformats)
#   - 處理 cv2 / onnxruntime DLL
#   - 把 docs/i18n/external/TripoSR 內 source code 帶上 (不含 ckpt)

import os
from pathlib import Path
from PyInstaller.utils.hooks import (
    collect_all,
    collect_data_files,
    collect_submodules,
    collect_dynamic_libs,
)

ROOT = Path(SPECPATH)

# ---- 打包用的資料檔 (運作時從 _MEIPASS 讀) ---- #
datas = [
    (str(ROOT / "config.example.toml"), "."),
    (str(ROOT / "docs"), "docs"),
    (str(ROOT / "assets" / "i18n"), "assets/i18n"),
    (str(ROOT / "assets" / "base_models"), "assets/base_models"),  # face_uv_template_*.json
    (str(ROOT / "external" / "TripoSR" / "tsr"), "external/TripoSR/tsr"),  # TripoSR source
]

# ---- ML 套件的 hidden imports (PyInstaller 抓不到動態 import) ---- #
hiddenimports = []
binaries = []

for pkg in [
    "mediapipe", "cv2", "onnxruntime", "rembg", "pymatting",
    "trimesh", "pygltflib", "diffusers", "transformers", "huggingface_hub",
    "pyrender", "OpenGL", "tsr",  # TripoSR
    "scipy", "skimage", "numba",
    "pydantic", "PySide6", "shiboken6",
]:
    try:
        d, b, hi = collect_all(pkg)
        datas.extend(d)
        binaries.extend(b)
        hiddenimports.extend(hi)
    except Exception:
        # 某些套件 collect_all 失敗 — fallback 各自處理
        try:
            hiddenimports.extend(collect_submodules(pkg))
            binaries.extend(collect_dynamic_libs(pkg))
        except Exception:
            pass

# 額外 hidden（runtime 動態 import）
hiddenimports += [
    "autovtuber.pipeline",
    "autovtuber.safety",
    "autovtuber.vrm",
    "autovtuber.ui",
    "autovtuber.workers",
    "autovtuber.setup",
    "autovtuber.config",
    "autovtuber.utils",
]

# ---- analysis ---- #
a = Analysis(
    [str(ROOT / "src" / "autovtuber" / "__main__.py")],
    pathex=[str(ROOT / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 排除明顯不用的（減 size）
        "matplotlib.tests",
        "numpy.tests",
        "scipy.tests",
        "sklearn.tests",
        "pytest",
        "_pytest",
        "tests",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,  # onedir 模式 — 把 binary 放外面
    name="AutoVtuber",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX 壓縮對 ML wheel 常會破壞 — 關掉
    console=False,  # GUI app；改 True 看 console log
    icon=None,  # 之後加 .ico
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="AutoVtuber",
)
