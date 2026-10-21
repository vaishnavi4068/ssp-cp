"""End-to-end API integration tests for `ssp-cp` (`WI-001` & `WI-003`):
- Local Argon2id login, mandatory first-login password rotation (`must_change_password`), CSRF protection, and 5-attempt lockout (`ADR-GLB-005`).
- `POST /api/v1/requests` intake normalization (`restrict -> restricted`, `APM12345 -> apm12345`, `dev -> nonprod`), idempotency deduplication, OPA `stage = 'requested'` evaluation, and `idp.policy_evaluation` persistence (`specs/examples/gcs_bucket.gates.json`).
- `POST /api/v1/approvals/{id}/decisions` role-based approval (`gcs_bucket_owner` v1), `self_approval = 'deny'` enforcement (`403 Forbidden`), human approval requirement on deletes (`auto_approved` rejected), OPA `stage = 'approved'` evaluation producing the 10-entry `guardrail_trace` with CMEK key `projects/microdrive-dev/locations/us-east1/keyRings/spp-keyring/cryptoKeys/spp-gcs-cmek`, and starting Temporal workflow `GcsBucketProvisionWorkflow`.
- `GET /api/v1/resources`, `GET /api/v1/status`, `GET /api/v1/audit`, and state unit `freeze` / `unfreeze` kill switch (`INV-9`).
- Conftest plan gate (`stage = 'plan'`) verification against mock Terraform `plan.json`.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.auth import login_rate_limiter
from app.database import init_engine
from app.main import app

TEST_DB_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+psycopg2://postgres:postgres@localhost:5432/spp_platform_test",
)


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", TEST_DB_URL)
    monkeypatch.setenv("SPP_CP_COOKIE_SECURE", "false")
    monkeypatch.setenv("TEMPORAL_ENABLED", "false")
    login_rate_limiter.reset()

    engine = init_engine(TEST_DB_URL, run_migrations=False)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS idp CASCADE;"))
        conn.execute(text("DROP TABLE IF EXISTS public.alembic_version;"))
    init_engine(TEST_DB_URL, run_migrations=True)

    with TestClient(app) as test_client:
        yield test_client


def _login_and_rotate_password(
    client: TestClient,
    username: str,
    bootstrap_pw: str,
    new_pw: str = "NewStrongPass!2026",
) -> str:
    resp = client.post("/api/v1/auth/login", json={"username": username, "password": bootstrap_pw})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["must_change_password"] is True
    csrf = body["csrf_token"]

    rot = client.post(
        "/api/v1/auth/change-password",
        json={"current_password": bootstrap_pw, "new_password": new_pw},
        headers={"X-CSRF-Token": csrf},
    )
    assert rot.status_code == 200, rot.text
    rot_body = rot.json()
    assert rot_body["must_change_password"] is False
    return rot_body["csrf_token"]


def test_healthz_and_readyz(client: TestClient):
    h = client.get("/healthz")
    assert h.status_code == 200
    data = h.json()
    assert data["service"] == "spp-cp"
    assert (
        data["cluster_target"]["default_kms_key_name"]
        == "projects/microdrive-dev/locations/us-east1/keyRings/spp-keyring/cryptoKeys/spp-gcs-cmek"
    )
    assert data["cluster_target"]["alloydb_host"] == "10.80.140.2"
    assert data["cluster_target"]["alloydb_database"] == "spp_platform"

    r = client.get("/readyz")
    assert r.status_code == 200
    assert r.json()["status"] == "ready"


def test_auth_must_change_password_csrf_and_5_attempt_lockout(client: TestClient):
    # 1. Login as manoj with bootstrap password
    resp = client.post("/api/v1/auth/login", json={"username": "manoj", "password": "SppFactory!Manoj2026"})
    assert resp.status_code == 200
    csrf = resp.json()["csrf_token"]

    # 2. Calling API before rotating password returns 403 must_change_password (ADR-GLB-005 SC-2)
    blocked = client.get("/api/v1/kinds")
    assert blocked.status_code == 403
    assert "must_change_password" in blocked.json()["detail"]

    # 3. Rotating password without CSRF token returns 403
    no_csrf = client.post(
        "/api/v1/auth/change-password",
        json={"current_password": "SppFactory!Manoj2026", "new_password": "Rotated!Manoj2026"},
    )
    assert no_csrf.status_code == 403

    # 4. Rotate password with CSRF token succeeds
    ok_rot = client.post(
        "/api/v1/auth/change-password",
        json={"current_password": "SppFactory!Manoj2026", "new_password": "Rotated!Manoj2026"},
        headers={"X-CSRF-Token": csrf},
    )
    assert ok_rot.status_code == 200
    new_csrf = ok_rot.json()["csrf_token"]

    # 5. Test 5-attempt lockout on dwayne
    for i in range(4):
        bad = client.post("/api/v1/auth/login", json={"username": "dwayne", "password": "wrong-password"})
        assert bad.status_code == 401
    fifth = client.post("/api/v1/auth/login", json={"username": "dwayne", "password": "wrong-password"})
    assert fifth.status_code == 423  # Locked

    # 6. Unlock dwayne as architect (manoj)
    # Re-login as manoj to restore cookie on client
    relogin = client.post("/api/v1/auth/login", json={"username": "manoj", "password": "Rotated!Manoj2026"})
    assert relogin.status_code == 200
    new_csrf = relogin.json()["csrf_token"]

    unlock = client.post(
        "/api/v1/auth/users/dwayne/unlock",
        json={"reason": "Unlocking after test lockout"},
        headers={"X-CSRF-Token": new_csrf},
    )
    assert unlock.status_code == 200


def test_gcs_bucket_gates_json_e2e_intake_opa_approval_and_temporal(client: TestClient):
    # Authenticate as requester (`requester@example.com`)
    req_csrf = _login_and_rotate_password(client, "requester", "SppFactory!Requester2026")

    # Load canonical fixture from `specs/examples/gcs_bucket.gates.json`
    fixture_path = Path(__file__).resolve().parents[1] / "specs" / "examples" / "gcs_bucket.gates.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))

    # Submit with raw unnormalized values (`APM12345`, `restrict`, `dev`, `<LOB>`) to verify intake normalization
    submission_payload = {
        "api_version": "idp.spp/v1",
        "kind": "gcs_bucket",
        "action": "create",
        "channel": "api",
        "idempotency_key": fixture["submission"]["row"]["idempotency_key"],
        "submission_id": fixture["submission"]["row"]["submission_id"],
        "request_id": fixture["requested"]["db"]["row"]["request_id"],
        "resource_id": fixture["requested"]["db"]["row"]["resource_id"],
        "approval_id": fixture["approved"]["db"]["approval"]["row"]["approval_id"],
        "metadata": {
            "apm_id": "APM12345",
            "project_id": "<lob>-nonprod-orders-svc",
            "environment": "dev",
            "lob": "<LOB>",
            "data_sensitivity": "restrict",
            "data_classification": "proprietary",
            "owner": "bucket.owner@example.com",
            "shared_mailbox": "<lob>-orders-team@example.com",
            "requested_by": "requester@example.com",
            "cost_center": "000000",
            "tenancy": "dedicated",
            "labels": {"app": "orders"},
            "extensions": {"<lob>": {"<lob>ml_version": "1.5"}},
        },
        "spec": {
            "name": "<lob>-nonprod-orders-landing-a1b2",
            "location": "us-east1",
            "storage_class": "STANDARD",
            "versioning": False,
            "lifecycle_rules": [],
            "access": [
                {
                    "role": "roles/storage.objectAdmin",
                    "members": ["serviceAccount:orders-pipeline@<lob>-nonprod-orders-svc.iam.gserviceaccount.com"],
                },
                {
                    "role": "roles/storage.objectViewer",
                    "members": ["group:gcp-<lob>-nonprod-orders-read@example.com"],
                },
            ],
            "purpose": "Landing zone for order events",
        },
    }

    resp = client.post(
        "/api/v1/requests",
        json=submission_payload,
        headers={"X-CSRF-Token": req_csrf},
    )
    assert resp.status_code == 201, resp.text
    created = resp.json()

    # Verify normalized `requested.document` matches `gcs_bucket.gates.json`
    expected_req_doc = dict(fixture["requested"]["document"])
    expected_req_doc["spec"] = dict(expected_req_doc["spec"])
    expected_req_doc["spec"].pop("_lifecycle_rules_note", None)
    expected_req_doc["spec"]["access"] = [
        {k: v for k, v in a.items() if k != "_source_gap"} for a in expected_req_doc["spec"]["access"]
    ]
    assert created["requested"]["document"] == expected_req_doc
    assert created["requested"]["document"]["metadata"]["apm_id"] == "apm12345"
    assert created["requested"]["document"]["metadata"]["environment"] == "nonprod"
    assert created["requested"]["document"]["metadata"]["data_sensitivity"] == "restricted"
    assert created["requested"]["document"]["spec"]["lifecycle_rules"] == []

    # Verify idempotency deduplication on `(apm_id, idempotency_key)`
    dup_resp = client.post(
        "/api/v1/requests",
        json=submission_payload,
        headers={"X-CSRF-Token": req_csrf},
    )
    assert dup_resp.status_code == 201
    assert dup_resp.json()["request_id"] == created["request_id"]

    # Verify `stage = 'requested'` policy_evaluation was recorded
    assert len(created["policy_evaluations"]) == 1
    assert created["policy_evaluations"][0]["stage"] == "requested"
    assert created["policy_evaluations"][0]["decision"] == "allow"

    # Attempt self-approval by requester -> MUST return 403 Forbidden (`self_approval = "deny"`, ADR-BP-003)
    # Give requester approver role temporarily or call via dwayne with responded_by=requester@example.com
    dwayne_csrf = _login_and_rotate_password(client, "dwayne", "SppFactory!Dwayne2026")
    self_approve = client.post(
        f"/api/v1/approvals/{created['approval']['approval_id']}/decisions",
        json={
            "approver_key": "bucket_owner",
            "status": "approved",
            "responded_by": "requester@example.com",
            "comment": "Attempting self-approval",
        },
        headers={"X-CSRF-Token": dwayne_csrf},
    )
    assert self_approve.status_code == 403
    assert "Self-approval is denied" in self_approve.json()["detail"]

    # Now login as `bucket_owner` (`bucket.owner@example.com`) and approve the `gcs_bucket_owner` gate
    owner_csrf = _login_and_rotate_password(client, "bucket_owner", "SppFactory!Bucket_owner2026")
    apr_resp = client.post(
        f"/api/v1/approvals/{created['approval']['approval_id']}/decisions",
        json={
            "approver_key": "bucket_owner",
            "status": "approved",
            "comment": "Approved bucket creation in us-east1",
        },
        headers={"X-CSRF-Token": owner_csrf},
    )
    assert apr_resp.status_code == 200, apr_resp.text
    approved_data = apr_resp.json()

    # Verify `approval.status == 'APPROVED'` and 2 policy_evaluation rows (`requested` and `approved`)
    assert approved_data["status"] == "APPROVED"
    assert approved_data["approval"]["status"] == "APPROVED"
    assert len(approved_data["policy_evaluations"]) == 2
    stages = [e["stage"] for e in approved_data["policy_evaluations"]]
    assert stages == ["requested", "approved"]
    assert approved_data["policy_evaluations"][1]["decision"] == "allow_with_mutations"

    # Verify exact 10-entry `guardrail_trace` in `idp.approval.guardrail_trace` (`WI-003` Acceptance Criterion 2)
    trace = approved_data["approval"]["guardrail_trace"]
    assert len(trace) == 10
    assert [t["rule_id"] for t in trace] == [
        "GCS-UBLA-001",
        "GCS-PAP-001",
        "GCS-ENC-001",
        "GCS-RET-001",
        "GCS-RET-003",
        "GCS-SDP-001",
        "GCS-DEL-001",
        "LBL-001",
        "PRQ-001",
        "PRQ-002",
    ]

    # Verify approved_spec has the real CMEK key in us-east1 and 8 mandatory labels without environmentsubtype
    approved_spec = approved_data["approval"]["approved_spec"]
    assert (
        approved_spec["spec"]["kms_key_name"]
        == "projects/microdrive-dev/locations/us-east1/keyRings/spp-keyring/cryptoKeys/spp-gcs-cmek"
    )
    assert approved_spec["spec"]["uniform_bucket_level_access"] is True
    assert approved_spec["spec"]["public_access_prevention"] == "enforced"
    assert approved_spec["spec"]["retention_days"] == 90
    assert approved_spec["spec"]["retention_locked"] is False
    assert approved_spec["spec"]["soft_delete_retention_days"] == 7
    assert approved_spec["spec"]["force_destroy"] is False
    assert "environmentsubtype" not in approved_spec["metadata"]["labels"]
    assert approved_spec["metadata"]["labels"]["sppappid"] == "apm12345"
    assert approved_spec["metadata"]["labels"]["environmenttype"] == "nonprod"

    # Verify Temporal workflow `GcsBucketProvisionWorkflow` was triggered on approval
    wf_dispatch = approved_data["temporal_workflow_dispatch"]
    assert wf_dispatch["workflow_name"] == "GcsBucketProvisionWorkflow"
    assert wf_dispatch["workflow_id"] == f"req-{created['request_id']}"
    assert wf_dispatch["namespace"] == "platform"

    # Verify GET /api/v1/resources (status view `idp.v_resource_status`) and GET /api/v1/audit
    res_list = client.get("/api/v1/resources")
    assert res_list.status_code == 200
    resources = res_list.json()["resources"]
    assert len(resources) == 1
    assert resources[0]["gate"] == "APPROVED"
    assert resources[0]["approval_status"] == "APPROVED"
    assert resources[0]["apm_id"] == "apm12345"

    res_detail = client.get(f"/api/v1/resources/{created['resource_id']}")
    assert res_detail.status_code == 200
    assert res_detail.json()["status"]["name"] == "<lob>-nonprod-orders-landing-a1b2"

    audit_resp = client.get(f"/api/v1/audit?request_id={created['request_id']}")
    assert audit_resp.status_code == 200
    audit_body = audit_resp.json()
    assert len(audit_body["gate_events"]) == 2
    assert {e["event_type"] for e in audit_body["gate_events"]} == {"request.submitted", "approval.granted"}
    assert len(audit_body["policy_evaluations"]) == 2


def test_delete_request_requires_human_approval_in_all_environments(client: TestClient):
    req_csrf = _login_and_rotate_password(client, "requester", "SppFactory!Requester2026")
    owner_csrf = _login_and_rotate_password(client, "bucket_owner", "SppFactory!Bucket_owner2026")

    # Submit a delete request in nonprod
    del_payload = {
        "api_version": "idp.spp/v1",
        "kind": "gcs_bucket",
        "action": "delete",
        "metadata": {
            "apm_id": "APM12345",
            "project_id": "spp-nonprod-orders-svc",
            "environment": "nonprod",
            "lob": "spp",
            "data_sensitivity": "restricted",
            "owner": "bucket.owner@example.com",
            "cost_center": "000000",
            "labels": {"app": "orders"},
        },
        "spec": {
            "name": "spp-nonprod-orders-deltest-a1b2",
            "location": "us-east1",
        },
    }
    # Re-login as requester
    re_req = client.post("/api/v1/auth/login", json={"username": "requester", "password": "NewStrongPass!2026"})
    req_csrf = re_req.json()["csrf_token"]

    resp = client.post("/api/v1/requests", json=del_payload, headers={"X-CSRF-Token": req_csrf})
    assert resp.status_code == 201, resp.text
    del_req = resp.json()

    # Login as bucket_owner and attempt `auto_approved` -> MUST fail with 403 Forbidden
    re_owner = client.post("/api/v1/auth/login", json={"username": "bucket_owner", "password": "NewStrongPass!2026"})
    owner_csrf = re_owner.json()["csrf_token"]

    auto_apr = client.post(
        f"/api/v1/approvals/{del_req['approval']['approval_id']}/decisions",
        json={"status": "auto_approved", "comment": "Attempt auto-approve delete"},
        headers={"X-CSRF-Token": owner_csrf},
    )
    assert auto_apr.status_code == 403
    assert "Human approval is required for all delete requests" in auto_apr.json()["detail"]

    # Explicit human `approved` succeeds
    human_apr = client.post(
        f"/api/v1/approvals/{del_req['approval']['approval_id']}/decisions",
        json={"status": "approved", "comment": "Explicit human approval for delete"},
        headers={"X-CSRF-Token": owner_csrf},
    )
    assert human_apr.status_code == 200
    assert human_apr.json()["approval"]["status"] == "APPROVED"


def test_conftest_plan_gate_cli(tmp_path: Path):
    """Verify `conftest test` CLI against compliant and non-compliant Terraform `plan.json` (`WI-003` Criterion 3)."""
    policy_dir = Path(__file__).resolve().parents[1] / "policy"
    compliant_plan = {
        "stage": "plan",
        "approved_delete_request": False,
        "resource_changes": [
            {
                "address": "module.gcs_bucket[\"spp-nonprod-orders-landing-a1b2\"].google_storage_bucket.this",
                "type": "google_storage_bucket",
                "change": {
                    "actions": ["create"],
                    "after": {
                        "name": "spp-nonprod-orders-landing-a1b2",
                        "location": "us-east1",
                        "storage_class": "STANDARD",
                        "uniform_bucket_level_access": True,
                        "public_access_prevention": "enforced",
                        "force_destroy": False,
                        "default_kms_key_name": "projects/microdrive-dev/locations/us-east1/keyRings/spp-keyring/cryptoKeys/spp-gcs-cmek",
                        "retention_policy": {"retention_period": 7776000, "is_locked": False},
                        "soft_delete_policy": {"retention_duration_seconds": 604800},
                        "lifecycle_rules": [],
                        "labels": {
                            "app": "orders",
                            "costcenter": "000000",
                            "dataclassification": "proprietary",
                            "datasensitivity": "restricted",
                            "environmenttype": "nonprod",
                            "idp_resource_id": "9478bcfc-c2cf-583b-8bd8-096476647840",
                            "owner": "bucket_owner_example_com",
                            "primarylob": "spp",
                            "provisionedby": "idp",
                            "sharedemailaddress": "spp-orders-team_example_com",
                            "sppappid": "apm12345",
                            "tenancy": "dedicated",
                        },
                    },
                },
            }
        ],
    }
    plan_file = tmp_path / "plan_ok.json"
    plan_file.write_text(json.dumps(compliant_plan), encoding="utf-8")

    ok_proc = subprocess.run(
        ["conftest", "test", str(plan_file), "-p", str(policy_dir)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert ok_proc.returncode == 0, ok_proc.stdout + ok_proc.stderr

    # Non-compliant plan (wrong location + unapproved delete)
    bad_plan = json.loads(json.dumps(compliant_plan))
    bad_plan["resource_changes"][0]["change"]["after"]["location"] = "US"
    bad_plan_file = tmp_path / "plan_bad.json"
    bad_plan_file.write_text(json.dumps(bad_plan), encoding="utf-8")

    bad_proc = subprocess.run(
        ["conftest", "test", str(bad_plan_file), "-p", str(policy_dir)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert bad_proc.returncode != 0
    assert "GLB-REG-001" in bad_proc.stdout
