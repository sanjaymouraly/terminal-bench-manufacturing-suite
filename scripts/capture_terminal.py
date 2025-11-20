#!/usr/bin/env python3
"""Capture a genuine Windows Terminal screenshot for repository evidence.

This is an evidence-capture utility, not part of benchmark scoring or CI. It opens a
new Windows Terminal window with a unique title, runs a PowerShell script, waits for a
completion marker, maximizes the terminal, captures its rectangle, and closes it.

Windows-only and opt-in. Linux/macOS evidence must be captured by the operator.
"""

from __future__ import annotations

import argparse
import contextlib
import ctypes
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

from PIL import ImageGrab

user32 = ctypes.windll.user32
with contextlib.suppress(AttributeError, OSError):
    ctypes.windll.shcore.SetProcessDpiAwareness(2)

SW_MINIMIZE = 6
SW_MAXIMIZE = 3
SW_RESTORE = 9
WM_CLOSE = 0x0010


def find_window(marker: str) -> int | None:
    matches: list[int] = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def callback(hwnd: int, _lparam: int) -> bool:
        length = user32.GetWindowTextLengthW(hwnd)
        if length and user32.IsWindowVisible(hwnd):
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            if marker in buffer.value:
                matches.append(hwnd)
        return True

    user32.EnumWindows(callback_type(callback), 0)
    return matches[0] if matches else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--script", type=Path, required=True, help="PowerShell script to run")
    parser.add_argument("--output", type=Path, required=True, help="PNG destination")
    parser.add_argument("--marker", required=True, help="unique terminal title marker")
    parser.add_argument("--timeout", type=float, default=180.0)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    script = args.script.resolve()
    ready = script.with_suffix(".ready")
    ready.unlink(missing_ok=True)
    wrapper = script.with_suffix(".wrapper.ps1")
    wrapper.write_text(
        f"Clear-Host\n& '{script}'\n"
        f"New-Item -ItemType File -Force -Path '{ready}' | Out-Null\n"
        "Start-Sleep -Seconds 600\n",
        encoding="utf-8",
    )
    wt = subprocess.Popen(
        [
            "wt.exe",
            "-w",
            "-1",
            "new-tab",
            "--title",
            args.marker,
            "powershell.exe",
            "-NoLogo",
            "-NoExit",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(wrapper),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + args.timeout
    hwnd: int | None = None
    while time.monotonic() < deadline:
        hwnd = find_window(args.marker)
        if hwnd and ready.exists():
            break
        time.sleep(0.5)
    if not hwnd:
        wt.terminate()
        raise SystemExit("Terminal window was not found before the timeout.")
    if not ready.exists():
        wt.terminate()
        raise SystemExit("The command script did not signal completion before the timeout.")
    previous = user32.GetForegroundWindow()
    user32.ShowWindow(previous, SW_MINIMIZE)
    user32.ShowWindow(hwnd, SW_MAXIMIZE)
    user32.BringWindowToTop(hwnd)
    time.sleep(1.0)
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    image = ImageGrab.grab(
        bbox=(rect.left, rect.top, rect.right, rect.bottom), include_layered_windows=False
    )
    image.save(args.output)
    print(f"Captured {args.output} ({image.width}x{image.height})")
    if previous:
        user32.ShowWindow(previous, SW_RESTORE)
    user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
    try:
        wt.wait(timeout=5)
    except subprocess.TimeoutExpired:
        wt.terminate()
    return 0


if __name__ == "__main__":
    sys.exit(main())
