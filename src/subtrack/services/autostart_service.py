"""Start with Windows, through the per-user Run key in the registry.

HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run needs no admin rights and
is what Task Manager's "Startup apps" page shows. The registry itself is the
source of truth, so turning it off in Task Manager is reflected in the app.
"""

import sys
from pathlib import Path
from typing import Protocol

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "SubTrack"


class RunKey(Protocol):
    """The three registry operations needed; swapped for a fake in tests."""

    def read(self, name: str) -> str | None: ...
    def write(self, name: str, command: str) -> None: ...
    def delete(self, name: str) -> None: ...


class WindowsRunKey:
    def __init__(self):
        import winreg  # only exists on Windows

        self._winreg = winreg

    def read(self, name: str) -> str | None:
        try:
            with self._winreg.OpenKey(self._winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
                return self._winreg.QueryValueEx(key, name)[0]
        except FileNotFoundError:
            return None

    def write(self, name: str, command: str) -> None:
        with self._winreg.CreateKey(self._winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            self._winreg.SetValueEx(key, name, 0, self._winreg.REG_SZ, command)

    def delete(self, name: str) -> None:
        try:
            with self._winreg.OpenKey(self._winreg.HKEY_CURRENT_USER, RUN_KEY, 0, self._winreg.KEY_SET_VALUE) as key:
                self._winreg.DeleteValue(key, name)
        except FileNotFoundError:
            pass


def launch_command() -> str:
    """Command that starts this copy of SubTrack hidden in the tray."""
    if getattr(sys, "frozen", False):  # packaged .exe (PyInstaller)
        return f'"{sys.executable}" --minimized'
    # From source: pythonw.exe has no console window.
    python = Path(sys.executable)
    pythonw = python.with_name("pythonw.exe")
    interpreter = pythonw if pythonw.exists() else python
    main_script = Path(__file__).resolve().parent.parent / "__main__.py"
    return f'"{interpreter}" "{main_script}" --minimized'


class AutostartService:
    def __init__(self, run_key: RunKey | None = None, command: str | None = None):
        if run_key is None and sys.platform == "win32":
            run_key = WindowsRunKey()
        self._run_key = run_key
        self._command = command or launch_command()

    def is_supported(self) -> bool:
        return self._run_key is not None

    def is_enabled(self) -> bool:
        return self.is_supported() and self._run_key.read(VALUE_NAME) is not None

    def is_current(self) -> bool:
        """False if the entry points at another copy (e.g. the app was moved)."""
        return self.is_supported() and self._run_key.read(VALUE_NAME) == self._command

    def set_enabled(self, enabled: bool) -> None:
        if not self.is_supported():
            raise RuntimeError("Start with Windows is only available on Windows")
        if enabled:
            self._run_key.write(VALUE_NAME, self._command)
        else:
            self._run_key.delete(VALUE_NAME)
