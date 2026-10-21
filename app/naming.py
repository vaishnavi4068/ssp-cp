"""Canonical JSON hashing, intake normalization, naming validation, and label normalization (`ADR-GLB-003`, `ADR-GLB-006`, `ADR-GLB-008`, `ADR-SVC-001`, `specs/naming/naming-spec.json`)."""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from typing import Any

# APM ID format per user decision: 'APM' followed by exactly 5 digits (case-insensitive input -> lowercase apm\d{5})
APM_ID_INPUT_PATTERN = re.compile(r"(?i)^APM\d{5}$")
APM_ID_NORMALIZED_PATTERN = re.compile(r"^apm\d{5}$")

LOB_PATTERN = re.compile(r"^([a-z][a-z0-9]{1,5}|<lob>)$")
APP_PATTERN = re.compile(r"^[a-z][a-z0-9]{1,11}$")
KEBAB_PURPOSE_PATTERN = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")
SNAKE_PURPOSE_PATTERN = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$")
SUFFIX_PATTERN = re.compile(r"^[a-z0-9]{4}$")
SUFFIX_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789"

LEGACY_ENV_MAP = {
    "sandbox": "nonprod",
    "dev": "nonprod",
    "qa": "nonprod",
    "test": "nonprod",
    "pdev": "nonprod",
    "pqa": "nonprod",
    "preprod": "nonprod",
    "nonprod": "nonprod",
    "prod": "prod",
}

RESERVED_PURPOSE_WORDS = {
    "non-prod",
    "nonprod",
    "prod",
    "sandbox",
    "dev",
    "qa",
    "test",
    "pdev",
    "pqa",
    "preprod",
    "restricted",
    "unrestricted",
}

FORBIDDEN_GCS_PREFIXES = ("goog",)
FORBIDDEN_GCS_SUBSTRINGS = ("google", "g00gle")

MANDATORY_LABELS = (
    "sppappid",
    "costcenter",
    "environmenttype",
    "primarylob",
    "datasensitivity",
    "owner",
    "provisionedby",
    "idp_resource_id",
)

FORBIDDEN_SECRET_KEYS = {
    "password",
    "passwd",
    "client_secret",
    "private_key",
    "secret_value",
    "api_key",
    "token",
}


def canonical_sha256(doc: Any) -> str:
    """Compute SHA-256 hex digest over canonical JSON (`sort_keys=True, separators=(',', ':')`, UTF-8)."""
    raw = json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def k8s_job_name(operation_id: str, phase: str) -> str:
    """Deterministic Kubernetes Job name matching SQL `idp.k8s_job_name(operation_id, phase)` (`ADR-AUT-001`)."""
    digest = hashlib.sha256(operation_id.encode("utf-8")).hexdigest()[:20]
    return f"tf-{phase.replace('_', '-')}-{digest}"


def validate_and_normalize_apm_id(raw_apm_id: str) -> str:
    """Validate APM ID with `^APM\\d{5}$` (case-insensitive) and normalize to lowercase `apm\\d{5}`."""
    cleaned = raw_apm_id.strip()
    if not APM_ID_INPUT_PATTERN.match(cleaned):
        raise ValueError(
            f"NAM-APM-001: apm_id '{raw_apm_id}' is invalid; expected 'APM' followed by 5 digits (e.g. 'APM12345')"
        )
    return cleaned.lower()


def normalize_environment(raw_env: str) -> str:
    """Normalize environment codes (`sandbox`, `dev`, `qa`, `test`, `pdev`, `pqa`, `preprod` -> `nonprod`; `prod` -> `prod`)."""
    cleaned = raw_env.strip().lower()
    if cleaned not in LEGACY_ENV_MAP:
        raise ValueError(
            f"GLB-ENV-001: environment '{raw_env}' is invalid; allowed values normalize to 'nonprod' or 'prod'"
        )
    return LEGACY_ENV_MAP[cleaned]


def normalize_data_sensitivity(raw_val: str) -> str:
    """Normalize intake data sensitivity (`restrict` -> `restricted`, `unrestrict` -> `unrestricted`)."""
    cleaned = raw_val.strip().lower()
    if cleaned in {"restrict", "restricted"}:
        return "restricted"
    if cleaned in {"unrestrict", "unrestricted", "public", "internal"}:
        return "unrestricted" if cleaned == "unrestrict" else cleaned
    return cleaned


def normalize_lob(raw_lob: str) -> str:
    return raw_lob.strip().lower()


