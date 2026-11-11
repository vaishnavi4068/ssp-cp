"""Temporal workflow client bridge for SPP Control Plane (`ssp-cp`).

On approval of a GCS bucket request, starts the Temporal workflow `GcsBucketProvisionWorkflow`
(implemented in `ssp-workers`) on the platform Temporal server in an SPP namespace/task queue
(configurable via `TEMPORAL_ADDRESS`, `TEMPORAL_NAMESPACE`, `TEMPORAL_TASK_QUEUE`, `TEMPORAL_GCS_WORKFLOW`).
Also records workflow start receipts for testing and audit.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from .config import Settings, get_settings

logger = logging.getLogger(__name__)


@dataclass
class WorkflowStartReceipt:
    workflow_name: str
    workflow_id: str
    namespace: str
    task_queue: str
    dispatched: bool
    payload: dict[str, Any] = field(default_factory=dict)
    note: str = ""


class TemporalBridge:
    """Connects lazily to Temporal frontend and starts `GcsBucketProvisionWorkflow` on approval."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._client = None
        self.started_workflows: list[WorkflowStartReceipt] = []

    async def _get_client(self):
        if not self.settings.temporal_enabled:
            return None
        if self._client is not None:
            return self._client
        try:
            from temporalio.client import Client

            self._client = await Client.connect(
                self.settings.temporal_address,
                namespace=self.settings.temporal_namespace,
            )
            return self._client
        except Exception as exc:
            logger.warning("Temporal connection unavailable (%s); recording workflow start in offline/audit mode.", exc)
            return None

    async def start_gcs_bucket_provision_workflow(
        self,
        *,
        request_id: str,
        approval_id: str,
        resource_id: str,
        state_unit_id: str,
        project_id: str,
        action: str,
        approved_spec: dict[str, Any],
        approved_spec_sha256: str,
        triggered_by: str,
    ) -> WorkflowStartReceipt:
        workflow_name = self.settings.temporal_gcs_workflow
        workflow_id = f"req-{request_id}"
        payload = {
            "request_id": request_id,
            "approval_id": approval_id,
            "resource_id": resource_id,
            "state_unit_id": state_unit_id,
            "project_id": project_id,
            "action": action,
            "approved_spec": approved_spec,
            "approved_spec_sha256": approved_spec_sha256,
            "triggered_by": triggered_by,
            "state_bucket": self.settings.state_bucket,
            "runner_service_account": self.settings.runner_service_account,
        }

        client = await self._get_client()
        dispatched = False
        note = "temporal_disabled_or_unreachable"
        if client is not None:
            try:
                await client.start_workflow(
                    workflow_name,
                    payload,
                    id=workflow_id,
                    task_queue=self.settings.temporal_task_queue,
                )
                dispatched = True
                note = "started"
            except Exception as exc:
                if type(exc).__name__ == "WorkflowAlreadyStartedError":
                    dispatched = True
                    note = "already_started"
                else:
                    logger.warning("Failed to start Temporal workflow %s (%s): %s", workflow_name, workflow_id, exc)
                    note = f"error: {exc}"

        receipt = WorkflowStartReceipt(
            workflow_name=workflow_name,
            workflow_id=workflow_id,
            namespace=self.settings.temporal_namespace,
            task_queue=self.settings.temporal_task_queue,
            dispatched=dispatched,
            payload=payload,
            note=note,
        )
        self.started_workflows.append(receipt)
        return receipt
