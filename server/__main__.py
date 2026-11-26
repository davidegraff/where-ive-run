"""Start the server: `uv run python -m server [--reload]`.

    PORT   default 8787
    HOST   default 127.0.0.1 (use 0.0.0.0 in a container)

Other settings are in settings.py.
"""

from __future__ import annotations

import copy
import os
import sys

import uvicorn
from uvicorn.config import LOGGING_CONFIG


def main() -> None:
    # Show the server's own messages (e.g. "Downloading ...cities1000.zip") next to uvicorn's.
    reload = "--reload" in sys.argv[1:]
    log_config = copy.deepcopy(LOGGING_CONFIG)
    log_config["loggers"]["server"] = {"handlers": ["default"], "level": "INFO", "propagate": False}
    uvicorn.run(
        "server.main:create_app",
        factory=True,
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8787")),
        reload=reload,
        reload_dirs=["server"] if reload else None,
        log_config=log_config,
    )


if __name__ == "__main__":
    main()
