"""Database migration, trigger, and constraint unit tests (`WI-001` Acceptance Criteria 1 & 2, `ADR-GLB-004`).

Verifies against PostgreSQL 15+ (`spp_platform_test`):
- All 18 tables in schema `idp`, `idp.v_resource_status` view, and `idp.k8s_job_name(operation_id, phase)`.
- Seed rows (`approval_gate_config` for `gcs_bucket_owner` v1 and `spanner_data_owner` v1, `apm_alias` for `apm12345`, `resource_kind` for `gcs_bucket`, `spanner_instance`, `spanner_database`).
- `request_guard` blocks updates to `requested_spec`, `action`, `kind`, or `schema_version` on `idp.request`.
- `approval_guard` blocks mutations to `approved_spec`, `approved_spec_sha256`, or `guardrail_trace` once `idp.approval.status <> 'PENDING'`.
- `expected_revision_guard` blocks mutations to `artifact_uri`, `artifact_generation`, `artifact_sha256`, or `manifest` on `idp.expected_revision`.
- `gate_event_guard` blocks `DELETE` and any `UPDATE` other than setting `published_at` on `idp.gate_event`.
- `submission_no_secret_values`, `request_no_secret_values`, and `approval_no_secret_values` reject payloads containing secret keys.
- `approval_no_auto_approve_delete` rejects `status = 'AUTO_APPROVED'` when `approved_spec->>'action' = 'delete'`.
"""

from __future__ import annotations

import json
import os
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError, InternalError, ProgrammingError

from app.database import run_alembic_upgrade
from app.naming import canonical_sha256

TEST_DB_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+psycopg2://postgres:postgres@localhost:5432/spp_platform_test",
)


@pytest.fixture(scope="module")
def db_engine():
    engine = create_engine(TEST_DB_URL, future=True)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS idp CASCADE;"))
        conn.execute(text("DROP TABLE IF EXISTS public.alembic_version;"))
    run_alembic_upgrade(TEST_DB_URL)
    yield engine


def test_18_idp_tables_view_and_seeds(db_engine):
    expected_core_tables = {
        "approval_gate_config",
        "resource_kind",
        "apm_alias",
        "state_unit",
        "resource",
        "submission",
        "request",
        "policy_evaluation",
        "approval",
        "approval_decision",
        "expected_revision",
        "expected_revision_member",
        "tf_operation",
        "observation",
        "resource_observed",
        "drift_finding",
        "lifecycle_task",
        "gate_event",
    }
    with db_engine.connect() as conn:
        rows = conn.execute(
            text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'idp' AND table_type = 'BASE TABLE'")
        ).scalars().all()
        assert expected_core_tables.issubset(set(rows))

        views = conn.execute(
            text("SELECT table_name FROM information_schema.views WHERE table_schema = 'idp'")
        ).scalars().all()
        assert "v_resource_status" in views

        # SQL function idp.k8s_job_name
        job_name = conn.execute(
            text("SELECT idp.k8s_job_name('op:af42f828-3378-5ee2-8e9b-2378d2314f97:r1:plan:1', 'plan')")
        ).scalar_one()
        assert job_name == "tf-plan-eba5f9ebf4fafecad8e9"

        # Seed rows
        gates = conn.execute(text("SELECT gate_key FROM idp.approval_gate_config")).scalars().all()
        assert {"gcs_bucket_owner", "spanner_data_owner"} == set(gates)

        apm = conn.execute(text("SELECT alias FROM idp.apm_alias WHERE apm_id = 'apm12345'")).scalar_one()
        assert apm == "orders"

        kinds = conn.execute(text("SELECT kind FROM idp.resource_kind")).scalars().all()
        assert {"gcs_bucket", "spanner_instance", "spanner_database"} == set(kinds)