def normalize_label_value(raw_val: str) -> str:
    """Normalize label value per `LBL-002`: lowercase, replace `[^a-z0-9_-]` with `_`, max 63 chars, drop empty.

    Preserves literal `<lob>` fixture placeholder so `specs/examples/gcs_bucket.gates.json` hashes match.
    """
    lowered = str(raw_val).lower()
    placeholder = "__lob_placeholder__"
    masked = lowered.replace("<lob>", placeholder)
    cleaned = re.sub(r"[^a-z0-9_-]", "_", masked)
    restored = cleaned.replace(placeholder, "<lob>")
    return restored[:63]


def compute_canonical_labels(
    metadata: dict[str, Any],
    resource_id: str,
    *,
    is_legacy_import: bool = False,
) -> dict[str, str]:
    """Compute the 8 mandatory labels + metadata-derived labels (`LBL-001` & `LBL-002`), dropping `environmentsubtype`."""
    user_labels = dict(metadata.get("labels") or {})
    if "environmentsubtype" in user_labels:
        raise ValueError(
            "LBL-001: 'environmentsubtype' label is dropped and forbidden everywhere; use 'environmenttype' ('nonprod' | 'prod')"
        )

    merged: dict[str, str] = {}
    for k, v in user_labels.items():
        if v is not None and str(v) != "":
            norm_v = normalize_label_value(str(v))
            if norm_v:
                merged[k.lower()] = norm_v

    derived = {
        "sppappid": normalize_label_value(metadata.get("apm_id", "")),
        "costcenter": normalize_label_value(metadata.get("cost_center", "")),
        "environmenttype": normalize_label_value(metadata.get("environment", "")),
        "primarylob": normalize_label_value(metadata.get("lob", "")),
        "datasensitivity": normalize_label_value(metadata.get("data_sensitivity", "")),
        "owner": normalize_label_value(metadata.get("owner", "")),
        "provisionedby": "idp",
        "idp_resource_id": normalize_label_value(resource_id),
        "dataclassification": normalize_label_value(metadata.get("data_classification", "")),
        "sharedemailaddress": normalize_label_value(metadata.get("shared_mailbox", "")),
        "tenancy": normalize_label_value(metadata.get("tenancy", "")),
    }
    for k, v in derived.items():
        if v:
            merged[k] = v

    if is_legacy_import:
        merged["idp_naming"] = "legacy"

    return dict(sorted(merged.items()))


def generate_random_suffix() -> str:
    return "".join(secrets.choice(SUFFIX_ALPHABET) for _ in range(4))


def build_gcs_bucket_name(lob: str, env: str, app: str, purpose_token: str, suffix: str | None = None) -> str:
    sfx = suffix or generate_random_suffix()
    return f"{lob}-{env}-{app}-{purpose_token}-{sfx}"


def validate_gcs_bucket_name(
    name: str,
    *,
    lob: str,
    env: str,
    app: str,
    action: str = "create",
    existing_name: str | None = None,
) -> tuple[bool, str | None, str | None]:
    """Validate GCS bucket name against `GCS-NAME-001`, `GCS-NAME-002`, `NAM-RSV-001`, `NAM-IMM-001`, `NAM-LEG-001`.

    Returns `(valid, rule_id, reason)`.
    """
    if action == "update" and existing_name and name != existing_name:
        return (
            False,
            "NAM-IMM-001",
            f"update request cannot rename existing resource '{existing_name}' to '{name}'",
        )

    if action == "import":
        return True, "NAM-LEG-001", None

    # Uppercase or length check first
    if name != name.lower() or len(name) > 63:
        return (
            False,
            "GCS-NAME-001",
            f"bucket name '{name}' must be lowercase and <= 63 characters",
        )

    # GCS-NAME-002: forbidden prefixes and substrings
    for prefix in FORBIDDEN_GCS_PREFIXES:
        if name.startswith(prefix):
            return False, "GCS-NAME-002", f"bucket name '{name}' starts with forbidden prefix '{prefix}'"
    for substr in FORBIDDEN_GCS_SUBSTRINGS:
        if substr in name:
            return False, "GCS-NAME-002", f"bucket name '{name}' contains forbidden substring '{substr}'"

    if env not in {"nonprod", "prod"} or not LOB_PATTERN.match(lob):
        return False, "GCS-NAME-001", f"invalid lob ('{lob}') or env ('{env}') token"

    expected_prefix = f"{lob}-{env}-{app}-"
    if not name.startswith(expected_prefix):
        return (
            False,
            "GCS-NAME-001",
            f"bucket name '{name}' does not match prefix '{expected_prefix}{{purpose}}-{{suffix}}'",
        )

    remainder = name[len(expected_prefix) :]
    if "-" not in remainder:
        return False, "GCS-NAME-001", f"bucket name '{name}' is missing 4-char random suffix"

    purpose_part, suffix_part = remainder.rsplit("-", 1)
    if not SUFFIX_PATTERN.match(suffix_part):
        return False, "GCS-NAME-001", f"bucket suffix '{suffix_part}' must be 4 lowercase alphanumeric chars"

    if purpose_part in RESERVED_PURPOSE_WORDS:
        return False, "NAM-RSV-001", f"purpose '{purpose_part}' is a reserved word"

    if not (2 <= len(purpose_part) <= 20 and KEBAB_PURPOSE_PATTERN.match(purpose_part)):
        return (
            False,
            "GCS-NAME-001",
            f"purpose '{purpose_part}' must be 2..20 char kebab-case",
        )

    return True, None, None


