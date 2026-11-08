"""Credential storage.

Order of preference:
1. OS keychain via `keyring` (macOS Keychain on the Mac build).
2. Encrypted file (Fernet/AES) in the app data dir, key file chmod 600. Used only when no
   keychain backend exists (Linux CI, headless servers). Weaker than the keychain because the
   key sits next to the data; the Settings > Security panel says which backend is active.
3. In-memory (tests).

Values are JSON-serialisable dicts. Nothing in here is ever logged.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Protocol

SERVICE = "vyral"


class SecretStore(Protocol):
    name: str

    def get(self, key: str) -> dict[str, Any] | None: ...
    def set(self, key: str, value: dict[str, Any]) -> None: ...
    def delete(self, key: str) -> None: ...


class MemoryStore:
    name = "memory"

    def __init__(self) -> None:
        self._d: dict[str, str] = {}

    def get(self, key: str) -> dict[str, Any] | None:
        raw = self._d.get(key)
        return json.loads(raw) if raw else None

    def set(self, key: str, value: dict[str, Any]) -> None:
        self._d[key] = json.dumps(value)

    def delete(self, key: str) -> None:
        self._d.pop(key, None)


class KeyringStore:
    name = "os-keychain"

    def __init__(self) -> None:
        import keyring

        self._kr = keyring

    def get(self, key: str) -> dict[str, Any] | None:
        raw = self._kr.get_password(SERVICE, key)
        return json.loads(raw) if raw else None

    def set(self, key: str, value: dict[str, Any]) -> None:
        self._kr.set_password(SERVICE, key, json.dumps(value))

    def delete(self, key: str) -> None:
        import keyring.errors

        try:
            self._kr.delete_password(SERVICE, key)
        except keyring.errors.PasswordDeleteError:
            pass


class EncryptedFileStore:
    name = "encrypted-file"

    def __init__(self, directory: Path) -> None:
        from cryptography.fernet import Fernet

        self._path = directory / "secrets.enc"
        key_path = directory / "secrets.key"
        if not key_path.exists():
            fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(Fernet.generate_key())
        self._fernet = Fernet(key_path.read_bytes())
        self._lock = threading.Lock()

    def _load(self) -> dict[str, Any]:
        if not self._path.exists():
            return {}
        return json.loads(self._fernet.decrypt(self._path.read_bytes()))

    def _save(self, data: dict[str, Any]) -> None:
        tmp = self._path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(self._fernet.encrypt(json.dumps(data).encode()))
        os.replace(tmp, self._path)  # atomic

    def get(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            return self._load().get(key)

    def set(self, key: str, value: dict[str, Any]) -> None:
        with self._lock:
            d = self._load()
            d[key] = value
            self._save(d)

    def delete(self, key: str) -> None:
        with self._lock:
            d = self._load()
            if d.pop(key, None) is not None:
                self._save(d)


def keychain_available() -> bool:
    try:
        import keyring
        from keyring.backends import fail

        kr = keyring.get_keyring()
        return not isinstance(kr, fail.Keyring) and kr.priority > 0
    except Exception:
        return False


def make_store(backend: str, data_dir: Path) -> SecretStore:
    if backend == "memory":
        return MemoryStore()
    if backend == "keychain" or (backend == "auto" and keychain_available()):
        return KeyringStore()
    return EncryptedFileStore(data_dir)
