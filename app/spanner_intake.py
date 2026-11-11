"""Composite Spanner intake (`spanner-instance-with-databases`) per specs/examples/spanner.gates.json (WI-007 phase 2)."""

from __future__ import annotations

import copy
import uuid
from datetime import timedelta
from typing import Any

from fastapi import HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    Approval,
    ApprovalDecision,
    ApprovalGateConfig,
    CpUser,
    GateEvent,
    Resource,
    ResourceKind,
    ResourceRequest,
    Submission,
    StateUnit,
    utcnow,
)
from .naming import (
    canonical_sha256,
    generate_spanner_display_name,
    normalize_environment,
    normalize_lob,
    validate_spanner_database_name,
    validate_spanner_instance_name,
    validate_and_normalize_apm_id,
)
from .opa_client import OpaClient
from .services import _resolve_app_alias_and_tier, _resolve_or_create_state_unit, get_request_detail
from .config import Settings, get_settings


class CompositeSpannerSubmission(BaseModel):
    template: str = Field(default="spanner-instance-with-databases")
    template_version: str = Field(default="1.0.0")
    channel: str = Field(default="api")
    idempotency_key: str | None = None
    resources: list[dict[str, Any]]


def _format_tf_address(template: str, *, name: str, instance: str | None = None) -> str:
    if "{instance}" in template:
        return template.format(name=name, instance=instance or "")
    return template.format(name=name)


