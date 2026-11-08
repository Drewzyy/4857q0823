"""Entry point: `python -m clippr` (dev) or the bundled `clippr-backend` sidecar (desktop)."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(prog="clippr-backend")
    parser.add_argument("--port", type=int, default=int(os.environ.get("CLIPPR_PORT", "8765")))
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--frontend", default=os.environ.get("CLIPPR_FRONTEND_DIST"), help="path to built frontend (dist/)")
    args = parser.parse_args()

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
    # The desktop shell reads this line to know where to point the window.
    print(f"CLIPPR_READY url={cfg.base_url}/", flush=True)
    sys.stdout.flush()
    uvicorn.run(app, host=cfg.host, port=cfg.port, log_level="warning", access_log=False)


if __name__ == "__main__":
    main()
