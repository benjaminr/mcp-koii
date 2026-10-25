#!/usr/bin/env python3
"""Entry point kept at the repo root so `mcp install koii_studio_server.py` keeps working."""

from koii_studio.server import main, server  # noqa: F401

if __name__ == "__main__":
    main()
