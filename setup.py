#!/usr/bin/env python3
from setuptools import setup, find_packages

setup(
    name="mcp-koii",
    version="0.1.0",
    description="MCP Interface for EP-133 K.O. II",
    author="Ben Rowell",
    packages=find_packages(),
    install_requires=[
        "mido>=1.2.10",
        "mcp>=1.5.0",
    ],
    entry_points={
        "console_scripts": [
            "koii-server=koii_server:server.run",
        ],
    },
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
    ],
)