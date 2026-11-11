"""WI-007: composite Spanner submission intake tests."""

from __future__ import annotations

import uuid

from app.naming import validate_spanner_database_name, validate_spanner_instance_name


def test_spanner_composite_name_vectors():
    ok, _, _ = validate_spanner_instance_name(
        "spp-nonprod-orders", lob="spp", env="nonprod", app="orders"
    )
    assert ok
    ok_hyphen, rule, _ = validate_spanner_database_name("orders-history", app="orders")
    assert not ok_hyphen and rule == "SPN-NAME-002"
    good, _, _ = validate_spanner_database_name("orders_history", app="orders")
    assert good


def test_submission_fixture_shape():
    submission = {
        "template": "spanner-instance-with-databases",
        "resources": [
            {
                "kind": "spanner_instance",
                "metadata": {"apm_id": "apm00172", "project_id": "spp-nonprod-orders-svc", "environment": "nonprod", "lob": "spp"},
                "spec": {"name": "spp-nonprod-orders", "compute": {"processing_units": 100}},
            },
            {
                "kind": "spanner_database",
                "metadata": {"apm_id": "apm00172", "project_id": "spp-nonprod-orders-svc", "environment": "nonprod"},
                "spec": {"instance": "spp-nonprod-orders", "name": "orders"},
            },
        ],
    }
    assert submission["resources"][1]["spec"]["instance"] == submission["resources"][0]["spec"]["name"]
    assert len(submission["resources"]) == 2
