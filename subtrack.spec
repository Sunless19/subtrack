# PyInstaller build definition.  Build with:  .\build.ps1   (or: pyinstaller subtrack.spec)
#
# One-folder build (dist\SubTrack\SubTrack.exe + its DLLs) rather than one-file:
# it starts faster, and antivirus tools flag self-extracting one-file exes more often.
# The installer and the portable zip both package this folder.

import re
from pathlib import Path

from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo,
    StringFileInfo,
    StringStruct,
    StringTable,
    VarFileInfo,
    VarStruct,
    VSVersionInfo,
)

ROOT = Path(SPECPATH)
version = re.search(r'__version__ = "([^"]+)"', (ROOT / "src/subtrack/__init__.py").read_text()).group(1)
numbers = tuple(int(part) for part in version.split(".")) + (0,) * (4 - len(version.split(".")))

# Shown in Explorer → Properties → Details.
version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=numbers, prodvers=numbers),
    kids=[
        StringFileInfo([
            StringTable("040904B0", [
                StringStruct("CompanyName", "SubTrack"),
                StringStruct("FileDescription", "SubTrack - subscription manager"),
                StringStruct("FileVersion", version),
                StringStruct("InternalName", "SubTrack"),
                StringStruct("OriginalFilename", "SubTrack.exe"),
                StringStruct("ProductName", "SubTrack"),
                StringStruct("ProductVersion", version),
            ])
        ]),
        VarFileInfo([VarStruct("Translation", [0x0409, 1200])]),
    ],
)

# Qt modules the app never imports. Excluding them keeps the build small.
QT_EXCLUDES = [
    f"PySide6.{name}"
    for name in (
        "Qt3DAnimation Qt3DCore Qt3DExtras Qt3DInput Qt3DLogic Qt3DRender QtBluetooth QtDataVisualization "
        "QtGraphs QtHttpServer QtLocation QtMultimedia QtMultimediaWidgets QtNfc QtOpenGL QtOpenGLWidgets "
        "QtPdf QtPdfWidgets QtPositioning QtQml QtQuick QtQuick3D QtQuickControls2 QtQuickWidgets "
        "QtRemoteObjects QtScxml QtSensors QtSerialBus QtSerialPort QtSpatialAudio QtSql QtStateMachine "
        "QtSvgWidgets QtTest QtTextToSpeech QtUiTools QtWebChannel QtWebEngineCore QtWebEngineQuick "
        "QtWebEngineWidgets QtWebSockets QtWebView QtDesigner QtHelp"
    ).split()
]

a = Analysis(
    [str(ROOT / "src/subtrack/__main__.py")],
    pathex=[str(ROOT / "src")],
    excludes=QT_EXCLUDES + ["tkinter", "unittest", "pytest"],
    noarchive=False,
)

# Qt plugins (virtual keyboard, PDF image format) drag in Qt Quick, QML and Qt PDF,
# and opengl32sw.dll is a 20 MB software OpenGL fallback that plain widgets never use.
UNNEEDED_BINARIES = re.compile(
    r"(opengl32sw|Qt6(Quick|Qml|Pdf|VirtualKeyboard)\w*|qtvirtualkeyboardplugin|qpdf)\.dll$", re.IGNORECASE
)
a.binaries = [entry for entry in a.binaries if not UNNEEDED_BINARIES.search(entry[0])]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SubTrack",
    icon=str(ROOT / "assets/subtrack.ico"),
    version=version_info,
    console=False,  # GUI app: no console window
    upx=False,
)

coll = COLLECT(exe, a.binaries, a.datas, name="SubTrack", upx=False)
