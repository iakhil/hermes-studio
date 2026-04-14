"""Frozen desktop backend entrypoint.

Tauri launches this executable as a bundled sidecar in production builds.
"""

from __future__ import annotations

import os

import uvicorn


def main() -> None:
    os.environ.setdefault("HERMES_STUDIO_DESKTOP", "1")
    host = os.environ.get("HERMES_STUDIO_HOST", "127.0.0.1")
    port = int(os.environ.get("HERMES_STUDIO_PORT", "8420"))
    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        log_level=os.environ.get("HERMES_STUDIO_LOG_LEVEL", "warning"),
        access_log=False,
    )


if __name__ == "__main__":
    main()
