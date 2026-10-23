#!/usr/bin/env python3
"""Launcher: ./op1video.py <command> (same as python -m op1video)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from op1video.cli import main  # noqa: E402

main()
