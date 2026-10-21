"""Pydantic v2 request and response schemas for SPP Control Plane (`ssp-cp`)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=256)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=256)
    new_password: str = Field(..., min_length=8, max_length=256)


class UnlockUserRequest(BaseModel):
    reason: str = Field(..., min_length=3, max_length=500)


class UserProfileResponse(BaseModel):
    username: str
    email: str
    display_name: str
    role: str
    must_change_password: bool
    csrf_token: str
    last_login_at: datetime | None = None


class AccessEntrySchema(BaseModel):
    model_config = ConfigDict(extra="allow")

    role: str = Field(..., min_length=1)
    members: list[str] = Field(default_factory=list)


class RequestMetadataInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    apm_id: str = Field(..., min_length=1, description="Application ID matching ^APM\\d{5}$ (case-insensitive)")
    project_id: str = Field(..., min_length=1)
    environment: str = Field(..., min_length=1, description="Normalized to 'nonprod' or 'prod'")
    lob: str = Field(..., min_length=1)
    data_sensitivity: str = Field(default="restricted")
    data_classification: str = Field(default="proprietary")
    owner: str = Field(..., min_length=3)
    shared_mailbox: str = Field(default="")
    requested_by: str | None = Field(default=None)
    cost_center: str = Field(default="000000")
    tenancy: str = Field(default="dedicated")
    labels: dict[str, Any] = Field(default_factory=dict)
    extensions: dict[str, Any] = Field(default_factory=dict)


class GcsBucketSpecInput(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str | None = Field(default=None, description="Full bucket name or generated from purpose_token + suffix")
    purpose_token: str | None = Field(
        default=None,
        description="Optional kebab-case purpose token (e.g. 'landing') used if 'name' is not pre-built",
    )
    location: str = Field(default="us-east1")
    storage_class: str = Field(default="STANDARD")
    versioning: bool = Field(default=False)
    lifecycle_rules: list[dict[str, Any]] = Field(default_factory=list)
    access: list[dict[str, Any]] = Field(default_factory=list)
    purpose: str = Field(default="Landing zone for application data")


class CreateRequestPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    api_version: str = Field(default="idp.spp/v1")
    kind: str = Field(default="gcs_bucket")
    action: str = Field(default="create", pattern="^(create|update|delete|import)$")
    idempotency_key: str | None = Field(default=None)
    channel: str = Field(default="api", pattern="^(ui|api|chat|legacy_shim|legacy_provisioning_shim|import)$")
    source_ref: str | None = Field(default=None)
    on_behalf_of: str | None = Field(default=None)
    base_approval_id: str | None = Field(default=None)
    resource_id: str | None = Field(default=None)
    submission_id: str | None = Field(default=None)
    request_id: str | None = Field(default=None)
    approval_id: str | None = Field(default=None)
    metadata: RequestMetadataInput
    spec: dict[str, Any]


class ApprovalDecisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approver_key: str | None = Field(default=None, description="Defaults to the current pending approver_key (e.g. bucket_owner)")
    decision_id: str | None = Field(default=None)
    status: str = Field(..., pattern="^(approved|denied|escalated|auto_approved)$")
    comment: str | None = Field(default=None, max_length=2000)
    responded_by: str | None = Field(default=None, description="Defaults to authenticated user's email")


class StateUnitFreezeRequest(BaseModel):
    reason: str = Field(..., min_length=3, max_length=1000)
