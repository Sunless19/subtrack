"""Makes sure only one SubTrack runs at a time per data folder.

A second launch (e.g. double-clicking the shortcut while SubTrack sits in the
tray) tells the running copy to show its window, then exits. Copies using a
different data folder (e.g. the build's smoke test) do not interfere.

On Windows a named mutex is also held, which the installer uses to ask the
user to close SubTrack before upgrading or uninstalling (Inno Setup's AppMutex).
"""

import hashlib
import sys

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from subtrack import paths

MUTEX_NAME = "SubTrack.SingleInstance"  # must match AppMutex in installer/subtrack.iss
_SHOW = b"show"


def server_name() -> str:
    folder = str(paths.data_dir()).lower().encode()
    return f"SubTrack.Instance.{hashlib.sha1(folder).hexdigest()[:12]}"


def notify_running_instance(show: bool) -> bool:
    """True if another SubTrack is already running (and was asked to show itself)."""
    socket = QLocalSocket()
    socket.connectToServer(server_name())
    if not socket.waitForConnected(500):
        return False
    if show:
        socket.write(_SHOW)
        socket.flush()
        socket.waitForBytesWritten(500)
    socket.disconnectFromServer()
    return True


class InstanceServer(QObject):
    """Listens for later launches. Emits show_requested when one asks for the window."""

    show_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mutex = _create_windows_mutex()
        # A crashed previous run can leave a stale server name behind on some platforms.
        name = server_name()
        QLocalServer.removeServer(name)
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._on_connection)
        self._server.listen(name)

    def _on_connection(self) -> None:
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            socket.readyRead.connect(lambda s=socket: self._on_ready_read(s))
            socket.disconnected.connect(socket.deleteLater)

    def _on_ready_read(self, socket: QLocalSocket) -> None:
        if bytes(socket.readAll()).startswith(_SHOW):
            self.show_requested.emit()


def _create_windows_mutex():
    if sys.platform != "win32":
        return None
    import ctypes

    # The handle is kept for the life of the process; Windows releases it on exit.
    return ctypes.windll.kernel32.CreateMutexW(None, False, MUTEX_NAME)
