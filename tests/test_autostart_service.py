import sys

import pytest

from subtrack.services.autostart_service import VALUE_NAME, AutostartService, launch_command


class FakeRunKey:
    """Stands in for the registry so tests never touch the real Run key."""

    def __init__(self):
        self.values: dict[str, str] = {}

    def read(self, name):
        return self.values.get(name)

    def write(self, name, command):
        self.values[name] = command

    def delete(self, name):
        self.values.pop(name, None)


def test_enable_and_disable():
    key = FakeRunKey()
    service = AutostartService(key, command='"app.exe" --minimized')
    assert not service.is_enabled()

    service.set_enabled(True)
    assert key.values == {VALUE_NAME: '"app.exe" --minimized'}
    assert service.is_enabled() and service.is_current()

    service.set_enabled(False)
    assert key.values == {}
    service.set_enabled(False)  # disabling twice is fine


def test_detects_entry_for_another_copy():
    key = FakeRunKey()
    key.values[VALUE_NAME] = '"C:\\old\\app.exe" --minimized'
    service = AutostartService(key, command='"C:\\new\\app.exe" --minimized')
    assert service.is_enabled()
    assert not service.is_current()


def test_launch_command_from_source_runs_main_script_minimized():
    command = launch_command()
    assert command.endswith('__main__.py" --minimized')
    assert "pythonw.exe" in command or "python" in command.lower()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_real_registry_is_supported_on_windows():
    # Only reads; never writes to the real registry.
    service = AutostartService()
    assert service.is_supported()
    service.is_enabled()
