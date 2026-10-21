"""Tests for live OPA server HTTP API integration, AlloyDB connection config resolution,
and Kubernetes/Helm deployment manifests (`WI-001` & `WI-003`)."""

from __future__ import annotations

import socket
import subprocess
import time
from pathlib import Path

import httpx
import yaml

from app.config import Settings, resolve_database_url
from app.opa_client import OpaClient


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_alloydb_database_url_resolution_from_env_and_secret_file(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("ALLOYDB_HOST", "10.80.140.2")
    monkeypatch.setenv("ALLOYDB_PORT", "5432")
    monkeypatch.setenv("ALLOYDB_DB", "spp_platform")
    monkeypatch.setenv("ALLOYDB_USER", "postgres")
    monkeypatch.setenv("ALLOYDB_SSLMODE", "require")
    monkeypatch.delenv("ALLOYDB_PASSWORD", raising=False)

    secret_file = tmp_path / "spp-alloydb-postgres-password"
    secret_file.write_text("my-secret-manager-pw\n", encoding="utf-8")

    url = resolve_database_url(str(tmp_path))
    assert url == "postgresql+psycopg2://postgres:my-secret-manager-pw@10.80.140.2:5432/spp_platform?sslmode=require"


def test_live_opa_server_http_evaluation():
    """Start a real `opa run --server` subprocess loading `policy/` and verify `OpaClient` HTTP evaluation."""
    port = _find_free_port()
    policy_dir = Path(__file__).resolve().parents[1] / "policy"
    proc = subprocess.Popen(
        ["opa", "run", "--server", f"--addr=127.0.0.1:{port}", str(policy_dir)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        opa_url = f"http://127.0.0.1:{port}"
        ready = False
        for _ in range(30):
            try:
                r = httpx.get(f"{opa_url}/health", timeout=0.5)
                if r.status_code == 200:
                    ready = True
                    break
            except Exception:
                time.sleep(0.1)
        assert ready, "OPA server failed to become healthy"

        settings = Settings(opa_url=opa_url, opa_fallback_local=False)
        client = OpaClient(settings)
        res = client.evaluate_raw(
            "idp.gcp.gcs_bucket",
            {
                "stage": "approved",
                "cloud": "gcp",
                "app_alias": "orders",
                "resource_id": "9478bcfc-c2cf-583b-8bd8-096476647840",
                "document": {
                    "api_version": "idp.spp/v1",
                    "kind": "gcs_bucket",
                    "action": "create",
                    "metadata": {
                        "apm_id": "apm12345",
                        "project_id": "spp-nonprod-orders-svc",
                        "environment": "nonprod",
                        "lob": "spp",
                        "data_sensitivity": "restricted",
                        "data_classification": "proprietary",
                        "owner": "bucket.owner@example.com",
                        "shared_mailbox": "spp-orders-team@example.com",
                        "cost_center": "000000",
                        "tenancy": "dedicated",
                        "labels": {"app": "orders"},
                    },
                    "spec": {
                        "name": "spp-nonprod-orders-landing-a1b2",
                        "location": "us-east1",
                        "storage_class": "STANDARD",
                        "versioning": False,
                        "lifecycle_rules": [],
                        "access": [
                            {
                                "role": "roles/storage.objectViewer",
                                "members": ["group:gcp-spp-nonprod-orders-read@example.com"],
                            }
                        ],
                    },
                },
            },
        )
        assert res["decision"] == "allow_with_mutations"
        assert len(res["guardrail_trace"]) == 10
        assert (
            res["resolved_kms_key"]
            == "projects/microdrive-dev/locations/us-east1/keyRings/spp-keyring/cryptoKeys/spp-gcs-cmek"
        )
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def test_helm_values_and_opa_k8s_manifests():
    repo_root = Path(__file__).resolve().parents[1]
    values_path = repo_root / "deploy" / "helm" / "spp-cp" / "values.yaml"
    values = yaml.safe_load(values_path.read_text(encoding="utf-8"))

    assert values["global"]["namespace"] == "spp-platform"
    assert values["global"]["nodeSelector"] == {"workload": "spp"}
    assert values["alloydb"]["cluster"] == "spp-alloydb"
    assert values["alloydb"]["instance"] == "spp-alloydb-primary"
    assert values["alloydb"]["host"] == "10.80.140.2"
    assert values["alloydb"]["port"] == 5432
    assert values["alloydb"]["database"] == "spp_platform"
    assert values["alloydb"]["username"] == "postgres"
    assert values["alloydb"]["sslmode"] == "require"
    assert values["alloydb"]["gcpSecretManagerPasswordSecret"] == "spp-alloydb-postgres-password"
    assert (
        values["kms"]["defaultGcsKeyName"]
        == "projects/microdrive-dev/locations/us-east1/keyRings/spp-keyring/cryptoKeys/spp-gcs-cmek"
    )
    assert values["opa"]["namespace"] == "spp-policy"

    opa_k8s_path = repo_root / "deploy" / "k8s" / "opa-deployment.yaml"
    docs = list(yaml.safe_load_all(opa_k8s_path.read_text(encoding="utf-8")))
    kinds = [d["kind"] for d in docs if d]
    assert kinds == ["Namespace", "Deployment", "Service", "NetworkPolicy"]
    svc_doc = next(d for d in docs if d and d["kind"] == "Service")
    assert svc_doc["spec"]["type"] == "ClusterIP"
    assert svc_doc["metadata"]["namespace"] == "spp-policy"
