"""Authentication module: password verification, TOTP 2FA, rate limiting."""

import hmac
import io
import os
import base64
import time
from collections import defaultdict

import pyotp
import qrcode


# ---------------------------------------------------------------------------
# Rate limiter (in-memory, resets on restart)
# ---------------------------------------------------------------------------

_attempts: dict[str, list[float]] = defaultdict(list)
_RATE_WINDOW = 900  # 15 minutes
_MAX_ATTEMPTS = 5


def is_rate_limited(ip: str) -> bool:
    """Return True if *ip* has exceeded the login attempt threshold."""
    now = time.time()
    cutoff = now - _RATE_WINDOW
    _attempts[ip] = [t for t in _attempts[ip] if t > cutoff]
    return len(_attempts[ip]) >= _MAX_ATTEMPTS


def record_failed_attempt(ip: str) -> None:
    _attempts[ip].append(time.time())


def reset_attempts(ip: str) -> None:
    _attempts.pop(ip, None)


# ---------------------------------------------------------------------------
# Password
# ---------------------------------------------------------------------------

def check_password(submitted: str) -> bool:
    """Constant-time compare against ADMIN_PASSWORD env var."""
    expected = os.environ.get("ADMIN_PASSWORD", "")
    if not expected:
        return False
    return hmac.compare_digest(submitted.encode(), expected.encode())


# ---------------------------------------------------------------------------
# TOTP
# ---------------------------------------------------------------------------

def is_totp_configured() -> bool:
    return bool(os.environ.get("TOTP_SECRET", ""))


def check_totp(code: str) -> bool:
    """Verify a 6-digit TOTP code (allows +/- 1 time step)."""
    secret = os.environ.get("TOTP_SECRET", "")
    if not secret:
        return False
    totp = pyotp.TOTP(secret)
    return totp.verify(code, valid_window=1)


def generate_totp_secret() -> str:
    return pyotp.random_base32()


def generate_totp_qr(secret: str, issuer: str = "FlickrDownloader",
                     account: str = "admin") -> str:
    """Return a base64-encoded PNG data URI of the TOTP provisioning QR code."""
    totp = pyotp.TOTP(secret)
    uri = totp.provisioning_uri(name=account, issuer_name=issuer)
    img = qrcode.make(uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"
