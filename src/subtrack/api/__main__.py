"""Run the SubTrack API locally.

    python -m subtrack.api                      # http://127.0.0.1:8765, desktop app's data
    python -m subtrack.api --db test.db         # another database file
    python -m subtrack.api --host 0.0.0.0       # reachable from other devices on your network
                                                #   (an API key is then required)

API key: set SUBTRACK_API_KEY, and clients send it as the X-API-Key header.
Docs: open http://127.0.0.1:8765/docs in a browser.
"""

import argparse
import os
import sys
from pathlib import Path

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import uvicorn

from subtrack.api.app import create_app


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m subtrack.api", description="Run the SubTrack API.")
    parser.add_argument("--host", default="127.0.0.1", help="127.0.0.1 = this PC only (default)")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--db", type=Path, help="SQLite file (default: the desktop app's database)")
    args = parser.parse_args()

    api_key = os.environ.get("SUBTRACK_API_KEY") or None
    if args.host not in ("127.0.0.1", "localhost", "::1") and not api_key:
        parser.error("listening beyond this PC needs an API key: set SUBTRACK_API_KEY first")

    print(f"SubTrack API on http://{args.host}:{args.port}  —  docs: http://{args.host}:{args.port}/docs")
    uvicorn.run(create_app(args.db, api_key), host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    sys.exit(main())
