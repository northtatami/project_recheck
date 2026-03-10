from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def open_external(path: str) -> None:
    target = str(Path(path))
    if sys.platform.startswith("win"):
        os.startfile(target)  # type: ignore[attr-defined]
        return
    if sys.platform == "darwin":
        subprocess.Popen(["open", target])
        return
    subprocess.Popen(["xdg-open", target])
