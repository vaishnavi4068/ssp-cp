"""Local username/password authentication, Argon2id hashing, session cookies, CSRF, rate limiting, and lockout (`ADR-GLB-005`).

Mirrors `spp-factory-foundation/services/factory-api/app/auth.py` while adding SPP personas and approver emails.
"""

from __future__ import annotations

import ipaddress
import os
import secrets
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import Settings, get_settings
from .database import get_db
from .models import CpAuditLog, CpSession, CpUser, utcnow

ph = PasswordHasher(time_cost=2, memory_cost=65536, parallelism=2)

INITIAL_USERS = [
    {
        "username": "manoj",
        "email": "manoj@example.com",
        "display_name": "Manoj (Architect)",
        "role": "architect",
        "secret_key": "manoj",
    },
    {
        "username": "dwayne",
        "email": "dwayne@example.com",
        "display_name": "Dwayne (Approver)",
        "role": "approver",
        "secret_key": "dwayne",
    },
    {
        "username": "norm",
        "email": "norm@example.com",
        "display_name": "Norm (Approver / Operations)",
        "role": "approver",
        "secret_key": "norm",
    },
    {
        "username": "bucket_owner",
        "email": "bucket.owner@example.com",
        "display_name": "Bucket Owner",
        "role": "bucket_owner",
        "secret_key": "bucket_owner",
    },
    {
        "username": "requester",
        "email": "requester@example.com",
        "display_name": "Developer Requester",
        "role": "developer",
        "secret_key": "requester",
    },
]


class RateLimiter:
    """In-memory sliding-window rate limiter per IP and per username."""

    def __init__(self) -> None:
        self._buckets: dict[str, list[float]] = defaultdict(list)

    def reset(self) -> None:
        self._buckets.clear()

    def check_and_record(self, key: str, window_seconds: int, max_requests: int) -> bool:
        now = time.monotonic()
        cutoff = now - window_seconds
        timestamps = [ts for ts in self._buckets[key] if ts > cutoff]
        if len(timestamps) >= max_requests:
            self._buckets[key] = timestamps
            return False
        timestamps.append(now)
        self._buckets[key] = timestamps
        return True


login_rate_limiter = RateLimiter()


def hash_password(password: str) -> str:
    return ph.hash(password)


