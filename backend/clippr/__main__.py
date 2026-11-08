"""Entry point: `python -m clippr` (dev) or the bundled `clippr-backend` service inside the Vyral app."""
from __future__ import annotations

import argparse
import os
import sys
import threading
import time
from pathlib import Path


def _alive(pid: int) -> bool:
    if os.name == "nt":
        import ctypes

        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
        if not h:
            return False
        try:
            return k.WaitForSingleObject(h, 0) == 0x102  # WAIT_TIMEOUT: still running
        finally:
            k.CloseHandle(h)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _watch_parent(pid: int) -> None:
    """Exit when the desktop app is gone, so a force-quit never leaves a second copy monitoring."""
    while True:
        time.sleep(2)
        if not _alive(pid):
            os._exit(0)


def main() -> None:
    # Windowed builds on Windows have no console: give logging somewhere to write.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")

    parser = argparse.ArgumentParser(prog="clippr-backend")
    parser.add_argument("--port", type=int, default=int(os.environ.get("CLIPPR_PORT", "8765")))
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--frontend", default=os.environ.get("CLIPPR_FRONTEND_DIST"), help="path to built frontend (dist/)")
    parser.add_argument("--parent-pid", type=int, default=None)
    args = parser.parse_args()

    if args.parent_pid:
        threading.Thread(target=_watch_parent, args=(args.parent_pid,), daemon=True).start()
    if args.data_dir:
        os.environ["CLIPPR_DATA_DIR"] = args.data_dir
    import uvicorn

    from clippr.app import create_app
    from clippr.config import Config

    cfg = Config(port=args.port)
    if args.frontend:
        cfg.frontend_dist = Path(args.frontend).resolve()
    else:
        guess = Path(__file__).resolve().parents[2] / "frontend" / "dist"
        cfg.frontend_dist = guess if guess.exists() else None
    app = create_app(cfg)
    print(f"CLIPPR_READY url={cfg.base_url}/", flush=True)
    uvicorn.run(app, host=cfg.host, port=cfg.port, log_level="warning", access_log=False, log_config=None)


if __name__ == "__main__":
    main()
