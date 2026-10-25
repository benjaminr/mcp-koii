#!/usr/bin/env python3
from setuptools import setup, find_packages

setup(
    name="koii-studio",
    version="0.4.0",
    description="koii studio: make beats, songs and sounds for the EP-133 K.O. II, with Claude over MCP",
    author="Ben Rowell",
    license="MIT",
    packages=find_packages(exclude=["tests"]),
    py_modules=["koii_studio_server"],
    package_data={"koii_studio": ["static/*"]},
    python_requires=">=3.9",
    install_requires=[
        "mido>=1.2.10",
        "python-rtmidi>=1.5",
        "mcp[cli]>=1.5,<2",
        "numpy>=1.24",      # the sound engine and analysis
        "scipy>=1.10",
    ],
    entry_points={
        "console_scripts": [
            "koii-studio-server=koii_studio.server:main",
            "koii-studio=koii_studio.visualiser:main",
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