def submit_spanner_instance_with_databases(
    db: Session,
    *,
    payload: CompositeSpannerSubmission,
    actor: CpUser,
    opa_client: OpaClient,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Create one submission with linked spanner_instance (/resources/0) and spanner_database (/resources/1)."""
    if payload.template != "spanner-instance-with-databases":
        raise HTTPException(status_code=400, detail=f"Unsupported template '{payload.template}'")
    if len(payload.resources) != 2:
        raise HTTPException(status_code=422, detail="template requires exactly two resources")

    inst_doc = payload.resources[0]
    db_doc = payload.resources[1]
    if inst_doc.get("kind") != "spanner_instance" or db_doc.get("kind") != "spanner_database":
        raise HTTPException(status_code=422, detail="resources[0]=spanner_instance and resources[1]=spanner_database required")

    cfg = settings or get_settings()
    inst_meta = inst_doc["metadata"]
    apm_id = validate_and_normalize_apm_id(inst_meta["apm_id"])
    env = normalize_environment(inst_meta["environment"])
    lob = normalize_lob(inst_meta["lob"])
    project_id = inst_meta["project_id"].strip()
    app_alias, _ = _resolve_app_alias_and_tier(db, apm_id, inst_meta.get("labels") or {})

    inst_spec = copy.deepcopy(inst_doc["spec"])
    db_spec = copy.deepcopy(db_doc["spec"])
    inst_name = inst_spec["name"]
    db_name = db_spec["name"]
    db_spec["instance"] = inst_name

    valid, rule, reason = validate_spanner_instance_name(inst_name, lob=lob, env=env, app=app_alias)
    if not valid:
        raise HTTPException(status_code=422, detail={"rule_id": rule, "message": reason})

    valid_db, rule_db, reason_db = validate_spanner_database_name(db_name, app=app_alias)
    if not valid_db:
        raise HTTPException(status_code=422, detail={"rule_id": rule_db, "message": reason_db})

    inst_spec["display_name"] = inst_spec.get("display_name") or generate_spanner_display_name(
        lob, app_alias, None, env
    )
    inst_spec.setdefault("config", "regional-us-east1")
    inst_spec.setdefault("location", "us-east1")

    state_unit = _resolve_or_create_state_unit(
        db, project_id=project_id, lob=lob, environment=env, apm_id=apm_id, settings=cfg
    )

    sub_uuid = uuid.uuid4()
    requested_by = inst_meta.get("requested_by") or actor.email or "requester@example.com"
    idempotency_key = payload.idempotency_key or f"ui:{uuid.uuid4()}"
    raw_payload = payload.model_dump()
    submission_row = Submission(
        submission_id=sub_uuid,
        channel=payload.channel,
        apm_id=apm_id,
        submitted_by=requested_by,
        idempotency_key=idempotency_key,
        raw_payload=raw_payload,
        raw_payload_sha256=canonical_sha256(raw_payload),
    )
    db.add(submission_row)

    inst_uuid = uuid.uuid4()
    db_uuid = uuid.uuid4()
    kinds = {
        "spanner_instance": db.scalar(
            select(ResourceKind).where(ResourceKind.kind == "spanner_instance", ResourceKind.enabled == True)  # noqa: E712
        ),
        "spanner_database": db.scalar(
            select(ResourceKind).where(ResourceKind.kind == "spanner_database", ResourceKind.enabled == True)  # noqa: E712
        ),
    }
    if not kinds["spanner_instance"] or not kinds["spanner_database"]:
        raise HTTPException(status_code=500, detail="spanner resource kinds are not seeded")

    inst_resource = Resource(
        resource_id=inst_uuid,
        state_unit_id=state_unit.state_unit_id,
        kind="spanner_instance",
        name=inst_name,
        resource_key=f"gcp:{project_id}:spanner_instance:{inst_name}",
        tf_address=_format_tf_address(kinds["spanner_instance"].tf_address_template, name=inst_name),
        apm_id=apm_id,
        lifecycle="proposed",
        gate="REQUESTED",
        sync_status="PENDING",
    )
    db_resource = Resource(
        resource_id=db_uuid,
        state_unit_id=state_unit.state_unit_id,
        kind="spanner_database",
        name=db_name,
        parent_resource_id=inst_uuid,
        resource_key=f"gcp:{project_id}:spanner_database:{inst_name}/{db_name}",
        tf_address=_format_tf_address(
            kinds["spanner_database"].tf_address_template,
            name=db_name,
            instance=inst_name,
        ),
        apm_id=apm_id,
        lifecycle="proposed",
        gate="REQUESTED",
        sync_status="PENDING",
    )
    db.add(inst_resource)
    db.add(db_resource)
    db.flush()

    request_ids: list[uuid.UUID] = []
    for idx, (kind, spec, meta, res_row) in enumerate(
        [
            ("spanner_instance", inst_spec, inst_meta, inst_resource),
            ("spanner_database", db_spec, db_doc["metadata"], db_resource),
        ]
    ):
        req_uuid = uuid.uuid4()
        requested_doc = {
            "api_version": "idp.spp/v1",
            "kind": kind,
            "action": "create",
            "metadata": {**meta, "apm_id": apm_id, "environment": env, "lob": lob, "project_id": project_id},
            "spec": spec,
        }
        opa_input = {
            "stage": "requested",
            "cloud": "gcp",
            "app_alias": app_alias,
            "resource_id": str(res_row.resource_id),
            "document": requested_doc,
        }
        kind_row = kinds[kind]
        raw_opa = opa_client.evaluate_raw(kind_row.opa_package, opa_input)
        if raw_opa.get("decision") == "deny":
            raise HTTPException(
                status_code=422,
                detail={"stage": "requested", "kind": kind, "violations": raw_opa.get("violations", [])},
            )

        req_row = ResourceRequest(
            request_id=req_uuid,
            submission_id=sub_uuid,
            resource_id=res_row.resource_id,
            kind=kind,
            action="create",
            schema_version=kind_row.schema_version,
            requested_spec=requested_doc,
            requested_spec_sha256=canonical_sha256(requested_doc),
            source_pointer=f"/resources/{idx}",
            status="PENDING_APPROVAL",
            temporal_workflow_id=f"req-{req_uuid}",
            requested_by=requested_by,
        )
        db.add(req_row)
        opa_client.evaluate_and_record(
            db,
            stage="requested",
            opa_package=kind_row.opa_package,
            opa_input=opa_input,
            request_id=req_row.request_id,
        )

        gate_cfg_row = db.scalar(
            select(ApprovalGateConfig).where(
                ApprovalGateConfig.gate_key == kind_row.approval_gate_key,
                ApprovalGateConfig.enabled == True,  # noqa: E712
            )
        )
        gate_cfg_json = gate_cfg_row.config if gate_cfg_row else {}

        apr_uuid = uuid.uuid4()
        approval_row = Approval(
            approval_id=apr_uuid,
            request_id=req_row.request_id,
            resource_id=res_row.resource_id,
            gate_key=kind_row.approval_gate_key,
            gate_version=gate_cfg_row.version if gate_cfg_row else 1,
            status="PENDING",
            guardrail_trace=[],
            temporal_workflow_id=f"apr-{req_uuid}",
        )
        db.add(approval_row)
        now = utcnow()
        for phase, appr in enumerate(gate_cfg_json.get("approvers", [])):
            db.add(
                ApprovalDecision(
                    approval_id=apr_uuid,
                    approver_key=appr.get("key", f"approver_{phase}"),
                    approver_identity=meta.get("owner") if appr.get("ticket_field") == "/metadata/owner" else appr.get("role", "approver"),
                    phase=phase,
                    mandatory=bool(appr.get("mandatory", True)),
                    status="pending",
                    sla_deadline=now + timedelta(days=int(appr.get("sla_days", 5))),
                )
            )
        res_row.current_request_id = req_row.request_id
        db.add(
            GateEvent(
                state_unit_id=state_unit.state_unit_id,
                resource_id=res_row.resource_id,
                request_id=req_row.request_id,
                gate="REQUESTED",
                event_type="request.submitted",
                actor=f"user:{requested_by}",
                detail={"submission_id": str(sub_uuid), "source_pointer": f"/resources/{idx}", "kind": kind},
            )
        )
        request_ids.append(req_uuid)

    db.commit()
    return {
        "submission_id": str(sub_uuid),
        "request_ids": [str(r) for r in request_ids],
        "instance_request": get_request_detail(db, request_ids[0]),
        "database_request": get_request_detail(db, request_ids[1]),
    }
