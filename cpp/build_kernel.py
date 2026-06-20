"""Compile the native MC kernel into ``spdt/pricing/_spdt_mc*.so``.

Standalone (no build-system wiring) so the package still ``pip install -e``s on a machine with
no compiler — the kernel is an *optional accelerator*, and :mod:`spdt.pricing.native` falls back
to a NumPy reference when it is absent. Run once locally::

    python cpp/build_kernel.py

Requires a C++17 compiler and ``pybind11`` (``pip install pybind11``).
"""

from __future__ import annotations

import subprocess
import sys
import sysconfig
from pathlib import Path

import pybind11

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "cpp" / "mc_kernel" / "autocall_kernel.cpp"
OUT_DIR = ROOT / "spdt" / "pricing"
EXT_SUFFIX = sysconfig.get_config_var("EXT_SUFFIX") or ".so"
OUT = OUT_DIR / f"_spdt_mc{EXT_SUFFIX}"


def _macos_sdk_path() -> str | None:
    try:
        return subprocess.check_output(["xcrun", "--show-sdk-path"], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def main() -> int:
    cmd = [
        "c++",
        "-O3",
        "-ffast-math",
        "-funroll-loops",
        "-march=native",
        "-std=c++17",
        "-shared",
        "-fPIC",
        f"-I{pybind11.get_include()}",
        f"-I{sysconfig.get_path('include')}",
        str(SRC),
        "-o",
        str(OUT),
    ]
    if sys.platform == "darwin":
        cmd[1:1] = ["-undefined", "dynamic_lookup", "-stdlib=libc++"]
        sdk = _macos_sdk_path()
        if sdk:
            # Some Command Line Tools installs ship the libc++ headers only inside the SDK, not
            # the toolchain dir, so point at both the sysroot and the SDK's c++/v1 explicitly.
            cmd[1:1] = ["-isysroot", sdk, "-isystem", f"{sdk}/usr/include/c++/v1"]
    print(" ".join(cmd))
    result = subprocess.run(cmd)
    if result.returncode == 0:
        print(f"built {OUT}")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
