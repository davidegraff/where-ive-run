"""Start the server: `uv run python -m server [--reload]`.

    PORT   default 8787
    HOST   default 127.0.0.1 (use 0.0.0.0 in a container)

Other settings are in settings.py.
"""

from __future__ import annotations

import os
import sys

import uvicorn


def main() -> None:
    uvicorn.run(
        "server.main:create_app",
        factory=True,
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8787")),
        reload="--reload" in sys.argv[1:],
        reload_dirs=["server"],
    )


if __name__ == "__main__":
    main()
