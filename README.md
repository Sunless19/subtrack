# SubTrack

Desktop application for managing personal subscriptions (Python + PySide6 + SQLite).
See [ARCHITECTURE.md](ARCHITECTURE.md) for the design and implementation status.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Run from source

```powershell
$env:PYTHONPATH = "src"; .\.venv\Scripts\python.exe -m subtrack
```

Data is stored in `%APPDATA%\SubTrack\subtrack.db`.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest
```

## Build the Windows app

```powershell
.\build.ps1
```

Runs the tests, builds `dist\SubTrack\SubTrack.exe` with PyInstaller, starts it once
as a smoke test, and writes to `dist\`:

| File                              | What it is                                    |
|-----------------------------------|-----------------------------------------------|
| `SubTrack-<version>-setup.exe`    | installer (per user, no admin needed)         |
| `SubTrack-<version>-portable.zip` | unzip anywhere and run `SubTrack.exe`         |

The installer step needs [Inno Setup 6](https://jrsoftware.org/isinfo.php)
(`winget install JRSoftware.InnoSetup`); without it the script skips that step.

## Releasing

GitHub Actions ([.github/workflows/build.yml](.github/workflows/build.yml)) runs the
tests and builds the installer and zip on every push and pull request; the files are
kept as workflow artifacts for 14 days.

To publish a release:

1. Bump `__version__` in [src/subtrack/__init__.py](src/subtrack/__init__.py), e.g. to `0.2.0`, and commit.
2. Tag and push:
   ```powershell
   git tag v0.2.0
   git push origin main v0.2.0
   ```
3. The workflow builds everything and creates the GitHub Release with the installer,
   the portable zip and `SHA256SUMS.txt`. People download it from the Releases page.

The build fails if the tag does not match `__version__`.

## Icon

`assets/subtrack.ico` is generated from the drawing in `src/subtrack/ui/icon.py`.
After changing the drawing, run `.\.venv\Scripts\python.exe tools\make_icon.py`
(on a normal desktop session) and commit the new `.ico`.
