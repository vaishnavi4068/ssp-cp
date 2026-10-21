"""FastAPI Control Plane Service (`ssp-cp`) for the Self-Service Provisioning Platform (SPP).

Implements:
- `WI-001` (Control plane core: FastAPI on GKE `md-dev`, AlloyDB `spp_platform` four-gate schema `idp`,
  role-based sequential approvals per `ADR-BP-003` with `gcs_bucket_owner` gate, human approval required for all deletes,
  and starting Temporal workflow `GcsBucketProvisionWorkflow` on approval).
- `WI-003` (OPA policy gates: evaluates Rego policies at intake `requested` and approval `approved`, storing
  `idp.policy_evaluation` and `idp.approval.guardrail_trace`).
- Local username/password authentication (Argon2id, Secret Manager bootstrap, mandatory first-login password change,
  `__Host-` session cookies, CSRF protection, rate limiting, and 5-attempt lockout per `ADR-GLB-005`).
- CORS configured for the SPP Portal (`ssp-ui`).
"""

from __future__ import annotations

import secrets
import uuid
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .auth import (
    _ensure_aware,
    bootstrap_users,
    create_user_session,
    get_client_ip,
    get_current_session_and_user,
    hash_password,
    login_rate_limiter,
    record_audit_log,
    require_active_user,
    require_approver_role,
    require_architect,
    verify_password,
)
from .config import Settings, get_settings
from .database import check_db_ready, get_db, get_session_factory, init_engine
from .models import (
    Approval,
    CpAuditLog,
    CpSession,
    CpUser,
    DriftFinding,
    GateEvent,
    PolicyEvaluation,
    ResourceKind,
    ResourceObserved,
    ResourceRequest,
    StateUnit,
    utcnow,
)
from .opa_client import OpaClient
from .schemas import (
    ApprovalDecisionInput,
    ChangePasswordRequest,
    CreateRequestPayload,
    LoginRequest,
    StateUnitFreezeRequest,
    UnlockUserRequest,
    UserProfileResponse,
)
from .services import get_request_detail, record_approval_decision, submit_resource_request
from .temporal_bridge import TemporalBridge


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    init_engine(settings.database_url, run_migrations=True)
    session_factory = get_session_factory()
    with session_factory() as db:
        bootstrap_users(db, settings)
    app.state.opa_client = OpaClient(settings)
    app.state.temporal_bridge = TemporalBridge(settings)
    yield


app = FastAPI(
    title="SPP Control Plane API (ssp-cp)",
    version="1.0.0",
    description="Self-Service Provisioning Platform (SPP) Control Plane API (WI-001 & WI-003).",
    lifespan=lifespan,
)

_boot_settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_boot_settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_opa_client(request: Request) -> OpaClient:
    client = getattr(request.app.state, "opa_client", None)
    if client is None:
        client = OpaClient(get_settings())
        request.app.state.opa_client = client
    return client


def get_temporal_bridge(request: Request) -> TemporalBridge:
    bridge = getattr(request.app.state, "temporal_bridge", None)
    if bridge is None:
        bridge = TemporalBridge(get_settings())
        request.app.state.temporal_bridge = bridge
    return bridge


# ---------------------------------------------------------------------------
# Health & Readiness Endpoints
# ---------------------------------------------------------------------------


@app.get("/healthz")
def healthz(settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "spp-cp",
        "cluster_target": {
            "gcp_project": settings.gcp_project_id,
            "gke_cluster": settings.gke_cluster_name,
            "region": settings.gcp_region,
            "k8s_namespace": settings.k8s_namespace,
            "node_pool": settings.gke_node_pool,
            "temporal_namespace": settings.temporal_namespace,
            "temporal_task_queue": settings.temporal_task_queue,
            "temporal_gcs_workflow": settings.temporal_gcs_workflow,
            "opa_url": settings.opa_url,
            "default_kms_key_name": settings.default_kms_key_name,
            "alloydb_host": settings.alloydb_host,
            "alloydb_database": settings.alloydb_database,
        },
    }


@app.get("/readyz")
def readyz(db: Session = Depends(get_db)) -> dict[str, Any]:
    if not check_db_ready(db):
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database not ready")
    return {"status": "ready", "schema": "idp"}


# ---------------------------------------------------------------------------
# 1. Local Authentication & Session Endpoints (`ADR-GLB-005`)
# ---------------------------------------------------------------------------


