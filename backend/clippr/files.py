"""Deleting files without stopping on one that's in use (Windows won't delete a file another program has open,
like a video that's playing or being uploaded): it's logged and skipped, and the rest carries on."""
from __future__ import annotations

import logging
import shutil
from pathlib import Path

log = logging.getLogger("clippr.files")


def remove(path: str | Path | None) -> bool:
    if not path:
        return True
    p = Path(path)
    try:
        if p.is_dir():
            shutil.rmtree(p)
        else:
            p.unlink(missing_ok=True)
        return True
    except OSError as e:
        log.warning("couldn't delete %s (%s); it's left for the next clean-up", p, e.strerror or e)
        return False


def remove_video(path: str | Path | None) -> None:
    """A video and its thumbnail."""
    if path:
        remove(path)
        remove(Path(path).with_suffix(".jpg"))
