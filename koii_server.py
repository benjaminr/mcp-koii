#!/usr/bin/env python3
"""Entry point kept at the repo root so `mcp install koii_server.py` keeps working."""

from koii.server import main, server  # noqa: F401

if __name__ == "__main__":
    main()
