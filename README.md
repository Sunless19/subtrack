# SubTrack

Desktop application for managing personal subscriptions (Python + PySide6 + SQLite).
See [ARCHITECTURE.md](ARCHITECTURE.md) for the design and implementation status.

## Features

- Subscriptions with price, currency (RON / EUR / USD), billing cycle, category, free trial, notes
- **Templates** for ~60 common services (Netflix, Spotify, Microsoft 365, …): type the name and
  category and billing cycle fill in; coloured letter badges next to every name
- **Shared plans**: split the cost between N people; every total uses your share
- **Price history**: price changes are recorded; the list shows ▲/▼ % since the first price
- **Introductory prices** that end on a date, then switch to the regular price
- **Contracts**: end date and notice period, with a "last day to cancel" reminder
- **Pause** between two dates, or **skip** just the next payment
- **Payment method** per subscription, with a filter
- Totals per month and per year in one currency; exchange rates typed in or **fetched online** (opt-in, ECB rates)
- Dashboard: spending per category, **last 12 months and 12-month forecast**, payments due in the next 30 days;
  **spent so far** per subscription in the list
- **Reminders** a few days before and on the payment day, as Windows notifications with
  *Mark as paid*, *Remind me in 1 hour* and *Remind me tomorrow* buttons; payments that fell due
  while the PC was off are caught up on at the next start
- Reminders tab: last and next 30 days of payments, contract deadlines and price changes, with their status
- Search, category and payment-method filters, sort by any column (money sorts across currencies), show/reactivate cancelled
- Export to CSV (Excel), JSON (backup) and **.ics calendar** (Google Calendar, Outlook); import CSV / JSON
- Runs in the tray, optional start with Windows, all data stays on your PC

## Roadmap

Every idea from the comparison with similar apps (Wallos, Bobby, Chronicle, ReSubs, TrackMySubs)
is built, except **automatic logo lookup**: it would download third-party brand logos (trademark
and privacy concerns), so SubTrack draws its own letter badges instead.

Possible next steps:

| Idea | Note |
|------|------|
| Multiple tags per subscription | Wallos #855 |
| Variable amounts (e.g. utility bills) | Wallos #1141 |
| Web or phone version | See "Web version" in ARCHITECTURE.md |

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

1. Bump `__version__` in [src/subtrack/__init__.py](src/subtrack/__init__.py), e.g. to `0.5.0`.
2. Write the notes in `release-notes/v0.5.0.md` (optional; a short default is used otherwise) and commit.
3. Tag and push:
   ```powershell
   git tag v0.5.0
   git push origin main v0.5.0
   ```
4. The workflow builds everything and creates the release in **two** places:
   - this (private) repo, and
   - the public [Sunless19/subtrack-releases](https://github.com/Sunless19/subtrack-releases),
     which is where installed copies look for updates and where people download it.

The build fails if the tag does not match `__version__`.

### Automatic updates: one-time setup

Publishing to the public repo needs a token, stored as a secret of this repo
(never in the app). Until it is set, releases still work, but the public step is
skipped with a warning and installed copies won't see the new version.

1. GitHub → your avatar → **Settings → Developer settings → Personal access tokens →
   Fine-grained tokens → Generate new token**.
2. Name `subtrack-releases`, expiration up to 1 year, **Repository access: Only select
   repositories → `Sunless19/subtrack-releases`**.
3. **Permissions → Repository permissions → Contents: Read and write**. Nothing else.
4. Generate, copy the token.
5. This repo → **Settings → Secrets and variables → Actions → New repository secret**:
   name `RELEASES_TOKEN`, paste the token.

When the token expires, generate a new one the same way and update the secret.

### How updating works

Installed copies check `api.github.com/repos/Sunless19/subtrack-releases/releases/latest`
1 minute after starting and every 6 hours. A newer version's installer is downloaded to
`%LOCALAPPDATA%\SubTrack\updates`, checked against `SHA256SUMS.txt`, and run silently:
right away if SubTrack is in the tray, when the user quits, or when they click
"Restart to update". SubTrack starts again afterwards. Both behaviours can be switched
off in Settings. Portable copies only show a notification with the download page.

## Icon

`assets/subtrack.ico` is generated from the drawing in `src/subtrack/ui/icon.py`.
After changing the drawing, run `.\.venv\Scripts\python.exe tools\make_icon.py`
(on a normal desktop session) and commit the new `.ico`.
