"""SQLAlchemy 2.x ORM models for schema `idp` (`specs/data-model/spp_state_model.sql`, ADR-GLB-004, ADR-GLB-005)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    MetaData,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    metadata = MetaData(schema="idp")


# ---------------------------------------------------------------------------
# Local Authentication & Control Plane Audit Models (ADR-GLB-005)
# ---------------------------------------------------------------------------


class CpUser(Base):
    __tablename__ = "cp_users"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    email: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    failed_login_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class CpSession(Base):
    __tablename__ = "cp_sessions"

    session_id: Mapped[str] = mapped_column(Text, primary_key=True)
    username: Mapped[str] = mapped_column(Text, ForeignKey("idp.cp_users.username"), nullable=False)
    csrf_token: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class CpAuditLog(Base):
    __tablename__ = "cp_audit_log"

    audit_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    actor_username: Mapped[str] = mapped_column(Text, nullable=False)
    actor_role: Mapped[str] = mapped_column(Text, nullable=False)
    source_ip: Mapped[str] = mapped_column(Text, default="127.0.0.1", nullable=False)
    action_type: Mapped[str] = mapped_column(Text, nullable=False)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    request_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    approval_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)


# ---------------------------------------------------------------------------
# 18 Core Tables in Schema `idp` (`specs/data-model/spp_state_model.sql`)
# ---------------------------------------------------------------------------


class ApprovalGateConfig(Base):
    __tablename__ = "approval_gate_config"

    gate_key: Mapped[str] = mapped_column(Text, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    updated_by: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ResourceKind(Base):
    __tablename__ = "resource_kind"

    kind: Mapped[str] = mapped_column(Text, primary_key=True)
    cloud: Mapped[str] = mapped_column(Text, default="gcp", nullable=False)
    parent_kind: Mapped[str | None] = mapped_column(Text, ForeignKey("idp.resource_kind.kind"), nullable=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    schema_uri: Mapped[str] = mapped_column(Text, nullable=False)
    schema_version: Mapped[str] = mapped_column(Text, nullable=False)
    tf_module_source: Mapped[str] = mapped_column(Text, nullable=False)
    tfvars_collection: Mapped[str] = mapped_column(Text, nullable=False)
    tf_address_template: Mapped[str] = mapped_column(Text, nullable=False)
    opa_package: Mapped[str] = mapped_column(Text, nullable=False)
    approval_gate_key: Mapped[str | None] = mapped_column(
        Text, ForeignKey("idp.approval_gate_config.gate_key"), nullable=True
    )
    drift_ignore_paths: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, nullable=False)
    legacy_resource_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ApmAlias(Base):
    __tablename__ = "apm_alias"

    apm_id: Mapped[str] = mapped_column(Text, primary_key=True)
    alias: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    app_tier: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class StateUnit(Base):
    __tablename__ = "state_unit"

    state_unit_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cloud: Mapped[str] = mapped_column(Text, default="gcp", nullable=False)
    scope_type: Mapped[str] = mapped_column(Text, default="project", nullable=False)
    scope_id: Mapped[str] = mapped_column(Text, nullable=False)
    lob: Mapped[str | None] = mapped_column(Text, nullable=True)
    environment: Mapped[str | None] = mapped_column(Text, nullable=True)
    apm_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    state_bucket: Mapped[str] = mapped_column(Text, default="microdrive-dev-spp-tfstate", nullable=False)
    state_prefix: Mapped[str] = mapped_column(Text, nullable=False)
    executor_identity: Mapped[str] = mapped_column(Text, nullable=False)
    current_expected_rev: Mapped[int | None] = mapped_column(Integer, nullable=True)
    applied_expected_rev: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(Text, default="active", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Resource(Base):
    __tablename__ = "resource"

    resource_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    state_unit_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("idp.state_unit.state_unit_id"), nullable=False
    )
    kind: Mapped[str] = mapped_column(Text, ForeignKey("idp.resource_kind.kind"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    parent_resource_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("idp.resource.resource_id"), nullable=True
    )
    resource_key: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    tf_address: Mapped[str] = mapped_column(Text, nullable=False)
    apm_id: Mapped[str] = mapped_column(Text, nullable=False)
    lifecycle: Mapped[str] = mapped_column(Text, default="proposed", nullable=False)
    gate: Mapped[str] = mapped_column(Text, default="REQUESTED", nullable=False)
    sync_status: Mapped[str] = mapped_column(Text, default="PENDING", nullable=False)
    current_request_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    current_approval_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Submission(Base):
    __tablename__ = "submission"
    __table_args__ = (UniqueConstraint("apm_id", "idempotency_key"),)

    submission_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    source_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    apm_id: Mapped[str] = mapped_column(Text, nullable=False)
    submitted_by: Mapped[str] = mapped_column(Text, nullable=False)
    on_behalf_of: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    raw_payload_sha256: Mapped[str] = mapped_column(Text, nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ResourceRequest(Base):
    __tablename__ = "request"

    request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    submission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("idp.submission.submission_id"), nullable=False
    )
    resource_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("idp.resource.resource_id"), nullable=False
    )
    kind: Mapped[str] = mapped_column(Text, ForeignKey("idp.resource_kind.kind"), nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    schema_version: Mapped[str] = mapped_column(Text, nullable=False)
    requested_spec: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    requested_spec_sha256: Mapped[str] = mapped_column(Text, nullable=False)
    source_pointer: Mapped[str | None] = mapped_column(Text, nullable=True)
    base_approval_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    status: Mapped[str] = mapped_column(Text, default="SUBMITTED", nullable=False)
    status_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    temporal_workflow_id: Mapped[str | None] = mapped_column(Text, unique=True, nullable=True)
    requested_by: Mapped[str] = mapped_column(Text, nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class PolicyEvaluation(Base):
    __tablename__ = "policy_evaluation"

    evaluation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    stage: Mapped[str] = mapped_column(Text, nullable=False)
    request_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("idp.request.request_id"), nullable=True
    )
    revision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("idp.expected_revision.revision_id"), nullable=True
    )
    opa_package: Mapped[str] = mapped_column(Text, nullable=False)
    bundle_revision: Mapped[str] = mapped_column(Text, nullable=False)
    input_sha256: Mapped[str] = mapped_column(Text, nullable=False)
    decision: Mapped[str] = mapped_column(Text, nullable=False)
    violations: Mapped[list[Any]] = mapped_column(JSONB, default=list, nullable=False)
    mutations: Mapped[list[Any]] = mapped_column(JSONB, default=list, nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Approval(Base):
    __tablename__ = "approval"

    approval_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("idp.request.request_id"), unique=True, nullable=False
    )
    resource_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("idp.resource.resource_id"), nullable=False
    )
    gate_key: Mapped[str | None] = mapped_column(
        Text, ForeignKey("idp.approval_gate_config.gate_key"), nullable=True
    )
    gate_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(Text, default="PENDING", nullable=False)
    approved_spec: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    approved_spec_sha256: Mapped[str | None] = mapped_column(Text, nullable=True)
    guardrail_trace: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    policy_evaluation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("idp.policy_evaluation.evaluation_id"), nullable=True
    )
    temporal_workflow_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ApprovalDecision(Base):
    __tablename__ = "approval_decision"

    decision_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    approval_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("idp.approval.approval_id"), nullable=False
    )
    approver_key: Mapped[str] = mapped_column(Text, nullable=False)
    approver_identity: Mapped[str] = mapped_column(Text, nullable=False)
    phase: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    mandatory: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    status: Mapped[str] = mapped_column(Text, default="pending", nullable=False)
    sla_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    follow_up_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    escalation_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    escalated_to: Mapped[str | None] = mapped_column(Text, nullable=True)
    responded_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ExpectedRevision(Base):
    __tablename__ = "expected_revision"

    revision_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    state_unit_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("idp.state_unit.state_unit_id"), nullable=False
    )
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_revision_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    artifact_uri: Mapped[str] = mapped_column(Text, nullable=False)
    artifact_generation: Mapped[int] = mapped_column(BigInteger, nullable=False)
    artifact_sha256: Mapped[str] = mapped_column(Text, nullable=False)
    manifest: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    plan_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    plan_summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(Text, default="RENDERED", nullable=False)
    blocked_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ExpectedRevisionMember(Base):
    __tablename__ = "expected_revision_member"

    revision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("idp.expected_revision.revision_id"), primary_key=True
    )
    resource_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("idp.resource.resource_id"), primary_key=True
    )
    approval_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("idp.approval.approval_id"), nullable=False
    )
    change: Mapped[str] = mapped_column(Text, nullable=False)
    tf_address: Mapped[str] = mapped_column(Text, nullable=False)


class TfOperation(Base):
    __tablename__ = "tf_operation"

    operation_id: Mapped[str] = mapped_column(Text, primary_key=True)
    state_unit_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("idp.state_unit.state_unit_id"), nullable=False
    )
    revision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("idp.expected_revision.revision_id"), nullable=False
    )
    phase: Mapped[str] = mapped_column(Text, nullable=False)
    run_key: Mapped[str] = mapped_column(Text, default="1", nullable=False)
    k8s_namespace: Mapped[str] = mapped_column(Text, default="spp-platform", nullable=False)
    k8s_job_name: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    executor_identity: Mapped[str] = mapped_column(Text, nullable=False)
    temporal_workflow_id: Mapped[str] = mapped_column(Text, nullable=False)
    temporal_activity_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, default="PENDING", nullable=False)
    tf_exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    state_serial_before: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    state_serial_after: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    state_lineage: Mapped[str | None] = mapped_column(Text, nullable=True)
    logs_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Observation(Base):
    __tablename__ = "observation"

    observation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    state_unit_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("idp.state_unit.state_unit_id"), nullable=False
    )
    source: Mapped[str] = mapped_column(Text, nullable=False)
    operation_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("idp.tf_operation.operation_id"), nullable=True
    )
    revision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("idp.expected_revision.revision_id"), nullable=True
    )
    state_uri: Mapped[str] = mapped_column(Text, nullable=False)
    state_generation: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    state_serial: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    state_lineage: Mapped[str | None] = mapped_column(Text, nullable=True)
    snapshot_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    drift_detected: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ResourceObserved(Base):
    __tablename__ = "resource_observed"

    resource_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("idp.resource.resource_id"), primary_key=True
    )
    changed_in_observation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("idp.observation.observation_id"), nullable=False
    )
    exists_in_cloud: Mapped[bool] = mapped_column(Boolean, nullable=False)
    cloud_resource_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    projection: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    projection_sha256: Mapped[str] = mapped_column(Text, nullable=False)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DriftFinding(Base):
    __tablename__ = "drift_finding"

    drift_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    resource_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("idp.resource.resource_id"), nullable=False
    )
    observation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("idp.observation.observation_id"), nullable=False
    )
    revision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("idp.expected_revision.revision_id"), nullable=False
    )
    drift_kind: Mapped[str] = mapped_column(Text, nullable=False)
    attribute_path: Mapped[str] = mapped_column(Text, nullable=False)
    expected_value: Mapped[Any] = mapped_column(JSONB, nullable=True)
    observed_value: Mapped[Any] = mapped_column(JSONB, nullable=True)
    severity: Mapped[str] = mapped_column(Text, default="critical", nullable=False)
    guardrail_rule_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, default="OPEN", nullable=False)
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LifecycleTask(Base):
    __tablename__ = "lifecycle_task"

    task_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    resource_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("idp.resource.resource_id"), nullable=False
    )
    approval_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("idp.approval.approval_id"), nullable=False
    )
    phase: Mapped[str] = mapped_column(Text, nullable=False)
    task_type: Mapped[str] = mapped_column(Text, nullable=False)
    task_key: Mapped[str] = mapped_column(Text, nullable=False)
    spec: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(Text, default="PENDING", nullable=False)
    external_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class GateEvent(Base):
    __tablename__ = "gate_event"

    event_id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    state_unit_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("idp.state_unit.state_unit_id"), nullable=True
    )
    resource_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("idp.resource.resource_id"), nullable=True
    )
    request_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("idp.request.request_id"), nullable=True
    )
    gate: Mapped[str] = mapped_column(Text, nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    actor: Mapped[str] = mapped_column(Text, nullable=False)
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
