"""
auth.py
-------
Email + password authentication with a per-user risk profile.

Design (stdlib only — no new dependencies):
  - Passwords: PBKDF2-HMAC-SHA256, 210k iterations, 16-byte random salt,
    constant-time comparison. Plaintext is never stored or logged.
  - Tokens: HMAC-SHA256-signed JSON ({email, exp}), 7-day expiry — a minimal
    JWT-equivalent. Secret from AUTH_SECRET env; if unset, a random per-process
    secret is generated (tokens then die on restart — fine for dev, set the
    env var in production).
  - Storage adapter:
      * Supabase Postgres (finintel_users table, service-role key, RLS blocks
        anon access) when SUPABASE_URL + SUPABASE_SERVICE_KEY are set —
        persistent across Render redeploys.
      * Local users.json fallback for development (gitignored).
"""

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
import urllib.request
import urllib.error

_ITERATIONS = 210_000
_TOKEN_TTL = 7 * 24 * 3600
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")

_SECRET = os.environ.get("AUTH_SECRET") or secrets.token_hex(32)

_SUPABASE_URL = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
_SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY") or ""
_LOCAL_PATH = os.path.join(os.path.dirname(__file__), "users.json")
_LOCK = threading.Lock()


def backend_name() -> str:
    return "supabase" if (_SUPABASE_URL and _SUPABASE_KEY) else "local-file"


# --------------------------------------------------------------------------- #
# Password hashing
# --------------------------------------------------------------------------- #
def _hash_password(password: str, salt: bytes) -> str:
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _ITERATIONS)
    return dk.hex()


def _verify_password(password: str, salt_hex: str, expected_hash: str) -> bool:
    computed = _hash_password(password, bytes.fromhex(salt_hex))
    return hmac.compare_digest(computed, expected_hash)


# --------------------------------------------------------------------------- #
# Tokens (HMAC-signed, JWT-style)
# --------------------------------------------------------------------------- #
def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def issue_token(email: str) -> str:
    payload = _b64(json.dumps({"email": email, "exp": int(time.time()) + _TOKEN_TTL}).encode())
    sig = _b64(hmac.new(_SECRET.encode(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{sig}"


def verify_token(token: str) -> str | None:
    """Returns the email if the token is valid and unexpired, else None."""
    try:
        payload, sig = token.split(".", 1)
        expected = _b64(hmac.new(_SECRET.encode(), payload.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expected):
            return None
        obj = json.loads(_unb64(payload))
        if int(obj.get("exp", 0)) < time.time():
            return None
        return obj.get("email") or None
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# Storage adapter
# --------------------------------------------------------------------------- #
def _sb_request(method: str, path: str, body=None):
    req = urllib.request.Request(
        f"{_SUPABASE_URL}/rest/v1/{path}", method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"apikey": _SUPABASE_KEY, "Authorization": f"Bearer {_SUPABASE_KEY}",
                 "Content-Type": "application/json", "Prefer": "return=representation"})
    with urllib.request.urlopen(req, timeout=10) as r:
        raw = r.read().decode()
    return json.loads(raw) if raw else None


def _local_load() -> dict:
    try:
        with open(_LOCAL_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _local_save(users: dict):
    with open(_LOCAL_PATH, "w", encoding="utf-8") as f:
        json.dump(users, f, indent=1)


def get_user(email: str) -> dict | None:
    email = email.lower()
    if backend_name() == "supabase":
        from urllib.parse import quote
        rows = _sb_request("GET", f"finintel_users?email=eq.{quote(email)}&select=*")
        return rows[0] if rows else None
    return _local_load().get(email)


def create_user(email: str, password: str) -> dict:
    email = email.lower()
    salt = secrets.token_bytes(16)
    record = {"email": email, "pw_hash": _hash_password(password, salt),
              "salt": salt.hex(), "profile": "", "answers": None}
    if backend_name() == "supabase":
        _sb_request("POST", "finintel_users", record)
        return record
    with _LOCK:
        users = _local_load()
        users[email] = record
        _local_save(users)
    return record


def update_profile(email: str, profile: str, answers=None):
    email = email.lower()
    patch = {"profile": profile, "answers": answers,
             "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    if backend_name() == "supabase":
        from urllib.parse import quote
        _sb_request("PATCH", f"finintel_users?email=eq.{quote(email)}", patch)
        return
    with _LOCK:
        users = _local_load()
        if email in users:
            users[email].update(patch)
            _local_save(users)


# --------------------------------------------------------------------------- #
# High-level operations used by the API layer
# --------------------------------------------------------------------------- #
class AuthError(Exception):
    pass


def signup(email: str, password: str) -> dict:
    email = (email or "").strip().lower()
    if not _EMAIL_RE.match(email):
        raise AuthError("Enter a valid email address.")
    if len(password or "") < 8:
        raise AuthError("Password must be at least 8 characters.")
    if get_user(email):
        raise AuthError("An account with this email already exists — sign in instead.")
    user = create_user(email, password)
    return {"token": issue_token(email), "email": email,
            "profile": user.get("profile", ""), "answers": user.get("answers")}


def login(email: str, password: str) -> dict:
    email = (email or "").strip().lower()
    user = get_user(email)
    # Same error for unknown email and wrong password — no account enumeration.
    if not user or not _verify_password(password or "", user["salt"], user["pw_hash"]):
        raise AuthError("Invalid email or password.")
    return {"token": issue_token(email), "email": email,
            "profile": user.get("profile", ""), "answers": user.get("answers")}


def user_from_header(authorization: str | None) -> str:
    """Email from a 'Bearer <token>' header; raises AuthError if invalid."""
    if not authorization or not authorization.startswith("Bearer "):
        raise AuthError("Sign in required.")
    email = verify_token(authorization[len("Bearer "):].strip())
    if not email:
        raise AuthError("Session expired — sign in again.")
    return email
