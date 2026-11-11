"""Locate and run bin/minivm.

The platform binary is called directly (the bin/minivm wrapper spawns a shell and
runs xattr on every call: 38.6 ms vs 8.3 ms per run, identical output [M]).
MINIVM=... overrides the choice.
"""
import json
import os
import platform
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, ".."))
BUNDLE = REPO          # the take-home bundle (bin/, examples/, docs/) is this folder
WRAPPER = os.path.join(BUNDLE, "bin", "minivm")


def _native():
    osn = {"darwin": "macos"}.get(platform.system().lower(), platform.system().lower())
    arch = {"arm64": "aarch64", "amd64": "x86_64"}.get(platform.machine().lower(), platform.machine().lower())
    if osn.startswith(("windows", "mingw", "msys", "cygwin")):
        b = os.path.join(BUNDLE, "bin", f"minivm-windows-{arch}.exe")
    else:
        b = os.path.join(BUNDLE, "bin", f"minivm-{osn}-{arch}")
    if not os.access(b, os.X_OK):
        return WRAPPER
    if osn == "macos":  # downloaded zips are quarantined; clear it once
        subprocess.run(["xattr", "-d", "com.apple.quarantine", b], capture_output=True)
    return b


VM = os.environ.get("MINIVM") or _native()


def run(prog, data, timeout=30):
    """-> (result dict, None) on success, (None, error text) on a VM error."""
    try:
        r = subprocess.run([VM, prog, data], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, "vm timeout"
    if r.returncode != 0:
        return None, (r.stderr.strip() or f"exit {r.returncode}")
    return json.loads(r.stdout), None


def schema_of(data):
    """bin/minivm --schema DATA -> (schema dict, None) or (None, error)."""
    r = subprocess.run([VM, "--schema", data], capture_output=True, text=True)
    if r.returncode != 0:
        return None, r.stderr.strip()
    return json.loads(r.stdout), None
