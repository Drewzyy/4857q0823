"""Is there an internet connection? Checked at most every 20 seconds, so asking often is cheap.

This must never say "offline" while the computer is online: that would stop every download. So it only answers
offline when no name at all can be looked up (no network, Wi-Fi off, cable out). Firewalls, VPNs and proxies that
block particular addresses don't count: a download that then fails is retried as usual.
"""
from __future__ import annotations

import os
import socket
import time

_state = {"at": 0.0, "ok": True}
HOSTS = ("www.twitch.tv", "www.tiktok.com", "www.youtube.com", "discord.com")


def online() -> bool:
    if time.monotonic() - _state["at"] < 20:
        return _state["ok"]
    # Behind a proxy, names are looked up by the proxy, so a failed lookup here proves nothing.
    ok = any(os.environ.get(k) for k in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY"))
    for host in () if ok else HOSTS:
        try:
            socket.getaddrinfo(host, 443)
            ok = True
            break
        except OSError:
            continue
        except Exception:  # anything unexpected: assume online rather than stop everything
            ok = True
            break
    _state.update(at=time.monotonic(), ok=ok)
    return ok
