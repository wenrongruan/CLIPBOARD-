"""Launch the actual frozen Windows app with isolated data and verify its UI."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

import psutil
import win32gui
import win32process
from PIL import ImageGrab


def main() -> None:
    executable = Path(sys.argv[1]).resolve()
    report_path = executable.parent / "windows-launch.json"
    report = {"executable": executable.name, "status": "failed"}
    process = None
    known_pids = set()
    try:
        with tempfile.TemporaryDirectory(prefix="sharedclipboard-exe-smoke-") as state:
            env = os.environ.copy()
            env["APPDATA"] = state
            env["LOCALAPPDATA"] = state
            env["SC_STARTUP_METRICS"] = "1"
            env.pop("QT_QPA_PLATFORM", None)
            process = subprocess.Popen([str(executable)], env=env)
            known_pids.add(process.pid)
            deadline = time.monotonic() + 60
            windows = []
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError(f"Executable exited early with {process.returncode}")
                try:
                    known_pids.update(p.pid for p in psutil.Process(process.pid).children(recursive=True))
                except psutil.NoSuchProcess:
                    pass
                windows = []

                def collect(hwnd, _):
                    _, pid = win32process.GetWindowThreadProcessId(hwnd)
                    if pid in known_pids and win32gui.IsWindowVisible(hwnd):
                        title = win32gui.GetWindowText(hwnd)
                        if title:
                            windows.append({"title": title, "class": win32gui.GetClassName(hwnd)})

                win32gui.EnumWindows(collect, None)
                if any("Qt" in window["class"] for window in windows):
                    break
                time.sleep(0.5)
            else:
                raise RuntimeError(f"No visible Qt app window within 60 seconds: {windows}")
            time.sleep(5)
            if process.poll() is not None:
                raise RuntimeError(f"Executable crashed with {process.returncode}")
            if any("error" in window["title"].lower() or "traceback" in window["title"].lower() for window in windows):
                raise RuntimeError(f"Executable displayed an error: {windows}")
            database = Path(state) / "SharedClipboard" / "clipboard.db"
            if not database.is_file():
                raise RuntimeError("The application did not initialize its clipboard database")
            ImageGrab.grab(all_screens=True).save(executable.parent / "windows-launch.png")
            report.update(status="passed", windows=windows, database_initialized=True)
            print(json.dumps(report, ensure_ascii=False))
            stop_processes(known_pids)
    finally:
        stop_processes(known_pids)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def stop_processes(pids) -> None:
    processes = []
    for pid in pids:
        try:
            process = psutil.Process(pid)
            process.kill()
            processes.append(process)
        except psutil.NoSuchProcess:
            pass
    psutil.wait_procs(processes, timeout=10)


if __name__ == "__main__":
    main()
