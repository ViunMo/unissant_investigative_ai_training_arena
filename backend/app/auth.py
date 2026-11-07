"""Login: username + password accounts stored in the data directory, HMAC-signed bearer tokens.

Standard library only (PBKDF2 password hashes, HMAC-SHA256 tokens) so the arena keeps running offline.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

TOKEN_TTL_SECONDS = 12 * 3600
USERNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{1,39}$")
MIN_PASSWORD = 6


class AuthError(ValueError):
    pass


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class UserStore:
    def __init__(self, data_dir: Path | None, admin_user: str | None = None, admin_password: str | None = None,
                 secret_key: str | None = None) -> None:
        self.data_dir = data_dir
        self.users: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._secret = (secret_key or self._load_secret()).encode()
        if data_dir:
            data_dir.mkdir(parents=True, exist_ok=True)
            path = data_dir / "users.json"
            if path.exists():
                try:
                    self.users = {u["username"]: u for u in json.loads(path.read_text())}
                except Exception:
                    self.users = {}
        if admin_user and admin_password and admin_user not in self.users:
            self.create(admin_user, admin_password, role="trainer")

    # ----- persistence ---------------------------------------------------------------------------------------
    def _load_secret(self) -> str:
        if not self.data_dir:
            return secrets.token_hex(32)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        path = self.data_dir / "secret.key"
        if not path.exists():
            path.write_text(secrets.token_hex(32))
        return path.read_text().strip()

    def _save(self) -> None:
        if self.data_dir:
            (self.data_dir / "users.json").write_text(json.dumps(list(self.users.values()), indent=1))

    # ----- accounts --------------------------------------------------------------------------------------------
    @staticmethod
    def _hash(password: str, salt: bytes) -> str:
        return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000).hex()

    @staticmethod
    def public(user: dict) -> dict:
        return {"username": user["username"], "role": user["role"], "created_at": user["created_at"]}

    def create(self, username: str, password: str, role: str = "investigator") -> dict:
        username = username.strip()
        if not USERNAME_RE.match(username):
            raise AuthError("username must be 2-40 characters: letters, digits, spaces, dots, dashes or underscores")
        if len(password) < MIN_PASSWORD:
            raise AuthError(f"password must be at least {MIN_PASSWORD} characters")
        with self._lock:
            if username.lower() in {u.lower() for u in self.users}:
                raise AuthError("that username is already taken")
            salt = secrets.token_bytes(16)
            user = {"username": username, "role": role, "salt": salt.hex(), "hash": self._hash(password, salt),
                    "created_at": datetime.now(timezone.utc).isoformat()}
            self.users[username] = user
            self._save()
        return self.public(user)

    def verify(self, username: str, password: str) -> dict | None:
        user = next((u for u in self.users.values() if u["username"].lower() == username.strip().lower()), None)
        if not user:
            return None
        if not hmac.compare_digest(self._hash(password, bytes.fromhex(user["salt"])), user["hash"]):
            return None
        return self.public(user)

    # ----- tokens ----------------------------------------------------------------------------------------------
    def issue_token(self, username: str, ttl: int = TOKEN_TTL_SECONDS) -> str:
        payload = json.dumps({"u": username, "exp": int(time.time()) + ttl}).encode()
        sig = hmac.new(self._secret, payload, hashlib.sha256).digest()
        return f"{_b64(payload)}.{_b64(sig)}"

    def user_for_token(self, token: str | None) -> dict | None:
        if not token or "." not in token:
            return None
        try:
            body, sig = token.split(".", 1)
            payload = _unb64(body)
            if not hmac.compare_digest(hmac.new(self._secret, payload, hashlib.sha256).digest(), _unb64(sig)):
                return None
            data = json.loads(payload)
            if data.get("exp", 0) < time.time():
                return None
            user = self.users.get(data.get("u"))
            return self.public(user) if user else None
        except Exception:
            return None
