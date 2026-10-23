#!/usr/bin/env python3
from setuptools import setup, find_packages

setup(
    name="mcp-koii",
    version="0.3.0",
    description="MCP Interface for EP-133 K.O. II",
    author="Ben Rowell",
    packages=find_packages(exclude=["tests"]),
    py_modules=["koii_server"],
    package_data={"koii": ["static/*"]},
    python_requires=">=3.9",
    install_requires=[
        "mido>=1.2.10",
        "python-rtmidi>=1.5",
        "mcp[cli]>=1.5,<2",
    ],
    entry_points={
        "console_scripts": [
            "koii-server=koii.server:main",
            "koii-visualiser=koii.visualiser:main",
        ],
    },
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.12",
    ],
)