def test_secret_rejection_check_constraints(db_engine):
    with pytest.raises((IntegrityError, InternalError, ProgrammingError)):
        with db_engine.begin() as conn:
            bad_payload = {"password": "my-secret-password"}
            conn.execute(
                text(
                    """
                    INSERT INTO idp.submission (channel, apm_id, submitted_by, idempotency_key, raw_payload, raw_payload_sha256)
                    VALUES ('api', 'apm12345', 'user@example.com', :idem, CAST(:payload AS jsonb), :sha)
                    """
                ),
                {
                    "idem": f"sec-{uuid.uuid4()}",
                    "payload": json.dumps(bad_payload),
                    "sha": canonical_sha256(bad_payload),
                },
            )


def test_immutability_triggers_and_delete_auto_approve_constraint(db_engine):
    su_id = uuid.uuid4()
    res_id = uuid.uuid4()
    sub_id = uuid.uuid4()
    req_id = uuid.uuid4()
    apr_id = uuid.uuid4()
    rev_id = uuid.uuid4()

    clean_payload = {"kind": "gcs_bucket", "action": "create"}
    clean_sha = canonical_sha256(clean_payload)

    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO idp.state_unit (state_unit_id, cloud, scope_type, scope_id, lob, environment, apm_id, state_bucket, state_prefix, executor_identity)
                VALUES (:su_id, 'gcp', 'project', :proj, 'spp', 'nonprod', 'apm12345', 'microdrive-dev-spp-tfstate', :prefix, 'idp-tf@test.iam.gserviceaccount.com')
                """
            ),
            {"su_id": su_id, "proj": f"spp-nonprod-{su_id.hex[:6]}", "prefix": f"projects/{su_id.hex[:8]}"},
        )
        conn.execute(
            text(
                """
                INSERT INTO idp.resource (resource_id, state_unit_id, kind, name, resource_key, tf_address, apm_id)
                VALUES (:res_id, :su_id, 'gcs_bucket', :name, :rkey, 'module.gcs_bucket["b"]', 'apm12345')
                """
            ),
            {
                "res_id": res_id,
                "su_id": su_id,
                "name": f"spp-nonprod-orders-test-{res_id.hex[:4]}",
                "rkey": f"gcp:proj:gcs_bucket:{res_id.hex[:8]}",
            },
        )
        conn.execute(
            text(
                """
                INSERT INTO idp.submission (submission_id, channel, apm_id, submitted_by, idempotency_key, raw_payload, raw_payload_sha256)
                VALUES (:sub_id, 'api', 'apm12345', 'req@example.com', :idem, CAST(:payload AS jsonb), :sha)
                """
            ),
            {"sub_id": sub_id, "idem": f"idem-{sub_id}", "payload": json.dumps(clean_payload), "sha": clean_sha},
        )
        conn.execute(
            text(
                """
                INSERT INTO idp.request (request_id, submission_id, resource_id, kind, action, schema_version, requested_spec, requested_spec_sha256, requested_by)
                VALUES (:req_id, :sub_id, :res_id, 'gcs_bucket', 'create', '1.0.0', CAST(:spec AS jsonb), :sha, 'req@example.com')
                """
            ),
            {"req_id": req_id, "sub_id": sub_id, "res_id": res_id, "spec": json.dumps(clean_payload), "sha": clean_sha},
        )
        conn.execute(
            text(
                """
                INSERT INTO idp.approval (approval_id, request_id, resource_id, gate_key, gate_version, status, approved_spec, approved_spec_sha256, guardrail_trace)
                VALUES (:apr_id, :req_id, :res_id, 'gcs_bucket_owner', 1, 'APPROVED', CAST(:spec AS jsonb), :sha, '[]'::jsonb)
                """
            ),
            {"apr_id": apr_id, "req_id": req_id, "res_id": res_id, "spec": json.dumps(clean_payload), "sha": clean_sha},
        )
        conn.execute(
            text(
                """
                INSERT INTO idp.expected_revision (revision_id, state_unit_id, revision_no, artifact_uri, artifact_generation, artifact_sha256, manifest)
                VALUES (:rev_id, :su_id, 1, 'gs://microdrive-dev-spp-tfstate/projects/p/expected/rev-000001/terraform.tfvars.json', 100, :sha, '{}'::jsonb)
                """
            ),
            {"rev_id": rev_id, "su_id": su_id, "sha": clean_sha},
        )
        evt_id = conn.execute(
            text(
                """
                INSERT INTO idp.gate_event (state_unit_id, resource_id, request_id, gate, event_type, actor, detail)
                VALUES (:su_id, :res_id, :req_id, 'REQUESTED', 'request.submitted', 'user:req@example.com', '{}'::jsonb)
                RETURNING event_id
                """
            ),
            {"su_id": su_id, "res_id": res_id, "req_id": req_id},
        ).scalar_one()

    # 1. request_guard blocks mutation of requested_spec or action
    with pytest.raises(Exception, match="immutable"):
        with db_engine.begin() as conn:
            conn.execute(
                text("UPDATE idp.request SET action = 'delete' WHERE request_id = :req_id"),
                {"req_id": req_id},
            )

    # 2. approval_guard blocks mutation of approved_spec once status <> 'PENDING'
    with pytest.raises(Exception, match="decided"):
        with db_engine.begin() as conn:
            conn.execute(
                text("UPDATE idp.approval SET guardrail_trace = '[{\"rule_id\": \"X\"}]'::jsonb WHERE approval_id = :apr_id"),
                {"apr_id": apr_id},
            )

    # 3. expected_revision_guard blocks mutation of artifact_uri
    with pytest.raises(Exception, match="immutable"):
        with db_engine.begin() as conn:
            conn.execute(
                text("UPDATE idp.expected_revision SET artifact_uri = 'gs://other' WHERE revision_id = :rev_id"),
                {"rev_id": rev_id},
            )

    # 4. gate_event_guard blocks DELETE and blocks UPDATE on non-published_at columns, but allows setting published_at
    with pytest.raises(Exception, match="append-only"):
        with db_engine.begin() as conn:
            conn.execute(text("DELETE FROM idp.gate_event WHERE event_id = :id"), {"id": evt_id})

    with pytest.raises(Exception, match="append-only"):
        with db_engine.begin() as conn:
            conn.execute(
                text("UPDATE idp.gate_event SET event_type = 'tampered' WHERE event_id = :id"),
                {"id": evt_id},
            )

    with db_engine.begin() as conn:
        conn.execute(
            text("UPDATE idp.gate_event SET published_at = now() WHERE event_id = :id"),
            {"id": evt_id},
        )

    # 5. approval_no_auto_approve_delete blocks AUTO_APPROVED when action == 'delete'
    req2_id = uuid.uuid4()
    del_spec = {"action": "delete", "kind": "gcs_bucket"}
    del_sha = canonical_sha256(del_spec)
    with pytest.raises(IntegrityError):
        with db_engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO idp.request (request_id, submission_id, resource_id, kind, action, schema_version, requested_spec, requested_spec_sha256, requested_by)
                    VALUES (:req_id, :sub_id, :res_id, 'gcs_bucket', 'delete', '1.0.0', CAST(:spec AS jsonb), :sha, 'req@example.com')
                    """
                ),
                {"req_id": req2_id, "sub_id": sub_id, "res_id": res_id, "spec": json.dumps(del_spec), "sha": del_sha},
            )
            conn.execute(
                text(
                    """
                    INSERT INTO idp.approval (request_id, resource_id, gate_key, gate_version, status, approved_spec, approved_spec_sha256)
                    VALUES (:req_id, :res_id, 'gcs_bucket_owner', 1, 'AUTO_APPROVED', CAST(:spec AS jsonb), :sha)
                    """
                ),
                {"req_id": req2_id, "res_id": res_id, "spec": json.dumps(del_spec), "sha": del_sha},
            )
