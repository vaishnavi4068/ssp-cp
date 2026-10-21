"""OPA policy evaluation client for SPP Control Plane (`ssp-cp`).

Calls the internal OPA server HTTP API (`http://spp-opa.spp-policy.svc.cluster.local:8181/v1/data/...`)
at `stage = 'requested'`, `stage = 'approved'`, and `stage = 'plan'`, and persists results in
`idp.policy_evaluation` (`ADR-GLB-007`, `WI-003`).
Includes a deterministic local `opa eval` CLI fallback when the cluster OPA HTTP endpoint is unreachable
(e.g. during local/CI unit tests).
"""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy.orm import Session

from .config import Settings, get_settings
from .models import PolicyEvaluation
from .naming import canonical_sha256

logger = logging.getLogger(__name__)


@dataclass
class OpaEvaluationOutput:
    evaluation_id: str
    stage: str
    opa_package: str
    bundle_revision: str
    input_sha256: str
    decision: str
    violations: list[dict[str, Any]]
    mutations: list[dict[str, Any]]
    guardrail_trace: list[dict[str, Any]]
    computed_labels: dict[str, str]
    prerequisites: list[dict[str, Any]]
    resolved_kms_key: str


class OpaClient:
    """Evaluates Rego packages via the OPA REST API (or local `opa eval` in offline test environments)."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def _package_to_url_path(self, opa_package: str) -> str:
        return opa_package.replace(".", "/")

    def evaluate_raw(self, opa_package: str, opa_input: dict[str, Any]) -> dict[str, Any]:
        url_path = self._package_to_url_path(opa_package)
        endpoint = f"{self.settings.opa_url.rstrip('/')}/v1/data/{url_path}/result"
        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.post(endpoint, json={"input": opa_input})
                resp.raise_for_status()
                body = resp.json()
                if "result" in body and isinstance(body["result"], dict):
                    return body["result"]
        except Exception as exc:
            if not self.settings.opa_fallback_local:
                raise RuntimeError(f"OPA server evaluation failed against {endpoint}: {exc}") from exc
            logger.debug("OPA HTTP server unreachable (%s); falling back to local `opa eval`.", exc)

        return self._evaluate_via_local_opa_cli(opa_package, opa_input)

    def _evaluate_via_local_opa_cli(self, opa_package: str, opa_input: dict[str, Any]) -> dict[str, Any]:
        policy_dir = self.settings.repo_root / "policy"
        query = f"data.{opa_package}.result"
        proc = subprocess.run(
            ["opa", "eval", "-f", "json", "-d", str(policy_dir), "-I", query],
            input=json.dumps(opa_input),
            text=True,
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"opa eval failed: {proc.stderr.strip()}")
        parsed = json.loads(proc.stdout)
        expressions = parsed.get("result", [{}])[0].get("expressions", [])
        if not expressions:
            raise RuntimeError(f"opa eval returned empty expressions for {query}")
        return expressions[0]["value"]

    def evaluate_and_record(
        self,
        db: Session,
        *,
        stage: str,
        opa_package: str,
        opa_input: dict[str, Any],
        request_id: Any = None,
        revision_id: Any = None,
    ) -> tuple[PolicyEvaluation, OpaEvaluationOutput]:
        input_hash = canonical_sha256(opa_input)
        raw_res = self.evaluate_raw(opa_package, opa_input)
        decision = raw_res.get("decision", "deny")
        violations = raw_res.get("violations", [])
        mutations = raw_res.get("mutations", [])
        guardrail_trace = raw_res.get("guardrail_trace", [])
        computed_labels = raw_res.get("computed_labels", {})
        prerequisites = raw_res.get("prerequisites", [])
        resolved_kms_key = raw_res.get("resolved_kms_key", "")

        row = PolicyEvaluation(
            stage=stage,
            request_id=request_id if stage != "plan" else None,
            revision_id=revision_id if stage == "plan" else None,
            opa_package=opa_package,
            bundle_revision=self.settings.opa_bundle_revision,
            input_sha256=input_hash,
            decision=decision,
            violations=violations,
            mutations=mutations,
        )
        db.add(row)
        db.flush()

        output = OpaEvaluationOutput(
            evaluation_id=str(row.evaluation_id),
            stage=stage,
            opa_package=opa_package,
            bundle_revision=self.settings.opa_bundle_revision,
            input_sha256=input_hash,
            decision=decision,
            violations=violations,
            mutations=mutations,
            guardrail_trace=guardrail_trace,
            computed_labels=computed_labels,
            prerequisites=prerequisites,
            resolved_kms_key=resolved_kms_key,
        )
        return row, output
