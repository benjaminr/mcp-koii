#!/usr/bin/env python3
"""Entry point at the repo root, for `mcp install koii_studio_server.py`."""

from koii_studio.server import main, server  # noqa: F401

if __name__ == "__main__":
    main()
