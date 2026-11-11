"""Is there an internet connection? Checked at most every 20 seconds, so asking often is cheap."""
from __future__ import annotations

import os
import socket
import time

_state = {"at": 0.0, "ok": True}
HOSTS = (("1.1.1.1", 443), ("8.8.8.8", 53), ("www.twitch.tv", 443))


def online() -> bool:
    if time.monotonic() - _state["at"] < 20:
        return _state["ok"]
    ok = bool(os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy"))  # behind a proxy: can't tell directly
    for host in () if ok else HOSTS:
        try:
            socket.create_connection(host, timeout=3).close()
            ok = True
            break
        except OSError:
            continue
    _state.update(at=time.monotonic(), ok=ok)
    return ok
