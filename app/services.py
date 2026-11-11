"""Core business logic for Gate 1 (`Requested`) intake normalization, OPA policy evaluation,
and Gate 2 (`Approved`) role-based approval gate orchestration (`ADR-GLB-003`, `ADR-GLB-006..009`,
`ADR-BP-003`, `ADR-SVC-001`)."""

from __future__ import annotations

import copy
import uuid
from datetime import timedelta
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import Settings, get_settings
from .models import (
    ApmAlias,
    Approval,
    ApprovalDecision,
    ApprovalGateConfig,
    CpUser,
    GateEvent,
    LifecycleTask,
    PolicyEvaluation,
    Resource,
    ResourceKind,
    ResourceRequest,
    StateUnit,
    Submission,
    utcnow,
)
from .naming import (
    build_gcs_bucket_name,
    canonical_sha256,
    compute_canonical_labels,
    generate_random_suffix,
    normalize_data_sensitivity,
    normalize_environment,
    normalize_lob,
    scan_for_secrets,
    validate_and_normalize_apm_id,
    validate_gcs_bucket_name,
)
from .opa_client import OpaClient
from .schemas import ApprovalDecisionInput, CreateRequestPayload
from .temporal_bridge import TemporalBridge


def _resolve_app_alias_and_tier(db: Session, apm_id: str, user_labels: dict[str, Any]) -> tuple[str, str]:
    alias_row = db.scalar(select(ApmAlias).where(ApmAlias.apm_id == apm_id))
    if alias_row is not None:
        return alias_row.alias, alias_row.app_tier or "2"
    fallback_app = str(user_labels.get("app") or "orders").strip().lower()
    return fallback_app, "2"


def _resolve_or_create_state_unit(
    db: Session,
    *,
    project_id: str,
    lob: str,
    environment: str,
    apm_id: str,
    settings: Settings,
) -> StateUnit:
    su = db.scalar(select(StateUnit).where(StateUnit.cloud == "gcp", StateUnit.scope_id == project_id))
    if su is not None:
        return su
    su = StateUnit(
        cloud="gcp",
        scope_type="project",
        scope_id=project_id,
        lob=lob,
        environment=environment,
        apm_id=apm_id,
        state_bucket=settings.state_bucket,
        state_prefix=f"projects/{project_id}",
        executor_identity=f"idp-tf@{project_id}.iam.gserviceaccount.com",
        status="active",
    )
    db.add(su)
    db.flush()
    return su


def _evaluate_skip_condition(skip_expr: str | None, approved_doc: dict[str, Any]) -> bool:
    """Evaluate gate approver `skip_condition` from `idp.approval_gate_config` (`ADR-BP-003`)."""
    if not skip_expr:
        return False
    meta = approved_doc.get("metadata", {})
    env = meta.get("environment", "nonprod")
    app_tier = meta.get("resolved", {}).get("app_tier", "2")
    if "metadata.environment not in ('prod')" in skip_expr and "app_tier != '1'" in skip_expr:
        return env != "prod" and str(app_tier) != "1"
    return False


