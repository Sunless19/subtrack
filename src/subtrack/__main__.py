import sys
from pathlib import Path

if not __package__:
    # Started as a script (e.g. by the "start with Windows" entry), not with -m:
    # make the package importable from the src folder.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from subtrack.app import run

if __name__ == "__main__":
    sys.exit(run())