def validate_spanner_instance_name(
    name: str,
    *,
    lob: str,
    env: str,
    app: str,
    action: str = "create",
    existing_name: str | None = None,
) -> tuple[bool, str | None, str | None]:
    if action == "update" and existing_name and name != existing_name:
        return False, "NAM-IMM-001", "update cannot rename an existing resource"
    if action == "import":
        return True, "NAM-LEG-001", None
    if name != name.lower() or len(name) > 64 or env not in {"nonprod", "prod"} or not LOB_PATTERN.match(lob):
        return False, "SPN-NAME-001", f"spanner instance name '{name}' invalid"
    base = f"{lob}-{env}-{app}"
    if name == base:
        return True, None, None
    if not name.startswith(base + "-"):
        return False, "SPN-NAME-001", f"spanner instance name '{name}' missing '{base}' prefix"
    purpose = name[len(base) + 1 :]
    if purpose in RESERVED_PURPOSE_WORDS:
        return False, "NAM-RSV-001", f"purpose '{purpose}' is reserved"
    if not (2 <= len(purpose) <= 20 and KEBAB_PURPOSE_PATTERN.match(purpose)):
        return False, "SPN-NAME-001", f"purpose '{purpose}' is invalid"
    return True, None, None


def validate_spanner_database_name(
    name: str,
    *,
    app: str,
    action: str = "create",
    existing_name: str | None = None,
) -> tuple[bool, str | None, str | None]:
    if action == "update" and existing_name and name != existing_name:
        return False, "NAM-IMM-001", "update cannot rename an existing resource"
    if action == "import":
        return True, "NAM-LEG-001", None
    if len(name) > 30 or name != name.lower():
        return False, "SPN-NAME-002", f"database name '{name}' exceeds 30 chars or has uppercase"
    if name == app:
        return True, None, None
    if not name.startswith(app + "_"):
        return False, "SPN-NAME-002", f"database name '{name}' must equal '{app}' or '{app}_{{purpose}}'"
    purpose = name[len(app) + 1 :]
    if purpose in RESERVED_PURPOSE_WORDS:
        return False, "NAM-RSV-001", f"purpose '{purpose}' is reserved"
    if not (2 <= len(purpose) <= 17 and SNAKE_PURPOSE_PATTERN.match(purpose)):
        return False, "SPN-NAME-002", f"database purpose '{purpose}' must use snake_case"
    return True, None, None


def generate_spanner_display_name(lob: str, app: str, purpose: str | None, env: str) -> str:
    """Generate Spanner display name `{LOB} {App}[ {Purpose}] ({env})` with 30-char shortening (`SPN-NAME-003`)."""
    lob_up = lob.upper()
    app_title = app.capitalize()
    env_part = f"({env})"
    if purpose:
        words = [w.capitalize() for w in re.split(r"[\s_-]+", purpose) if w]
        while words:
            candidate = f"{lob_up} {app_title} {' '.join(words)} {env_part}"
            if len(candidate) <= 30:
                return candidate
            words.pop()
    candidate = f"{lob_up} {app_title} {env_part}"
    if len(candidate) <= 30:
        return candidate
    max_app_len = max(1, 30 - len(f"{lob_up}  {env_part}"))
    return f"{lob_up} {app_title[:max_app_len]} {env_part}"


def scan_for_secrets(payload: Any, path: str = "") -> list[str]:
    """Scan nested dict/list for secret keys (`INV-1`)."""
    found: list[str] = []
    if isinstance(payload, dict):
        for k, v in payload.items():
            cur = f"{path}/{k}"
            if str(k).lower() in FORBIDDEN_SECRET_KEYS:
                found.append(cur)
            found.extend(scan_for_secrets(v, cur))
    elif isinstance(payload, list):
        for i, item in enumerate(payload):
            found.extend(scan_for_secrets(item, f"{path}/{i}"))
    return found