def verify_password(password_hash: str, plain_password: str) -> bool:
    try:
        return ph.verify(password_hash, plain_password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def _resolve_bootstrap_password(username: str, settings: Settings, secret_key: str | None = None) -> str:
    """Read initial bootstrap password from Kubernetes Secret file (synced from GCP Secret Manager) or env var."""
    candidates = [
        f"spp-cp-bootstrap-{secret_key or username}",
        f"spp-cp-bootstrap-{username}",
        f"spp-factory-bootstrap-{secret_key or username}",
        f"spp-factory-bootstrap-{username}",
        f"bootstrap-password-{secret_key or username}",
        f"bootstrap-password-{username}",
    ]
    for name in candidates:
        secret_file = Path(settings.bootstrap_secrets_dir) / name
        if secret_file.is_file():
            val = secret_file.read_text(encoding="utf-8").strip()
            if val:
                return val
    for key_suffix in [username.upper(), (secret_key or username).upper()]:
        env_val = (
            os.getenv(f"SPP_CP_BOOTSTRAP_PASSWORD_{key_suffix}")
            or os.getenv(f"FACTORY_BOOTSTRAP_PASSWORD_{key_suffix}")
            or os.getenv(f"SPP_FACTORY_BOOTSTRAP_{key_suffix}")
        )
        if env_val:
            return env_val
    if os.getenv("SPP_CP_ALLOW_DEFAULT_BOOTSTRAP_PASSWORDS", "true").lower() != "true":
        raise RuntimeError(
            f"No bootstrap secret found for user '{username}' and default passwords are disabled "
            "(SPP_CP_ALLOW_DEFAULT_BOOTSTRAP_PASSWORDS=false)."
        )
    return f"SppFactory!{username.capitalize()}2026"


def bootstrap_users(db: Session, settings: Settings | None = None) -> None:
    """Idempotently seed local accounts with `must_change_password=True` on first bootstrap."""
    cfg = settings or get_settings()
    for u in INITIAL_USERS:
        existing = db.scalar(select(CpUser).where(CpUser.username == u["username"]))
        if existing is not None:
            existing.role = u["role"]
            existing.email = u["email"]
        else:
            initial_pw = _resolve_bootstrap_password(u["username"], cfg, u.get("secret_key"))
            user = CpUser(
                username=u["username"],
                email=u["email"],
                display_name=u["display_name"],
                role=u["role"],
                password_hash=hash_password(initial_pw),
                must_change_password=True,
                failed_login_attempts=0,
                locked_until=None,
                is_active=True,
            )
            db.add(user)
    db.commit()


def record_audit_log(
    db: Session,
    *,
    actor_username: str,
    actor_role: str,
    action_type: str,
    reason: str,
    source_ip: str = "127.0.0.1",
    resource_id: UUID | None = None,
    request_id: UUID | None = None,
    approval_id: UUID | None = None,
    details: dict[str, Any] | None = None,
) -> CpAuditLog:
    entry = CpAuditLog(
        actor_username=actor_username,
        actor_role=actor_role,
        source_ip=source_ip,
        action_type=action_type,
        resource_id=resource_id,
        request_id=request_id,
        approval_id=approval_id,
        reason=reason,
        details=details or {},
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def _parse_networks(env_name: str, default: str) -> list:
    nets = []
    for item in os.getenv(env_name, default).split(","):
        item = item.strip()
        if item:
            try:
                nets.append(ipaddress.ip_network(item, strict=False))
            except ValueError:
                pass
    return nets


def _in_networks(ip: str, nets: list) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr in n for n in nets)


def get_client_ip(request: Request) -> str:
    peer = request.client.host if request.client and request.client.host else "127.0.0.1"
    proxies = _parse_networks("SPP_CP_TRUSTED_PROXY_CIDRS", "")
    forwarded = request.headers.get("x-forwarded-for")
    if not forwarded or not _in_networks(peer, proxies):
        return peer
    lb_hops = _parse_networks("SPP_CP_TRUSTED_LB_CIDRS", "130.211.0.0/22,35.191.0.0/16")
    hops = [h.strip() for h in forwarded.split(",") if h.strip()]
    for hop in reversed(hops):
        if _in_networks(hop, lb_hops) or _in_networks(hop, proxies):
            continue
        try:
            ipaddress.ip_address(hop)
        except ValueError:
            return peer
        return hop
    return peer


def create_user_session(db: Session, user: CpUser, settings: Settings) -> CpSession:
    now = utcnow()
    session_id = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(32)
    sess = CpSession(
        session_id=session_id,
        username=user.username,
        csrf_token=csrf_token,
        created_at=now,
        last_seen_at=now,
        expires_at=now + timedelta(seconds=settings.session_absolute_timeout_seconds),
        revoked=False,
    )
    db.add(sess)
    db.commit()
    db.refresh(sess)
    return sess


def _ensure_aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def get_current_session_and_user(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> tuple[CpSession, CpUser]:
    cookie_val = request.cookies.get(settings.cookie_name)
    if not cookie_val:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    sess = db.scalar(
        select(CpSession).where(
            CpSession.session_id == cookie_val,
            CpSession.revoked == False,  # noqa: E712
        )
    )
    if not sess:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired session")

    now = utcnow()
    expires_at = _ensure_aware(sess.expires_at)
    last_seen = _ensure_aware(sess.last_seen_at)
    if expires_at and now >= expires_at:
        sess.revoked = True
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired")

    if last_seen and (now - last_seen).total_seconds() > settings.session_idle_timeout_seconds:
        sess.revoked = True
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session idle timeout exceeded")

    user = db.scalar(select(CpUser).where(CpUser.username == sess.username))
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User inactive")

    sess.last_seen_at = now
    db.commit()
    return sess, user


def require_active_user(
    request: Request,
    session_and_user: tuple[CpSession, CpUser] = Depends(get_current_session_and_user),
) -> CpUser:
    sess, user = session_and_user
    if user.must_change_password:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="must_change_password: Password change required on first login before accessing control plane endpoints.",
        )
    if request.method in {"POST", "PUT", "DELETE", "PATCH"}:
        csrf_header = request.headers.get("X-CSRF-Token", "")
        if not csrf_header or not secrets.compare_digest(csrf_header, sess.csrf_token):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="CSRF token missing or invalid",
            )
    return user


def require_architect(user: CpUser = Depends(require_active_user)) -> CpUser:
    if user.role != "architect":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only 'architect' role can perform this action (ADR-GLB-005).",
        )
    return user


def require_approver_role(user: CpUser = Depends(require_active_user)) -> CpUser:
    if user.role not in {"approver", "bucket_owner", "architect", "operations", "data_owner", "dbaas_reviewer"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"User '{user.username}' with role '{user.role}' is not authorized to record approval decisions (ADR-BP-003).",
        )
    return user