@app.post("/api/v1/auth/login", response_model=UserProfileResponse)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    client_ip = get_client_ip(request)
    username = payload.username.strip().lower()

    if not login_rate_limiter.check_and_record(
        f"ip:{client_ip}",
        settings.login_rate_limit_window_seconds,
        settings.login_rate_limit_max_requests,
    ) or not login_rate_limiter.check_and_record(
        f"user:{username}",
        settings.login_rate_limit_window_seconds,
        settings.login_rate_limit_max_requests,
    ):
        record_audit_log(
            db,
            actor_username=username or "anonymous",
            actor_role="anonymous",
            action_type="login_rate_limited",
            reason="Login rate limit exceeded",
            source_ip=client_ip,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Please wait before trying again.",
        )

    user = db.scalar(select(CpUser).where(CpUser.username == username))
    now = utcnow()

    if user is None or not user.is_active:
        record_audit_log(
            db,
            actor_username=username,
            actor_role="anonymous",
            action_type="login_failed",
            reason="Invalid username or inactive user",
            source_ip=client_ip,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    locked_until = _ensure_aware(user.locked_until)
    if locked_until and locked_until > now:
        record_audit_log(
            db,
            actor_username=user.username,
            actor_role=user.role,
            action_type="login_failed_locked",
            reason=f"Account locked until {locked_until.isoformat()}",
            source_ip=client_ip,
        )
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail=f"Account is locked due to repeated failed login attempts until {locked_until.isoformat()}",
        )

    if not (
        verify_password(user.password_hash, payload.password)
        or (payload.password.strip() != payload.password and verify_password(user.password_hash, payload.password.strip()))
    ):
        user.failed_login_attempts += 1
        if user.failed_login_attempts >= settings.lockout_max_failed_attempts:
            user.locked_until = now + timedelta(seconds=settings.lockout_duration_seconds)
            db.commit()
            record_audit_log(
                db,
                actor_username=user.username,
                actor_role=user.role,
                action_type="account_locked",
                reason=f"Locked after {user.failed_login_attempts} consecutive failed login attempts",
                source_ip=client_ip,
            )
            raise HTTPException(
                status_code=status.HTTP_423_LOCKED,
                detail="Account locked after maximum consecutive failed login attempts.",
            )
        db.commit()
        record_audit_log(
            db,
            actor_username=user.username,
            actor_role=user.role,
            action_type="login_failed",
            reason=f"Invalid password (attempt {user.failed_login_attempts}/{settings.lockout_max_failed_attempts})",
            source_ip=client_ip,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    user.failed_login_attempts = 0
    user.locked_until = None
    user.last_login_at = now
    db.commit()

    sess = create_user_session(db, user, settings)
    record_audit_log(
        db,
        actor_username=user.username,
        actor_role=user.role,
        action_type="login_success",
        reason="User authenticated via local credentials",
        source_ip=client_ip,
        details={"must_change_password": user.must_change_password},
    )

    response.set_cookie(
        key=settings.cookie_name,
        value=sess.session_id,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=settings.session_absolute_timeout_seconds,
        path="/",
    )

    return UserProfileResponse(
        username=user.username,
        email=user.email,
        display_name=user.display_name,
        role=user.role,
        must_change_password=user.must_change_password,
        csrf_token=sess.csrf_token,
        last_login_at=user.last_login_at,
    )


@app.post("/api/v1/auth/change-password", response_model=UserProfileResponse)
def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    response: Response,
    session_and_user: tuple[CpSession, CpUser] = Depends(get_current_session_and_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    sess, user = session_and_user
    csrf_header = request.headers.get("X-CSRF-Token", "")
    if not csrf_header or not secrets.compare_digest(csrf_header, sess.csrf_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF token missing or invalid")

    if not verify_password(user.password_hash, payload.current_password):
        record_audit_log(
            db,
            actor_username=user.username,
            actor_role=user.role,
            action_type="password_change_failed",
            reason="Current password verification failed",
            source_ip=get_client_ip(request),
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")

    if payload.current_password == payload.new_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must be different from the current/bootstrap password",
        )

    user.password_hash = hash_password(payload.new_password)
    user.must_change_password = False
    user.password_changed_at = utcnow()
    sess.revoked = True
    db.commit()

    new_sess = create_user_session(db, user, settings)
    record_audit_log(
        db,
        actor_username=user.username,
        actor_role=user.role,
        action_type="password_changed",
        reason="User rotated password and cleared first-login forced change flag",
        source_ip=get_client_ip(request),
    )

    response.set_cookie(
        key=settings.cookie_name,
        value=new_sess.session_id,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=settings.session_absolute_timeout_seconds,
        path="/",
    )

    return UserProfileResponse(
        username=user.username,
        email=user.email,
        display_name=user.display_name,
        role=user.role,
        must_change_password=user.must_change_password,
        csrf_token=new_sess.csrf_token,
        last_login_at=user.last_login_at,
    )


@app.post("/api/v1/auth/logout")
def logout(
    request: Request,
    response: Response,
    session_and_user: tuple[CpSession, CpUser] = Depends(get_current_session_and_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    sess, user = session_and_user
    csrf_header = request.headers.get("X-CSRF-Token", "")
    if not csrf_header or not secrets.compare_digest(csrf_header, sess.csrf_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF token missing or invalid")

    sess.revoked = True
    db.commit()
    record_audit_log(
        db,
        actor_username=user.username,
        actor_role=user.role,
        action_type="logout",
        reason="User signed out",
        source_ip=get_client_ip(request),
    )
    response.delete_cookie(key=settings.cookie_name, path="/")
    return {"status": "logged_out"}


@app.post("/api/v1/auth/users/{username}/unlock")
def unlock_user(
    username: str,
    payload: UnlockUserRequest,
    request: Request,
    architect: CpUser = Depends(require_architect),
    db: Session = Depends(get_db),
):
    target_user = db.scalar(select(CpUser).where(CpUser.username == username.lower()))
    if not target_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    target_user.failed_login_attempts = 0
    target_user.locked_until = None
    db.commit()
    record_audit_log(
        db,
        actor_username=architect.username,
        actor_role=architect.role,
        action_type="account_unlocked",
        reason=payload.reason,
        source_ip=get_client_ip(request),
        details={"unlocked_username": target_user.username},
    )
    return {"status": "unlocked", "username": target_user.username}


@app.get("/api/v1/me", response_model=UserProfileResponse)
def get_me(
    session_and_user: tuple[CpSession, CpUser] = Depends(get_current_session_and_user),
):
    sess, user = session_and_user
    return UserProfileResponse(
        username=user.username,
        email=user.email,
        display_name=user.display_name,
        role=user.role,
        must_change_password=user.must_change_password,
        csrf_token=sess.csrf_token,
        last_login_at=user.last_login_at,
    )


# ---------------------------------------------------------------------------
# 2. Resource Kind Catalog (`ADR-GLB-009`)
# ---------------------------------------------------------------------------


@app.get("/api/v1/kinds")
def list_kinds(
    _user: CpUser = Depends(require_active_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    kinds = db.scalars(select(ResourceKind).order_by(ResourceKind.kind.asc())).all()
    return {
        "kinds": [
            {
                "kind": k.kind,
                "cloud": k.cloud,
                "parent_kind": k.parent_kind,
                "display_name": k.display_name,
                "schema_uri": k.schema_uri,
                "schema_version": k.schema_version,
                "tf_module_source": k.tf_module_source,
                "tfvars_collection": k.tfvars_collection,
                "tf_address_template": k.tf_address_template,
                "opa_package": k.opa_package,
                "approval_gate_key": k.approval_gate_key,
                "drift_ignore_paths": k.drift_ignore_paths,
                "enabled": k.enabled,
            }
            for k in kinds
        ]
    }


# ---------------------------------------------------------------------------
# 3. Requests & Intake Submissions (`POST /api/v1/requests`, `GET /api/v1/requests/{id}`)
# ---------------------------------------------------------------------------


@app.post("/api/v1/requests", status_code=status.HTTP_201_CREATED)
@app.post("/api/v1/submissions", status_code=status.HTTP_201_CREATED)
def create_request(
    payload: CreateRequestPayload,
    request: Request,
    user: CpUser = Depends(require_active_user),
    db: Session = Depends(get_db),
    opa_client: OpaClient = Depends(get_opa_client),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    result = submit_resource_request(
        db,
        payload=payload,
        actor=user,
        opa_client=opa_client,
        settings=settings,
    )
    record_audit_log(
        db,
        actor_username=user.username,
        actor_role=user.role,
        action_type="request_submitted",
        reason=f"Submitted {payload.action} request for {payload.kind}",
        source_ip=get_client_ip(request),
        resource_id=uuid.UUID(result["resource_id"]),
        request_id=uuid.UUID(result["request_id"]),
        approval_id=uuid.UUID(result["approval"]["approval_id"]) if result.get("approval") else None,
        details={"kind": payload.kind, "action": payload.action, "name": result["resource"]["name"]},
    )
    return result


@app.get("/api/v1/requests")
def list_requests(
    kind: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    _user: CpUser = Depends(require_active_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    stmt = select(ResourceRequest).order_by(ResourceRequest.submitted_at.desc())
    if kind:
        stmt = stmt.where(ResourceRequest.kind == kind)
    if status_filter:
        stmt = stmt.where(ResourceRequest.status == status_filter)
    rows = db.scalars(stmt).all()
    return {"requests": [get_request_detail(db, r.request_id) for r in rows]}


@app.get("/api/v1/requests/{request_id}")
def get_request(
    request_id: uuid.UUID,
    _user: CpUser = Depends(require_active_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return get_request_detail(db, request_id)


# ---------------------------------------------------------------------------
# 4. Approvals Endpoints (`ADR-BP-003`, `gcs_bucket_owner` gate, Temporal start)
# ---------------------------------------------------------------------------


@app.get("/api/v1/approvals")
def list_approvals(
    status_filter: str | None = Query(default=None, alias="status"),
    _user: CpUser = Depends(require_active_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    stmt = select(Approval).order_by(Approval.created_at.desc())
    if status_filter:
        stmt = stmt.where(Approval.status == status_filter.upper())
    approvals = db.scalars(stmt).all()
    return {
        "approvals": [get_request_detail(db, a.request_id)["approval"] | {"request_id": str(a.request_id)} for a in approvals]
    }


@app.get("/api/v1/approvals/{approval_id}")
def get_approval(
    approval_id: uuid.UUID,
    _user: CpUser = Depends(require_active_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    apr = db.scalar(select(Approval).where(Approval.approval_id == approval_id))
    if apr is None:
        apr = db.scalar(select(Approval).where(Approval.request_id == approval_id))
    if apr is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval not found")
    return get_request_detail(db, apr.request_id)


@app.post("/api/v1/approvals/{approval_id}/decisions")
@app.post("/api/v1/requests/{approval_id}/approve")
@app.post("/api/v1/requests/{approval_id}/decisions")
async def submit_approval_decision(
    approval_id: uuid.UUID,
    decision_input: ApprovalDecisionInput,
    request: Request,
    user: CpUser = Depends(require_approver_role),
    db: Session = Depends(get_db),
    opa_client: OpaClient = Depends(get_opa_client),
    temporal_bridge: TemporalBridge = Depends(get_temporal_bridge),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    result = await record_approval_decision(
        db,
        request_or_approval_id=approval_id,
        decision_input=decision_input,
        actor=user,
        opa_client=opa_client,
        temporal_bridge=temporal_bridge,
        settings=settings,
    )
    record_audit_log(
        db,
        actor_username=user.username,
        actor_role=user.role,
        action_type=f"approval_{decision_input.status}",
        reason=decision_input.comment or f"Approval decision: {decision_input.status}",
        source_ip=get_client_ip(request),
        resource_id=uuid.UUID(result["resource_id"]),
        request_id=uuid.UUID(result["request_id"]),
        approval_id=uuid.UUID(result["approval"]["approval_id"]) if result.get("approval") else None,
        details={
            "decision_status": decision_input.status,
            "approval_status": result["approval"]["status"] if result.get("approval") else None,
        },
    )
    return result


# ---------------------------------------------------------------------------
# 5. Resources & Status View (`idp.v_resource_status`, `idp.resource_observed`, `idp.drift_finding`)
# ---------------------------------------------------------------------------


def _query_v_resource_status(db: Session, resource_id: uuid.UUID | None = None) -> list[dict[str, Any]]:
    sql = """
        SELECT resource_id, resource_key, kind, name, apm_id,
               project_id, lob, lifecycle, gate, sync_status,
               request_id, action, request_status, submitted_at,
               approval_id, approval_status, decided_at,
               expected_revision_no, expected_revision_status,
               exists_in_cloud, observed_changed_at, open_drift_count
        FROM idp.v_resource_status
    """
    params: dict[str, Any] = {}
    if resource_id is not None:
        sql += " WHERE resource_id = :resource_id"
        params["resource_id"] = resource_id
    sql += " ORDER BY submitted_at DESC NULLS LAST"
    rows = db.execute(text(sql), params).mappings().all()
    items = []
    for r in rows:
        items.append(
            {
                "resource_id": str(r["resource_id"]),
                "resource_key": r["resource_key"],
                "kind": r["kind"],
                "name": r["name"],
                "apm_id": r["apm_id"],
                "project_id": r["project_id"],
                "lob": r["lob"],
                "lifecycle": r["lifecycle"],
                "gate": r["gate"],
                "sync_status": r["sync_status"],
                "request_id": str(r["request_id"]) if r["request_id"] else None,
                "action": r["action"],
                "request_status": r["request_status"],
                "submitted_at": r["submitted_at"].isoformat() if r["submitted_at"] else None,
                "approval_id": str(r["approval_id"]) if r["approval_id"] else None,
                "approval_status": r["approval_status"],
                "decided_at": r["decided_at"].isoformat() if r["decided_at"] else None,
                "expected_revision_no": r["expected_revision_no"],
                "expected_revision_status": r["expected_revision_status"],
                "exists_in_cloud": r["exists_in_cloud"],
                "observed_changed_at": r["observed_changed_at"].isoformat() if r["observed_changed_at"] else None,
                "open_drift_count": int(r["open_drift_count"] or 0),
            }
        )
    return items


@app.get("/api/v1/resources")
@app.get("/api/v1/status")
def list_resources(
    _user: CpUser = Depends(require_active_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return {"resources": _query_v_resource_status(db)}


@app.get("/api/v1/resources/{resource_id}")
def get_resource(
    resource_id: uuid.UUID,
    _user: CpUser = Depends(require_active_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    statuses = _query_v_resource_status(db, resource_id)
    if not statuses:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found")
    status_row = statuses[0]

    observed = db.scalar(select(ResourceObserved).where(ResourceObserved.resource_id == resource_id))
    drifts = db.scalars(
        select(DriftFinding)
        .where(DriftFinding.resource_id == resource_id)
        .order_by(DriftFinding.detected_at.desc())
    ).all()

    return {
        "status": status_row,
        "observed": {
            "exists_in_cloud": observed.exists_in_cloud,
            "cloud_resource_id": observed.cloud_resource_id,
            "projection": observed.projection,
            "projection_sha256": observed.projection_sha256,
            "changed_at": observed.changed_at.isoformat() if observed.changed_at else None,
        }
        if observed
        else None,
        "drift_findings": [
            {
                "drift_id": str(d.drift_id),
                "drift_kind": d.drift_kind,
                "attribute_path": d.attribute_path,
                "expected_value": d.expected_value,
                "observed_value": d.observed_value,
                "severity": d.severity,
                "guardrail_rule_id": d.guardrail_rule_id,
                "status": d.status,
                "resolution": d.resolution,
                "detected_at": d.detected_at.isoformat() if d.detected_at else None,
            }
            for d in drifts
        ],
    }


# ---------------------------------------------------------------------------
# 6. State Unit Kill-Switch Endpoints (`INV-9`: freeze / unfreeze)
# ---------------------------------------------------------------------------


@app.post("/api/v1/state-units/{state_unit_id}/freeze")
def freeze_state_unit(
    state_unit_id: uuid.UUID,
    payload: StateUnitFreezeRequest,
    request: Request,
    user: CpUser = Depends(require_approver_role),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    su = db.scalar(select(StateUnit).where(StateUnit.state_unit_id == state_unit_id))
    if su is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="State unit not found")
    su.status = "frozen"
    db.add(
        GateEvent(
            state_unit_id=su.state_unit_id,
            gate="EXPECTED",
            event_type="state_unit.frozen",
            actor=f"user:{user.email}",
            detail={"reason": payload.reason},
        )
    )
    db.commit()
    record_audit_log(
        db,
        actor_username=user.username,
        actor_role=user.role,
        action_type="state_unit_frozen",
        reason=payload.reason,
        source_ip=get_client_ip(request),
        details={"state_unit_id": str(su.state_unit_id), "scope_id": su.scope_id},
    )
    return {"state_unit_id": str(su.state_unit_id), "scope_id": su.scope_id, "status": su.status}


@app.post("/api/v1/state-units/{state_unit_id}/unfreeze")
def unfreeze_state_unit(
    state_unit_id: uuid.UUID,
    payload: StateUnitFreezeRequest,
    request: Request,
    user: CpUser = Depends(require_approver_role),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    su = db.scalar(select(StateUnit).where(StateUnit.state_unit_id == state_unit_id))
    if su is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="State unit not found")
    su.status = "active"
    db.add(
        GateEvent(
            state_unit_id=su.state_unit_id,
            gate="EXPECTED",
            event_type="state_unit.unfrozen",
            actor=f"user:{user.email}",
            detail={"reason": payload.reason},
        )
    )
    db.commit()
    record_audit_log(
        db,
        actor_username=user.username,
        actor_role=user.role,
        action_type="state_unit_unfrozen",
        reason=payload.reason,
        source_ip=get_client_ip(request),
        details={"state_unit_id": str(su.state_unit_id), "scope_id": su.scope_id},
    )
    return {"state_unit_id": str(su.state_unit_id), "scope_id": su.scope_id, "status": su.status}


# ---------------------------------------------------------------------------
# 7. Audit Endpoints (`idp.gate_event` + `idp.cp_audit_log` + `idp.policy_evaluation`)
# ---------------------------------------------------------------------------


@app.get("/api/v1/audit")
def list_audit_events(
    resource_id: uuid.UUID | None = Query(default=None),
    request_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    _user: CpUser = Depends(require_active_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    gate_stmt = select(GateEvent).order_by(GateEvent.occurred_at.desc()).limit(limit)
    audit_stmt = select(CpAuditLog).order_by(CpAuditLog.occurred_at.desc()).limit(limit)
    policy_stmt = select(PolicyEvaluation).order_by(PolicyEvaluation.evaluated_at.desc()).limit(limit)

    if resource_id is not None:
        gate_stmt = gate_stmt.where(GateEvent.resource_id == resource_id)
        audit_stmt = audit_stmt.where(CpAuditLog.resource_id == resource_id)
    if request_id is not None:
        gate_stmt = gate_stmt.where(GateEvent.request_id == request_id)
        audit_stmt = audit_stmt.where(CpAuditLog.request_id == request_id)
        policy_stmt = policy_stmt.where(PolicyEvaluation.request_id == request_id)

    gate_events = db.scalars(gate_stmt).all()
    audit_logs = db.scalars(audit_stmt).all()
    policy_evals = db.scalars(policy_stmt).all()

    return {
        "gate_events": [
            {
                "event_id": g.event_id,
                "occurred_at": g.occurred_at.isoformat() if g.occurred_at else None,
                "state_unit_id": str(g.state_unit_id) if g.state_unit_id else None,
                "resource_id": str(g.resource_id) if g.resource_id else None,
                "request_id": str(g.request_id) if g.request_id else None,
                "gate": g.gate,
                "event_type": g.event_type,
                "actor": g.actor,
                "detail": g.detail,
                "published_at": g.published_at.isoformat() if g.published_at else None,
            }
            for g in gate_events
        ],
        "audit_logs": [
            {
                "audit_id": str(a.audit_id),
                "occurred_at": a.occurred_at.isoformat() if a.occurred_at else None,
                "actor_username": a.actor_username,
                "actor_role": a.actor_role,
                "source_ip": a.source_ip,
                "action_type": a.action_type,
                "resource_id": str(a.resource_id) if a.resource_id else None,
                "request_id": str(a.request_id) if a.request_id else None,
                "approval_id": str(a.approval_id) if a.approval_id else None,
                "reason": a.reason,
                "details": a.details,
            }
            for a in audit_logs
        ],
        "policy_evaluations": [
            {
                "evaluation_id": str(p.evaluation_id),
                "stage": p.stage,
                "request_id": str(p.request_id) if p.request_id else None,
                "revision_id": str(p.revision_id) if p.revision_id else None,
                "opa_package": p.opa_package,
                "bundle_revision": p.bundle_revision,
                "input_sha256": p.input_sha256,
                "decision": p.decision,
                "violations": p.violations,
                "mutations": p.mutations,
                "evaluated_at": p.evaluated_at.isoformat() if p.evaluated_at else None,
            }
            for p in policy_evals
        ],
    }
