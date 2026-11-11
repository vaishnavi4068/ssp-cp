"""Unit tests for naming, APM ID (`^APM\\d{5}$`), label normalization (`LBL-001`, `LBL-002`),
and `k8s_job_name` derivation (`WI-001`, `ADR-GLB-006`, `ADR-GLB-008`, `ADR-AUT-001`, `specs/naming/naming-spec.json`)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.naming import (
    compute_canonical_labels,
    generate_spanner_display_name,
    k8s_job_name,
    normalize_data_sensitivity,
    normalize_environment,
    normalize_label_value,
    validate_and_normalize_apm_id,
    validate_gcs_bucket_name,
    validate_spanner_database_name,
    validate_spanner_instance_name,
)


def test_apm_id_validation_and_normalization():
    # User decision: ^APM\d{5}$ case-insensitive -> lowercase apm\d{5}
    assert validate_and_normalize_apm_id("APM12345") == "apm12345"
    assert validate_and_normalize_apm_id("apm12345") == "apm12345"
    assert validate_and_normalize_apm_id("ApM00001") == "apm00001"

    for invalid in ["APM0017299", "apm0017299", "APM1234", "APM123456", "APP12345", "12345", ""]:
        with pytest.raises(ValueError, match="NAM-APM-001"):
            validate_and_normalize_apm_id(invalid)


def test_environment_normalization():
    for raw in ["sandbox", "dev", "qa", "test", "pdev", "pqa", "preprod", "nonprod", "DEV", "PreProd"]:
        assert normalize_environment(raw) == "nonprod"
    assert normalize_environment("prod") == "prod"
    assert normalize_environment("PROD") == "prod"
    with pytest.raises(ValueError, match="GLB-ENV-001"):
        normalize_environment("staging-unknown")


def test_data_sensitivity_normalization():
    assert normalize_data_sensitivity("restrict") == "restricted"
    assert normalize_data_sensitivity("RESTRICTED") == "restricted"
    assert normalize_data_sensitivity("unrestrict") == "unrestricted"


def test_k8s_job_name_matches_spec_vectors():
    # WI-002 / ADR-AUT-001 / gcs_bucket.gates.json vectors
    assert (
        k8s_job_name("op:af42f828-3378-5ee2-8e9b-2378d2314f97:r1:plan:1", "plan")
        == "tf-plan-eba5f9ebf4fafecad8e9"
    )
    assert (
        k8s_job_name("op:af42f828-3378-5ee2-8e9b-2378d2314f97:r1:apply:1", "apply")
        == "tf-apply-b85d57b4511c03e98373"
    )
    assert (
        k8s_job_name("op:af42f828-3378-5ee2-8e9b-2378d2314f97:r2:refresh_plan:2026-10-23T06", "refresh_plan")
        == "tf-refresh-plan-415a15a935cbd63f95e1"
    )


def test_naming_spec_13_test_vectors():
    spec_path = Path(__file__).resolve().parents[1] / "specs" / "naming" / "naming-spec.json"
    spec_data = json.loads(spec_path.read_text(encoding="utf-8"))
    vectors = spec_data["test_vectors"]
    assert len(vectors) == 13

    for vec in vectors:
        kind = vec["kind"]
        action = vec.get("action", "create")
        env = vec.get("environment", "nonprod")
        app = vec.get("app", "orders")
        name = vec.get("name", "<lob>-nonprod-orders-landing-a1b2")
        lob = "<lob>"

        if kind == "gcs_bucket":
            existing_name = "<lob>-nonprod-orders-old-a1b2" if action == "update" else None
            valid, rule, _ = validate_gcs_bucket_name(
                name, lob=lob, env=env, app=app, action=action, existing_name=existing_name
            )
            assert valid is vec["valid"], f"Failed vector: {vec}"
            if not vec["valid"]:
                assert rule == vec["expected_rule"]
            elif "expected_rule" in vec:
                assert rule == vec["expected_rule"]
        elif kind == "spanner_instance":
            valid, rule, _ = validate_spanner_instance_name(name, lob=lob, env=env, app=app, action=action)
            assert valid is vec["valid"]
            if not vec["valid"]:
                assert rule == vec["expected_rule"]
        elif kind == "spanner_database":
            valid, rule, _ = validate_spanner_database_name(name, app=app, action=action)
            assert valid is vec["valid"]
            if not vec["valid"]:
                assert rule == vec["expected_rule"]


def test_spanner_display_name_shortening_vectors():
    spec_path = Path(__file__).resolve().parents[1] / "specs" / "naming" / "naming-spec.json"
    spec_data = json.loads(spec_path.read_text(encoding="utf-8"))
    examples = spec_data["display_name_examples"]
    assert len(examples) == 3

    for ex in examples:
        actual = generate_spanner_display_name(ex["lob"], ex["app"], ex["purpose"], ex["env"])
        assert actual == ex["expected"]
        assert len(actual) <= 30


def test_label_normalization_vectors_and_8_mandatory_labels():
    # ADR-GLB-008 LBL-002 normalization test vectors
    assert normalize_label_value("bucket.owner@example.com") == "bucket_owner_example_com"
    assert normalize_label_value("<lob>-orders-team@example.com") == "<lob>-orders-team_example_com"
    assert normalize_label_value("SPP-Orders Team") == "spp-orders_team"
    long_str = "a" * 75
    assert len(normalize_label_value(long_str)) == 63

    # LBL-001 8 mandatory labels + metadata-derived labels, no environmentsubtype
    meta = {
        "apm_id": "apm12345",
        "cost_center": "000000",
        "environment": "nonprod",
        "lob": "<lob>",
        "data_sensitivity": "restricted",
        "data_classification": "proprietary",
        "owner": "bucket.owner@example.com",
        "shared_mailbox": "<lob>-orders-team@example.com",
        "tenancy": "dedicated",
        "labels": {"app": "orders"},
    }
    labels = compute_canonical_labels(meta, "9478bcfc-c2cf-583b-8bd8-096476647840")
    assert "environmentsubtype" not in labels
    assert labels == {
        "app": "orders",
        "costcenter": "000000",
        "dataclassification": "proprietary",
        "datasensitivity": "restricted",
        "environmenttype": "nonprod",
        "idp_resource_id": "9478bcfc-c2cf-583b-8bd8-096476647840",
        "owner": "bucket_owner_example_com",
        "primarylob": "<lob>",
        "provisionedby": "idp",
        "sharedemailaddress": "<lob>-orders-team_example_com",
        "sppappid": "apm12345",
        "tenancy": "dedicated",
    }

    # Verify environmentsubtype is explicitly rejected if supplied
    meta_with_subtype = dict(meta, labels={"app": "orders", "environmentsubtype": "dev"})
    with pytest.raises(ValueError, match="environmentsubtype"):
        compute_canonical_labels(meta_with_subtype, "9478bcfc-c2cf-583b-8bd8-096476647840")
