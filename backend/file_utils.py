"""Small file utilities used across the backend."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict


def atomic_write_json(
    path: Path,
    data: Dict[str, Any],
    *,
    ensure_ascii: bool = False,
    indent: int = 2,
) -> None:
    """
    Atomically write JSON to `path` to reduce the chance of partial/corrupted files.
    Uses write-to-temp + os.replace.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=f"{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=ensure_ascii, indent=indent)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    finally:
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass
        except Exception:
            pass

