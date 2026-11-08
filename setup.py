"""Legacy setuptools entry point for the Rizzler core package.

The canonical project metadata, Python support range, and the ``src/`` package
layout live in ``pyproject.toml``. Keep a single source of truth rather than
maintaining duplicate package versions or dependency lists here.

This installs the reusable ``rizzler`` orchestration contracts. The GPU-backed
Kaggle voice assistant is launched separately from its notebook.
"""

from setuptools import setup


if __name__ == "__main__":
    setup()