def submit_resource_request(
    db: Session,
    *,
    payload: CreateRequestPayload,
    actor: CpUser,
    opa_client: OpaClient,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Process a submission into Gate 1 (`Requested`), evaluate OPA (`stage='requested'`),
    and initialize Gate 2 (`idp.approval` + `idp.approval_decision` rows in `PENDING`)."""
    cfg = settings or get_settings()

    raw_dict = payload.model_dump(exclude_none=True)
    secret_paths = scan_for_secrets(raw_dict)
    if secret_paths:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "rule_id": "INV-001",
                "message": f"INV-1 violation: secret keys are forbidden in requests: {secret_paths}",
            },
        )

    # 1. Validate & normalize metadata (`ADR-SVC-001 REQ-2`, `ADR-GLB-006`)
    try:
        apm_id = validate_and_normalize_apm_id(payload.metadata.apm_id)
        env = normalize_environment(payload.metadata.environment)
        lob = normalize_lob(payload.metadata.lob)
        data_sensitivity = normalize_data_sensitivity(payload.metadata.data_sensitivity)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    requested_by = (payload.metadata.requested_by or actor.email or f"{actor.username}@example.com").strip()
    idempotency_key = payload.idempotency_key or f"{payload.channel}:{uuid.uuid4()}"

    # 2. Check idempotency deduplication on `(apm_id, idempotency_key)` (`ADR-GLB-004 REQ-4`)
    existing_sub = db.scalar(
        select(Submission).where(
            Submission.apm_id == apm_id,
            Submission.idempotency_key == idempotency_key,
        )
    )
    if existing_sub is not None:
        existing_req = db.scalar(
            select(ResourceRequest).where(ResourceRequest.submission_id == existing_sub.submission_id)
        )
        if existing_req is not None:
            return get_request_detail(db, existing_req.request_id)

    # 3. Load ResourceKind from `idp.resource_kind` (`ADR-GLB-009`)
    kind_row = db.scalar(
        select(ResourceKind).where(ResourceKind.kind == payload.kind, ResourceKind.enabled == True)  # noqa: E712
    )
    if kind_row is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported or disabled resource kind '{payload.kind}'",
        )

    user_labels = dict(payload.metadata.labels or {})
    if "environmentsubtype" in user_labels:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "rule_id": "LBL-001",
                "message": "LBL-001: 'environmentsubtype' label is dropped and forbidden everywhere; use 'environmenttype' ('nonprod' | 'prod')",
            },
        )

    app_alias, _ = _resolve_app_alias_and_tier(db, apm_id, user_labels)
    project_id = payload.metadata.project_id.strip()

    # 4. Resolve or draw bucket name (`GCS-NAME-001..003`)
    spec_in = copy.deepcopy(payload.spec)
    # Strip internal documentation note keys if caller sent fixture directly
    spec_in.pop("_lifecycle_rules_note", None)
    for acc in spec_in.get("access", []):
        if isinstance(acc, dict):
            acc.pop("_source_gap", None)

    action = payload.action
    existing_resource: Resource | None = None
    if payload.resource_id:
        existing_resource = db.scalar(select(Resource).where(Resource.resource_id == uuid.UUID(payload.resource_id)))

    bucket_name = spec_in.get("name")
    purpose_token = spec_in.pop("purpose_token", None)
    if not bucket_name and payload.kind == "gcs_bucket":
        if not purpose_token:
            raw_purpose = str(spec_in.get("purpose", "landing")).strip().lower().split()[0]
            purpose_token = raw_purpose
        # Draw up to max_attempts (5) random 4-char suffixes (`GCS-NAME-003`)
        for _ in range(5):
            candidate = build_gcs_bucket_name(lob, env, app_alias, purpose_token, generate_random_suffix())
            collision = db.scalar(
                select(Resource).where(Resource.kind == "gcs_bucket", Resource.name == candidate)
            )
            if collision is None:
                bucket_name = candidate
                break
        if not bucket_name:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="GCS-NAME-003: failed to draw a unique 4-char suffix after 5 attempts",
            )
        spec_in["name"] = bucket_name

    if not bucket_name:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="spec.name is required")

    # Check existing resource on update/delete
    if existing_resource is None and action in {"update", "delete"}:
        existing_resource = db.scalar(
            select(Resource).where(Resource.kind == payload.kind, Resource.name == bucket_name)
        )

    existing_name_for_check = existing_resource.name if existing_resource else None

    if payload.kind == "gcs_bucket":
        valid_name, rule_id, reason = validate_gcs_bucket_name(
            bucket_name,
            lob=lob,
            env=env,
            app=app_alias,
            action=action,
            existing_name=existing_name_for_check,
        )
        if not valid_name:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"rule_id": rule_id, "message": f"{rule_id}: {reason}"},
            )
        if action == "create":
            global_dup = db.scalar(
                select(Resource).where(Resource.kind == "gcs_bucket", Resource.name == bucket_name)
            )
            if global_dup is not None and (
                not payload.resource_id or global_dup.resource_id != uuid.UUID(payload.resource_id)
            ):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "rule_id": "GCS-NAME-003",
                        "message": f"GCS-NAME-003: bucket name '{bucket_name}' already exists in idp.resource",
                    },
                )

    # Ensure lifecycle_rules defaults to [] (NONE) per ADR-SVC-001 REQ-3
    if "lifecycle_rules" not in spec_in or spec_in["lifecycle_rules"] is None:
        spec_in["lifecycle_rules"] = []
    if "location" not in spec_in:
        spec_in["location"] = "us-east1"
    if "storage_class" not in spec_in:
        spec_in["storage_class"] = "STANDARD"
    if "versioning" not in spec_in:
        spec_in["versioning"] = False

    # Build canonical `requested.document` matching `specs/examples/gcs_bucket.gates.json`
    normalized_metadata: dict[str, Any] = {
        "apm_id": apm_id,
        "project_id": project_id,
        "environment": env,
        "lob": lob,
        "data_sensitivity": data_sensitivity,
        "data_classification": payload.metadata.data_classification.strip().lower(),
        "owner": payload.metadata.owner.strip(),
        "shared_mailbox": payload.metadata.shared_mailbox.strip(),
        "requested_by": requested_by,
        "cost_center": payload.metadata.cost_center.strip(),
        "tenancy": payload.metadata.tenancy.strip().lower(),
        "labels": user_labels,
    }
    if payload.metadata.extensions:
        normalized_metadata["extensions"] = payload.metadata.extensions

    requested_doc: dict[str, Any] = {
        "api_version": payload.api_version,
        "kind": payload.kind,
        "action": action,
        "metadata": normalized_metadata,
        "spec": spec_in,
    }

    # 5. Resolve StateUnit and Resource rows
    state_unit = _resolve_or_create_state_unit(
        db,
        project_id=project_id,
        lob=lob,
        environment=env,
        apm_id=apm_id,
        settings=cfg,
    )

    res_uuid = (
        existing_resource.resource_id
        if existing_resource
        else (uuid.UUID(payload.resource_id) if payload.resource_id else uuid.uuid4())
    )

    # 6. Evaluate OPA at `stage = 'requested'` BEFORE committing (`WI-003`)
    opa_req_input = {
        "stage": "requested",
        "cloud": "gcp",
        "app_alias": app_alias,
        "resource_id": str(res_uuid),
        "existing_name": existing_name_for_check or "",
        "document": requested_doc,
    }
    raw_opa_eval = opa_client.evaluate_raw(kind_row.opa_package, opa_req_input)
    if raw_opa_eval.get("decision") == "deny":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "decision": "deny",
                "stage": "requested",
                "violations": raw_opa_eval.get("violations", []),
            },
        )

    # 7. Persist Submission, Resource, Request, PolicyEvaluation(stage='requested'), Approval, ApprovalDecision, GateEvent
    sub_uuid = uuid.UUID(payload.submission_id) if payload.submission_id else uuid.uuid4()
    req_uuid = uuid.UUID(payload.request_id) if payload.request_id else uuid.uuid4()
    apr_uuid = uuid.UUID(payload.approval_id) if payload.approval_id else uuid.uuid4()

    raw_payload_sha = canonical_sha256(raw_dict)
    requested_spec_sha = canonical_sha256(requested_doc)

    submission_row = Submission(
        submission_id=sub_uuid,
        channel=payload.channel,
        source_ref=payload.source_ref,
        apm_id=apm_id,
        submitted_by=requested_by,
        on_behalf_of=payload.on_behalf_of,
        idempotency_key=idempotency_key,
        raw_payload=raw_dict,
        raw_payload_sha256=raw_payload_sha,
    )
    db.add(submission_row)

    resource_key = f"gcp:{project_id}:{payload.kind}:{bucket_name}"
    tf_address = kind_row.tf_address_template.format(name=bucket_name)

    if existing_resource is None:
        resource_row = Resource(
            resource_id=res_uuid,
            state_unit_id=state_unit.state_unit_id,
            kind=payload.kind,
            name=bucket_name,
            resource_key=resource_key,
            tf_address=tf_address,
            apm_id=apm_id,
            lifecycle="proposed" if action == "create" else "active",
            gate="REQUESTED",
            sync_status="PENDING",
        )
        db.add(resource_row)
    else:
        resource_row = existing_resource
        resource_row.gate = "REQUESTED"
        resource_row.sync_status = "PENDING"
        if action == "delete":
            resource_row.lifecycle = "deleting"

    db.flush()

    base_approval_uuid = (
        uuid.UUID(payload.base_approval_id)
        if payload.base_approval_id
        else resource_row.current_approval_id
    )

    request_row = ResourceRequest(
        request_id=req_uuid,
        submission_id=sub_uuid,
        resource_id=resource_row.resource_id,
        kind=payload.kind,
        action=action,
        schema_version=kind_row.schema_version,
        requested_spec=requested_doc,
        requested_spec_sha256=requested_spec_sha,
        source_pointer="/resources/0",
        base_approval_id=base_approval_uuid if action in {"update", "delete"} else None,
        status="PENDING_APPROVAL",
        temporal_workflow_id=f"req-{req_uuid}",
        requested_by=requested_by,
    )
    db.add(request_row)
    db.flush()

    # Record `stage = 'requested'` in `idp.policy_evaluation`
    policy_eval_req_row, _ = opa_client.evaluate_and_record(
        db,
        stage="requested",
        opa_package=kind_row.opa_package,
        opa_input=opa_req_input,
        request_id=request_row.request_id,
    )

    # Pin `gate_key` and `gate_version` from `idp.approval_gate_config` (`ADR-BP-003 REQ-1`)
    gate_cfg_row = db.scalar(
        select(ApprovalGateConfig).where(
            ApprovalGateConfig.gate_key == kind_row.approval_gate_key,
            ApprovalGateConfig.enabled == True,  # noqa: E712
        )
    )
    gate_key = gate_cfg_row.gate_key if gate_cfg_row else kind_row.approval_gate_key
    gate_version = gate_cfg_row.version if gate_cfg_row else 1
    gate_cfg_json = gate_cfg_row.config if gate_cfg_row else {}

    approval_row = Approval(
        approval_id=apr_uuid,
        request_id=request_row.request_id,
        resource_id=resource_row.resource_id,
        gate_key=gate_key,
        gate_version=gate_version,
        status="PENDING",
        guardrail_trace=[],
        policy_evaluation_id=policy_eval_req_row.evaluation_id,
        temporal_workflow_id=f"apr-{request_row.request_id}",
    )
    db.add(approval_row)
    db.flush()

    resource_row.current_request_id = request_row.request_id

    # Create sequential `idp.approval_decision` rows from `approval_gate_config` (`ADR-BP-003`)
    now = utcnow()
    approvers_cfg = gate_cfg_json.get("approvers", [])
    for idx, appr in enumerate(approvers_cfg):
        appr_key = appr.get("key", f"approver_{idx}")
        ticket_field = appr.get("ticket_field")
        if ticket_field == "/metadata/owner":
            identity = normalized_metadata["owner"]
        else:
            identity = appr.get("role", appr_key)
        sla_days = int(appr.get("sla_days", 5))
        decision_row = ApprovalDecision(
            approval_id=approval_row.approval_id,
            approver_key=appr_key,
            approver_identity=identity,
            phase=idx,
            mandatory=bool(appr.get("mandatory", True)),
            status="pending",
            sla_deadline=now + timedelta(days=sla_days),
        )
        db.add(decision_row)

    # Emit append-only `idp.gate_event` (`request.submitted`)
    gate_evt = GateEvent(
        state_unit_id=state_unit.state_unit_id,
        resource_id=resource_row.resource_id,
        request_id=request_row.request_id,
        gate="REQUESTED",
        event_type="request.submitted",
        actor=f"user:{requested_by}",
        detail={
            "submission_id": str(sub_uuid),
            "action": action,
            "kind": payload.kind,
            "name": bucket_name,
            "requested_spec_sha256": requested_spec_sha,
            "policy_evaluation_id": str(policy_eval_req_row.evaluation_id),
        },
    )
    db.add(gate_evt)
    db.commit()

    return get_request_detail(db, request_row.request_id)


async def record_approval_decision(
    db: Session,
    *,
    request_or_approval_id: uuid.UUID,
    decision_input: ApprovalDecisionInput,
    actor: CpUser,
    opa_client: OpaClient,
    temporal_bridge: TemporalBridge,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Process an approver's decision (`approved` | `denied` | `escalated`), enforcing:
    - `self_approval = "deny"` (`ADR-BP-003 REQ-2`, `GR-1`)
    - Universal human approval for deletes: `auto_approved` / `AUTO_APPROVED` forbidden on `action == 'delete'` (`ADR-BP-003 REQ-5`, `GR-2`)
    - Sequential phase ordering & `skip_condition` (`ADR-BP-003 REQ-3..4`)
    - OPA evaluation at `stage = 'approved'`, computing `approved_spec`, `guardrail_trace`, `idp.lifecycle_task` rows (`ADR-GLB-007`, `ADR-SVC-001`)
    - Starting Temporal workflow `GcsBucketProvisionWorkflow` on approval (`WI-001`).
    """
    cfg = settings or get_settings()

    # Resolve Approval by approval_id or request_id
    approval_row = db.scalar(select(Approval).where(Approval.approval_id == request_or_approval_id))
    if approval_row is None:
        approval_row = db.scalar(select(Approval).where(Approval.request_id == request_or_approval_id))
    if approval_row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval or Request not found")

    if approval_row.status != "PENDING":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Approval {approval_row.approval_id} is already decided with status '{approval_row.status}'",
        )

    request_row = db.scalar(select(ResourceRequest).where(ResourceRequest.request_id == approval_row.request_id))
    assert request_row is not None
    submission_row = db.scalar(select(Submission).where(Submission.submission_id == request_row.submission_id))
    assert submission_row is not None
    resource_row = db.scalar(select(Resource).where(Resource.resource_id == approval_row.resource_id))
    assert resource_row is not None
    state_unit = db.scalar(select(StateUnit).where(StateUnit.state_unit_id == resource_row.state_unit_id))
    assert state_unit is not None
    kind_row = db.scalar(select(ResourceKind).where(ResourceKind.kind == request_row.kind))
    assert kind_row is not None

    responded_by = (decision_input.responded_by or actor.email or f"{actor.username}@example.com").strip()

    # 1. Universal rule: Never allow auto_approved on delete in ANY environment (`ADR-BP-003 REQ-5`, `ADR-GLB-007 REQ-4`)
    if decision_input.status == "auto_approved" and request_row.action == "delete":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Human approval is required for all delete requests in nonprod and prod; 'auto_approved' is forbidden (ADR-BP-003 GR-2).",
        )

    # 2. Enforce `self_approval = "deny"` (`ADR-BP-003 REQ-2`, `GR-1`)
    forbidden_self_actors = {
        request_row.requested_by.lower(),
        submission_row.submitted_by.lower(),
        actor.username.lower(),
    }
    if submission_row.on_behalf_of:
        forbidden_self_actors.add(submission_row.on_behalf_of.lower())

    if responded_by.lower() in {
        request_row.requested_by.lower(),
        submission_row.submitted_by.lower(),
        (submission_row.on_behalf_of or "").lower(),
    } or actor.username.lower() == request_row.requested_by.split("@")[0].lower():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Self-approval is denied (self_approval='deny'): requester '{request_row.requested_by}' cannot approve their own request (ADR-BP-003).",
        )

    # 3. Locate the pending ApprovalDecision row
    decisions = list(
        db.scalars(
            select(ApprovalDecision)
            .where(ApprovalDecision.approval_id == approval_row.approval_id)
            .order_by(ApprovalDecision.phase.asc())
        ).all()
    )
    if not decisions:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="No approval_decision rows found")

    target_decision: ApprovalDecision | None = None
    if decision_input.decision_id:
        target_decision = next((d for d in decisions if str(d.decision_id) == decision_input.decision_id), None)
    elif decision_input.approver_key:
        target_decision = next((d for d in decisions if d.approver_key == decision_input.approver_key), None)
    else:
        target_decision = next((d for d in decisions if d.status == "pending"), None)

    if target_decision is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Matching pending approval decision not found")

    # Enforce sequential ordering: all earlier phases must already be approved
    for earlier in decisions:
        if earlier.phase < target_decision.phase and earlier.status not in {"approved", "auto_approved"}:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Sequential approval gate: earlier approver '{earlier.approver_key}' (phase {earlier.phase}) must approve first",
            )

    # Role / identity check for `bucket_owner` / `approver` (`ADR-BP-003`)
    if target_decision.approver_key in {"bucket_owner", "data_owner"}:
        allowed_identities = {
            target_decision.approver_identity.lower(),
            actor.email.lower(),
        }
        if actor.role not in {"approver", "bucket_owner", "data_owner", "architect", "operations"} and (
            responded_by.lower() not in allowed_identities
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"User '{responded_by}' is not authorized to decide gate '{target_decision.approver_key}' for owner '{target_decision.approver_identity}'",
            )

    now = utcnow()
    target_decision.status = decision_input.status
    target_decision.responded_by = responded_by
    target_decision.response_comment = decision_input.comment
    target_decision.responded_at = now

    if decision_input.status == "denied":
        approval_row.status = "DENIED"
        approval_row.decided_at = now
        request_row.status = "DENIED"
        request_row.status_reason = decision_input.comment or "Denied by approver"
        db.add(
            GateEvent(
                state_unit_id=state_unit.state_unit_id,
                resource_id=resource_row.resource_id,
                request_id=request_row.request_id,
                gate="APPROVED",
                event_type="approval.denied",
                actor=f"user:{responded_by}",
                detail={"approval_id": str(approval_row.approval_id), "comment": decision_input.comment},
            )
        )
        db.commit()
        return get_request_detail(db, request_row.request_id)

    if decision_input.status == "escalated":
        target_decision.escalation_count += 1
        target_decision.escalated_to = "manager@example.com"
        db.commit()
        return get_request_detail(db, request_row.request_id)

    # Check if any subsequent sequential approvers can be skipped per `skip_condition`
    requested_doc = copy.deepcopy(request_row.requested_spec)
    meta = requested_doc.get("metadata", {})
    app_alias, app_tier = _resolve_app_alias_and_tier(db, meta.get("apm_id", "apm12345"), meta.get("labels", {}))

    gate_cfg_row = db.scalar(select(ApprovalGateConfig).where(ApprovalGateConfig.gate_key == approval_row.gate_key))
    gate_approvers_cfg = {
        a["key"]: a for a in (gate_cfg_row.config.get("approvers", []) if gate_cfg_row else [])
    }

    temp_resolved_doc = {
        "metadata": {
            "environment": meta.get("environment", "nonprod"),
            "resolved": {"app_tier": app_tier},
        }
    }
    for d in decisions:
        if d.status == "pending":
            acfg = gate_approvers_cfg.get(d.approver_key, {})
            if _evaluate_skip_condition(acfg.get("skip_condition"), temp_resolved_doc):
                d.status = "approved"
                d.responded_by = "system:skip_condition"
                d.response_comment = f"Skipped per skip_condition: {acfg.get('skip_condition')}"
                d.responded_at = now

    # If there are still pending mandatory approvers, commit partial progress and wait
    still_pending = [d for d in decisions if d.mandatory and d.status == "pending"]
    if still_pending:
        db.commit()
        return get_request_detail(db, request_row.request_id)

    # 4. All required approvers have approved -> Evaluate OPA at `stage = 'approved'` (`WI-003`, `ADR-GLB-007`)
    opa_approved_input: dict[str, Any] = {
        "stage": "approved",
        "cloud": "gcp",
        "app_alias": app_alias,
        "resource_id": str(resource_row.resource_id),
        "document": requested_doc,
    }
    if cfg.kms_key_placeholder:
        opa_approved_input["kms_key_name"] = cfg.kms_key_placeholder

    policy_eval_apr_row, opa_out = opa_client.evaluate_and_record(
        db,
        stage="approved",
        opa_package=kind_row.opa_package,
        opa_input=opa_approved_input,
        request_id=request_row.request_id,
    )

    if opa_out.decision == "deny":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "decision": "deny",
                "stage": "approved",
                "violations": opa_out.violations,
            },
        )

    # 5. Build canonical `approved.document` matching `specs/examples/gcs_bucket.gates.json`
    lob = meta.get("lob", "<lob>")
    env = meta.get("environment", "nonprod")
    is_legacy_import = request_row.action == "import"
    computed_labels = opa_out.computed_labels or compute_canonical_labels(
        meta, str(resource_row.resource_id), is_legacy_import=is_legacy_import
    )

    approved_doc = copy.deepcopy(requested_doc)
    approved_doc["metadata"]["labels"] = computed_labels
    approved_doc["metadata"]["resolved"] = {
        "app_tier": app_tier,
        "environment_type": env,
        "vpc_sc_perimeter": f"{lob}_{env}_restricted_perimeter",
        "cost_center_validated": True,
        "resolved_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    if request_row.kind == "gcs_bucket":
        kms_key = opa_out.resolved_kms_key or cfg.default_kms_key_name
        approved_doc["spec"].update(
            {
                "retention_days": 90,
                "retention_locked": False,
                "uniform_bucket_level_access": True,
                "public_access_prevention": "enforced",
                "kms_key_name": kms_key,
                "soft_delete_retention_days": 7,
                "force_destroy": False,
            }
        )

    approved_doc["prerequisites"] = opa_out.prerequisites
    approved_doc["post_apply"] = [
        {
            "type": "notify_owner",
            "target": meta.get("owner", ""),
        }
    ]
    decided_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    approved_doc["approval"] = {
        "request_id": str(request_row.request_id),
        "requested_spec_sha256": request_row.requested_spec_sha256,
        "policy_bundle_revision": cfg.opa_bundle_revision,
        "gate_key": approval_row.gate_key,
        "decided_at": decided_iso,
        "approvers": [
            {
                "approver_key": d.approver_key,
                "identity": d.approver_identity,
                "status": d.status,
                "responded_at": (d.responded_at or now).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
            for d in decisions
        ],
    }

    approved_spec_sha = canonical_sha256(approved_doc)

    # 6. Persist `idp.approval` fields & `guardrail_trace`
    approval_row.approved_spec = approved_doc
    approval_row.approved_spec_sha256 = approved_spec_sha
    approval_row.guardrail_trace = opa_out.guardrail_trace
    approval_row.policy_evaluation_id = policy_eval_apr_row.evaluation_id
    approval_row.status = "APPROVED"
    approval_row.decided_at = now
    approval_row.valid_until = now + timedelta(days=30)

    request_row.status = "APPROVED"
    resource_row.gate = "APPROVED"
    resource_row.current_approval_id = approval_row.approval_id

    # 7. Materialize `idp.lifecycle_task` rows (`pre_apply` and `post_apply`, `ADR-SVC-001`, `ADR-AUT-001`)
    for prereq in approved_doc.get("prerequisites", []):
        task_type = prereq["type"]
        target = prereq["target"]
        task_key = f"{task_type}:{target}"
        existing_task = db.scalar(
            select(LifecycleTask).where(
                LifecycleTask.approval_id == approval_row.approval_id,
                LifecycleTask.task_key == task_key,
            )
        )
        if existing_task is None:
            db.add(
                LifecycleTask(
                    resource_id=resource_row.resource_id,
                    approval_id=approval_row.approval_id,
                    phase="pre_apply",
                    task_type=task_type,
                    task_key=task_key,
                    spec=prereq,
                    status="PENDING",
                )
            )

    for post_task in approved_doc.get("post_apply", []):
        task_type = post_task["type"]
        target = post_task["target"]
        task_key = f"{task_type}:{target}"
        existing_task = db.scalar(
            select(LifecycleTask).where(
                LifecycleTask.approval_id == approval_row.approval_id,
                LifecycleTask.task_key == task_key,
            )
        )
        if existing_task is None:
            db.add(
                LifecycleTask(
                    resource_id=resource_row.resource_id,
                    approval_id=approval_row.approval_id,
                    phase="post_apply",
                    task_type=task_type,
                    task_key=task_key,
                    spec=post_task,
                    status="PENDING",
                )
            )

    # 8. Start Temporal workflow `GcsBucketProvisionWorkflow` on platform Temporal server (`WI-001`)
    wf_receipt = await temporal_bridge.start_gcs_bucket_provision_workflow(
        request_id=str(request_row.request_id),
        approval_id=str(approval_row.approval_id),
        resource_id=str(resource_row.resource_id),
        state_unit_id=str(state_unit.state_unit_id),
        project_id=state_unit.scope_id,
        action=request_row.action,
        approved_spec=approved_doc,
        approved_spec_sha256=approved_spec_sha,
        triggered_by=responded_by,
    )

    # 9. Emit `idp.gate_event` (`approval.granted`)
    db.add(
        GateEvent(
            state_unit_id=state_unit.state_unit_id,
            resource_id=resource_row.resource_id,
            request_id=request_row.request_id,
            gate="APPROVED",
            event_type="approval.granted",
            actor=f"user:{responded_by}",
            detail={
                "approval_id": str(approval_row.approval_id),
                "approved_spec_sha256": approved_spec_sha,
                "policy_evaluation_id": str(policy_eval_apr_row.evaluation_id),
                "guardrail_count": len(opa_out.guardrail_trace),
                "temporal_workflow": {
                    "workflow_name": wf_receipt.workflow_name,
                    "workflow_id": wf_receipt.workflow_id,
                    "namespace": wf_receipt.namespace,
                    "task_queue": wf_receipt.task_queue,
                    "dispatched": wf_receipt.dispatched,
                },
            },
        )
    )
    db.commit()

    detail = get_request_detail(db, request_row.request_id)
    detail["temporal_workflow_dispatch"] = {
        "workflow_name": wf_receipt.workflow_name,
        "workflow_id": wf_receipt.workflow_id,
        "namespace": wf_receipt.namespace,
        "task_queue": wf_receipt.task_queue,
        "dispatched": wf_receipt.dispatched,
        "note": wf_receipt.note,
    }
    return detail


def get_request_detail(db: Session, request_id: uuid.UUID) -> dict[str, Any]:
    """Fetch complete four-gate detail for a request (`requested`, `approved`, `policy_evaluations`, `decisions`, `lifecycle_tasks`)."""
    req = db.scalar(select(ResourceRequest).where(ResourceRequest.request_id == request_id))
    if req is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Request {request_id} not found")

    sub = db.scalar(select(Submission).where(Submission.submission_id == req.submission_id))
    res = db.scalar(select(Resource).where(Resource.resource_id == req.resource_id))
    apr = db.scalar(select(Approval).where(Approval.request_id == req.request_id))
    decisions = (
        list(
            db.scalars(
                select(ApprovalDecision)
                .where(ApprovalDecision.approval_id == apr.approval_id)
                .order_by(ApprovalDecision.phase.asc())
            ).all()
        )
        if apr
        else []
    )
    evals = list(
        db.scalars(
            select(PolicyEvaluation)
            .where(PolicyEvaluation.request_id == req.request_id)
            .order_by(PolicyEvaluation.evaluated_at.asc())
        ).all()
    )
    tasks = (
        list(
            db.scalars(
                select(LifecycleTask)
                .where(LifecycleTask.approval_id == apr.approval_id)
                .order_by(LifecycleTask.phase.asc(), LifecycleTask.task_key.asc())
            ).all()
        )
        if apr
        else []
    )

    return {
        "request_id": str(req.request_id),
        "submission_id": str(req.submission_id),
        "resource_id": str(req.resource_id),
        "kind": req.kind,
        "action": req.action,
        "schema_version": req.schema_version,
        "status": req.status,
        "status_reason": req.status_reason,
        "requested_by": req.requested_by,
        "temporal_workflow_id": req.temporal_workflow_id,
        "submitted_at": req.submitted_at.isoformat() if req.submitted_at else None,
        "updated_at": req.updated_at.isoformat() if req.updated_at else None,
        "requested": {
            "document": req.requested_spec,
            "requested_spec_sha256": req.requested_spec_sha256,
        },
        "submission": {
            "submission_id": str(sub.submission_id),
            "channel": sub.channel,
            "apm_id": sub.apm_id,
            "submitted_by": sub.submitted_by,
            "idempotency_key": sub.idempotency_key,
            "raw_payload_sha256": sub.raw_payload_sha256,
        }
        if sub
        else None,
        "resource": {
            "resource_id": str(res.resource_id),
            "resource_key": res.resource_key,
            "name": res.name,
            "tf_address": res.tf_address,
            "gate": res.gate,
            "lifecycle": res.lifecycle,
            "sync_status": res.sync_status,
        }
        if res
        else None,
        "approval": {
            "approval_id": str(apr.approval_id),
            "gate_key": apr.gate_key,
            "gate_version": apr.gate_version,
            "status": apr.status,
            "approved_spec": apr.approved_spec,
            "approved_spec_sha256": apr.approved_spec_sha256,
            "guardrail_trace": apr.guardrail_trace,
            "policy_evaluation_id": str(apr.policy_evaluation_id) if apr.policy_evaluation_id else None,
            "temporal_workflow_id": apr.temporal_workflow_id,
            "decided_at": apr.decided_at.isoformat() if apr.decided_at else None,
            "valid_until": apr.valid_until.isoformat() if apr.valid_until else None,
            "decisions": [
                {
                    "decision_id": str(d.decision_id),
                    "approver_key": d.approver_key,
                    "approver_identity": d.approver_identity,
                    "phase": d.phase,
                    "mandatory": d.mandatory,
                    "status": d.status,
                    "sla_deadline": d.sla_deadline.isoformat() if d.sla_deadline else None,
                    "responded_by": d.responded_by,
                    "response_comment": d.response_comment,
                    "responded_at": d.responded_at.isoformat() if d.responded_at else None,
                }
                for d in decisions
            ],
            "lifecycle_tasks": [
                {
                    "task_id": str(t.task_id),
                    "phase": t.phase,
                    "task_type": t.task_type,
                    "task_key": t.task_key,
                    "status": t.status,
                    "spec": t.spec,
                }
                for t in tasks
            ],
        }
        if apr
        else None,
        "policy_evaluations": [
            {
                "evaluation_id": str(e.evaluation_id),
                "stage": e.stage,
                "opa_package": e.opa_package,
                "bundle_revision": e.bundle_revision,
                "input_sha256": e.input_sha256,
                "decision": e.decision,
                "violations": e.violations,
                "mutations": e.mutations,
                "evaluated_at": e.evaluated_at.isoformat() if e.evaluated_at else None,
            }
            for e in evals
        ],
    }
