"""Configuration settings for SPP Control Plane (`ssp-cp`).

Supports:
- AlloyDB for PostgreSQL via env vars / mounted GCP Secret Manager secrets (ADR-GLB-004, ADR-GLB-005).
- Plain PostgreSQL `DATABASE_URL` for local / CI test execution.
- Configurable Temporal server address, namespace (`platform`), task queue, and workflow name (`GcsBucketProvisionWorkflow`).
- Internal OPA service endpoint (`http://spp-opa.spp-policy.svc.cluster.local:8181`) with local Rego fallback for unit/offline tests.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote_plus


def _default_repo_root() -> Path:
    env_root = os.getenv("SPP_CP_REPO_ROOT")
    if env_root:
        return Path(env_root)
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "db").is_dir() and (parent / "policy").is_dir():
            return parent
    return Path.cwd()


def _read_secret_file(secrets_dir: str, *names: str) -> str | None:
    base = Path(secrets_dir)
    if not base.is_dir():
        return None
    for name in names:
        candidate = base / name
        if candidate.is_file():
            val = candidate.read_text(encoding="utf-8").strip()
            if val:
                return val
    return None


def resolve_database_url(secrets_dir: str = "/etc/spp-cp-secrets") -> str:
    """Resolve database connection URL from env or Secret Manager mounted files.

    Precedence:
    1. Explicit `DATABASE_URL` environment variable (supports plain Postgres URL for local tests).
    2. Secret Manager file `database-url` or `alloydb-database-url` under `secrets_dir`.
    3. AlloyDB component env vars (`ALLOYDB_HOST`, `ALLOYDB_PORT`, `ALLOYDB_DB`, `ALLOYDB_USER`, `ALLOYDB_PASSWORD` or secret file).
    4. Default local Postgres URL (`postgresql+psycopg2://postgres:postgres@localhost:5432/spp_platform`).
    """
    explicit_url = os.getenv("DATABASE_URL")
    if explicit_url:
        return explicit_url

    secret_url = _read_secret_file(secrets_dir, "database-url", "alloydb-database-url", "spp-cp-database-url")
    if secret_url:
        return secret_url

    alloy_host = os.getenv("ALLOYDB_HOST")
    if alloy_host:
        alloy_port = os.getenv("ALLOYDB_PORT", "5432")
        alloy_db = os.getenv("ALLOYDB_DB", "spp_platform")
        alloy_user = os.getenv("ALLOYDB_USER", "postgres")
        alloy_sslmode = os.getenv("ALLOYDB_SSLMODE", "require")
        alloy_pw = os.getenv("ALLOYDB_PASSWORD") or _read_secret_file(
            secrets_dir,
            "spp-alloydb-postgres-password",
            "alloydb-password",
            "postgres-password",
            "spp-cp-db-password",
        ) or ""
        auth_part = f"{quote_plus(alloy_user)}:{quote_plus(alloy_pw)}" if alloy_pw else quote_plus(alloy_user)
        return f"postgresql+psycopg2://{auth_part}@{alloy_host}:{alloy_port}/{alloy_db}?sslmode={alloy_sslmode}"

    return "postgresql+psycopg2://postgres:postgres@localhost:5432/spp_platform"


@dataclass
class Settings:
    bootstrap_secrets_dir: str = field(
        default_factory=lambda: os.getenv("SPP_CP_BOOTSTRAP_SECRETS_DIR", "/etc/spp-cp-secrets")
    )
    database_url: str = field(
        default_factory=lambda: resolve_database_url(
            os.getenv("SPP_CP_BOOTSTRAP_SECRETS_DIR", "/etc/spp-cp-secrets")
        )
    )
    alloydb_instance_uri: str = field(
        default_factory=lambda: os.getenv(
            "ALLOYDB_INSTANCE_URI",
            "projects/microdrive-dev/locations/us-east1/clusters/spp-alloydb/instances/spp-alloydb-primary",
        )
    )
    alloydb_host: str = field(
        default_factory=lambda: os.getenv("ALLOYDB_HOST", "10.80.140.2")
    )
    alloydb_port: int = field(
        default_factory=lambda: int(os.getenv("ALLOYDB_PORT", "5432"))
    )
    alloydb_database: str = field(
        default_factory=lambda: os.getenv("ALLOYDB_DB", "spp_platform")
    )
    alloydb_user: str = field(
        default_factory=lambda: os.getenv("ALLOYDB_USER", "postgres")
    )
    alloydb_sslmode: str = field(
        default_factory=lambda: os.getenv("ALLOYDB_SSLMODE", "require")
    )
    alloydb_password_secret_name: str = field(
        default_factory=lambda: os.getenv("ALLOYDB_PASSWORD_SECRET", "spp-alloydb-postgres-password")
    )
    temporal_address: str = field(
        default_factory=lambda: os.getenv(
            "TEMPORAL_ADDRESS",
            "temporal-frontend.spp-temporal.svc.cluster.local:7233",
        )
    )
    temporal_namespace: str = field(
        default_factory=lambda: os.getenv("TEMPORAL_NAMESPACE", "platform")
    )
    temporal_task_queue: str = field(
        default_factory=lambda: os.getenv("TEMPORAL_TASK_QUEUE", "spp-gcs-provisioning")
    )
    temporal_gcs_workflow: str = field(
        default_factory=lambda: os.getenv("TEMPORAL_GCS_WORKFLOW", "GcsBucketProvisionWorkflow")
    )
    temporal_enabled: bool = field(
        default_factory=lambda: os.getenv("TEMPORAL_ENABLED", "true").lower() == "true"
    )
    opa_url: str = field(
        default_factory=lambda: os.getenv(
            "OPA_URL",
            "http://spp-opa.spp-policy.svc.cluster.local:8181",
        )
    )
    opa_bundle_revision: str = field(
        default_factory=lambda: os.getenv("OPA_BUNDLE_REVISION", "3f9a1c2")
    )
    opa_fallback_local: bool = field(
        default_factory=lambda: os.getenv("OPA_FALLBACK_LOCAL", "true").lower() == "true"
    )
    default_kms_key_name: str = field(
        default_factory=lambda: os.getenv(
            "SPP_DEFAULT_KMS_KEY_NAME",
            "projects/microdrive-dev/locations/us-east1/keyRings/spp-keyring/cryptoKeys/spp-gcs-cmek",
        )
    )
    kms_key_placeholder: str = field(
        default_factory=lambda: os.getenv(
            "SPP_KMS_KEY_URI_OVERRIDE",
            "projects/microdrive-dev/locations/us-east1/keyRings/spp-keyring/cryptoKeys/spp-gcs-cmek",
        )
    )
    runner_service_account: str = field(
        default_factory=lambda: os.getenv(
            "SPP_RUNNER_SA_EMAIL",
            "spp-deploy@microdrive-dev.iam.gserviceaccount.com",
        )
    )
    state_bucket: str = field(
        default_factory=lambda: os.getenv("SPP_STATE_BUCKET", "microdrive-dev-spp-tfstate")
    )
    session_secret: str = field(
        default_factory=lambda: os.getenv(
            "SPP_CP_SESSION_SECRET",
            "dev-bootstrap-session-secret-change-in-secret-manager-32b",
        )
    )
    cookie_name: str = field(
        default_factory=lambda: os.getenv(
            "SPP_CP_SESSION_COOKIE_NAME",
            "__Host-spp_cp_session",
        )
    )
    cookie_secure: bool = field(
        default_factory=lambda: os.getenv("SPP_CP_COOKIE_SECURE", "true").lower() == "true"
    )
    session_idle_timeout_seconds: int = field(
        default_factory=lambda: int(os.getenv("SPP_CP_SESSION_IDLE_SECONDS", "1800"))
    )
    session_absolute_timeout_seconds: int = field(
        default_factory=lambda: int(os.getenv("SPP_CP_SESSION_MAX_SECONDS", "28800"))
    )
    login_rate_limit_window_seconds: int = field(
        default_factory=lambda: int(os.getenv("SPP_CP_RATE_LIMIT_WINDOW_SECONDS", "60"))
    )
    login_rate_limit_max_requests: int = field(
        default_factory=lambda: int(os.getenv("SPP_CP_RATE_LIMIT_MAX_REQUESTS", "10"))
    )
    lockout_max_failed_attempts: int = field(
        default_factory=lambda: int(os.getenv("SPP_CP_LOCKOUT_MAX_ATTEMPTS", "5"))
    )
    lockout_duration_seconds: int = field(
        default_factory=lambda: int(os.getenv("SPP_CP_LOCKOUT_DURATION_SECONDS", "900"))
    )
    cors_origins: list[str] = field(
        default_factory=lambda: [
            o.strip()
            for o in os.getenv(
                "SPP_CP_CORS_ORIGINS",
                "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000,http://127.0.0.1:3000",
            ).split(",")
            if o.strip()
        ]
    )
    repo_root: Path = field(default_factory=_default_repo_root)
    k8s_namespace: str = field(
        default_factory=lambda: os.getenv("SPP_K8S_NAMESPACE", "spp-platform")
    )
    gcp_project_id: str = field(
        default_factory=lambda: os.getenv("GCP_PROJECT_ID", "microdrive-dev")
    )
    gke_cluster_name: str = field(
        default_factory=lambda: os.getenv("GKE_CLUSTER_NAME", "md-dev")
    )
    gcp_region: str = field(
        default_factory=lambda: os.getenv("GCP_REGION", "us-east1")
    )
    gke_node_pool: str = field(
        default_factory=lambda: os.getenv(
            "GKE_NODE_POOL", "spp-pool (workload=spp, dedicated=spp:NoSchedule)"
        )
    )


def get_settings() -> Settings:
    return Settings()
