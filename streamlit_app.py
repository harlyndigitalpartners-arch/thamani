"""Streamlit entrypoint for cloud deployment."""
from __future__ import annotations

import runpy
import sys
from pathlib import Path

# Ensure project root is in Python module search path
project_root = Path(__file__).resolve().parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

if __name__ == "__main__":
    target = project_root / "src" / "ui" / "app.py"
    runpy.run_path(str(target), run_name="__main__")
