"""Locations of files the app writes to disk."""

import os
from pathlib import Path

APP_NAME = "SubTrack"


def data_dir() -> Path:
    """%APPDATA%\\SubTrack on Windows, ~/.subtrack elsewhere. Created if missing."""
    appdata = os.environ.get("APPDATA")
    path = Path(appdata) / APP_NAME if appdata else Path.home() / ".subtrack"
    path.mkdir(parents=True, exist_ok=True)
    return path


def database_path() -> Path:
    return data_dir() / "subtrack.db"


def log_path() -> Path:
    return data_dir() / "subtrack.log"
