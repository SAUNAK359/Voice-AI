"""Owner-scoped MCP bridge to the durable Rizzler Work control plane.

The optional official MCP SDK is a protocol adapter, not an authorization
boundary. A trusted issuer supplies a short-lived, signed Work bearer token
to the *local stdio subprocess* at startup. No anonymous TCP listener,
user-provided MCP endpoint, unrestricted file access or tool-created grants.
"""
from __future__ import annotations

import hashlib
import os
import re
import secrets

from .contracts import DELIVERABLES
from .work_store import WorkStore

_JOB_ID = re.compile(r"^[a-f0-9]{32}$")
_SOURCE_ID = re.compile(r"^[A-Za-z0-9_-]{8,128}$")


class MCPWorkBridge:
    """Pure, testable contracts independent of transport and LLM provider."""

    def __init__(self, store: WorkStore, owner: str, *, allow_write: bool = False):
        from .work_auth import OWNER
        if not isinstance(owner, str) or not OWNER.fullmatch(owner):
            raise PermissionError("Invalid authenticated MCP owner")
        self.store, self.owner, self.allow_write = store, owner, allow_write

    def _job(self, job_id: str) -> str:
        if not isinstance(job_id, str) or not _JOB_ID.fullmatch(job_id):
            raise ValueError("Invalid job identifier")
        # All other methods query the owner-scoped ledger as well.
        return job_id

    def list_jobs(self) -> dict:
        return {"jobs": self.store.list_jobs(self.owner)}

    def status(self, job_id: str) -> dict:
        jid = self._job(job_id)
        job = self.store.get(self.owner, jid)
        steps = self.store.agent_steps(self.owner, jid)
        return {"job": job, "agents": [
            {k: v for k, v in step.items() if k != "qa_json"} for step in steps]}

    def plan(self, job_id: str) -> dict:
        return self.store.job_plan(self.owner, self._job(job_id))

    def events(self, job_id: str, after: int = 0) -> dict:
        if type(after) is not int or not 0 <= after <= 2**63 - 1:
            raise ValueError("Invalid event cursor")
        return {"events": self.store.events(self.owner, self._job(job_id), after)}

    def artifacts(self, job_id: str) -> dict:
        jid = self._job(job_id)
        job = self.store.get(self.owner, jid)
        return {"status": job["status"],
                "artifacts": self.store.artifacts(self.owner, jid)}

    def quality(self, job_id: str) -> dict:
        return self.store.quality_report(self.owner, self._job(job_id))

    def preflight(self, job_id: str) -> dict:
        jid = self._job(job_id)
        item = self.store.cognitive_preflight(self.owner, jid)
        if item is None:
            self.store.get(self.owner, jid)
            return {"job_id": jid, "status": "pending"}
        from .work_preflight import safe_summary
        return {"job_id": jid, **safe_summary(item)}

    def submit(self, objective: str, deliverables: list[str],
               upload_ids: list[str] | None = None,
               source_ids: list[str] | None = None,
               evidence_scope: str = "auto",
               source_coverage: str = "targeted",
               idempotency_key: str = "") -> dict:
        if not self.allow_write:
            raise PermissionError("MCP Work submission is disabled for this connection")
        if (not isinstance(objective, str) or not 5 <= len(objective.strip()) <= 8000
                or not isinstance(deliverables, list)
                or not 1 <= len(deliverables) <= 16
                or any(type(x) is not str or x not in DELIVERABLES for x in deliverables)
                or len(set(deliverables)) != len(deliverables)):
            raise ValueError("Invalid MCP Work objective or deliverables")
        uploads = upload_ids if upload_ids is not None else []
        sources = source_ids if source_ids is not None else []
        if (not isinstance(uploads, list) or not isinstance(sources, list)
                or len(uploads) > 4 or len(sources) > 8
                or any(not isinstance(s, str) or not _SOURCE_ID.fullmatch(s)
                       for s in uploads + sources)):
            raise ValueError("Invalid references")
        if evidence_scope not in ("auto", "uploaded_only", "external_allowed"):
            raise ValueError("Invalid evidence policy")
        if source_coverage not in ("targeted", "complete"):
            raise ValueError("Invalid coverage")
        # Explicit idempotency key enables safe replay after a network crash.
        # Without one, each actual tool invocation deliberately creates a new job.
        if idempotency_key:
            if not re.fullmatch(r"[A-Za-z0-9_-]{8,96}", idempotency_key):
                raise ValueError("Invalid idempotency key")
            idem = "mcp_" + hashlib.sha256(
                (self.owner + ":" + idempotency_key).encode()).hexdigest()[:40]
        else:
            idem = "mcp_" + secrets.token_hex(20)
        record = self.store.submit(self.owner, objective, deliverables,
                                   idem, uploads, sources, source_coverage,
                                   evidence_scope)
        return {"job": record, "status": "accepted_not_completed",
                "job_id": record["id"]}


def create_mcp_server(bridge: MCPWorkBridge):
    """Official SDK v2; stdio only. No raw external MCP calls are exposed."""
    try:
        from mcp.server.mcpserver import MCPServer
    except ImportError as exc:
        raise RuntimeError("Install Rizzler with the optional [mcp] extra") from exc

    server = MCPServer("rizzler-owner-work")

    @server.tool()
    def list_work_jobs() -> dict:
        """List only jobs owned by the authenticated MCP user."""
        return bridge.list_jobs()

    @server.tool()
    def get_work_status(job_id: str) -> dict:
        """Read durable status and specialist progress; never claim queued work finished."""
        return bridge.status(job_id)

    @server.tool()
    def get_work_plan(job_id: str) -> dict:
        """Read the validated, owned specialist DAG."""
        return bridge.plan(job_id)

    @server.tool()
    def get_work_preflight(job_id: str) -> dict:
        """Inspect approved cognitive conclusions and task requirements."""
        return bridge.preflight(job_id)

    @server.tool()
    def get_work_events(job_id: str, after: int = 0) -> dict:
        """Poll incremental, durable progress events."""
        return bridge.events(job_id, after)

    @server.tool()
    def get_work_artifacts(job_id: str) -> dict:
        """List verified final artifacts without exposing host filesystem paths."""
        return bridge.artifacts(job_id)

    @server.tool()
    def get_work_quality(job_id: str) -> dict:
        """Read independently validated completed-job quality reports."""
        return bridge.quality(job_id)

    if bridge.allow_write:
        @server.tool()
        def submit_work(objective: str, deliverables: list[str],
                        upload_ids: list[str] | None = None,
                        source_ids: list[str] | None = None,
                        evidence_scope: str = "auto",
                        source_coverage: str = "targeted",
                        idempotency_key: str = "") -> dict:
            """Submit authorized asynchronous multi-agent work. Returns queued status, NOT final results."""
            return bridge.submit(objective, deliverables, upload_ids,
                                 source_ids, evidence_scope, source_coverage,
                                 idempotency_key)
    return server


def main() -> None:
    """Private stdio MCP server; operator-only bootstrap from a trusted issuer."""
    from .work_auth import verify_token
    from .work_objects import from_environment
    from .work_store import WorkStore
    token = os.environ.get("RIZZLER_MCP_WORK_TOKEN", "")
    secret = os.environ.get("RIZZLER_MCP_SIGNING_SECRET", "")
    owner = verify_token("Bearer " + token, secret)
    root = os.environ.get("RIZZLER_WORK_ROOT", "")
    if not root:
        raise RuntimeError("RIZZLER_WORK_ROOT must be set to persistent storage")
    if os.environ.get("RIZZLER_DATABASE_URL"):
        from .work_postgres import PostgresWorkStore
        store = PostgresWorkStore(root, os.environ["RIZZLER_DATABASE_URL"],
                                  object_store=from_environment())
    else:
        store = WorkStore(root, object_store=from_environment())
    allow_write = os.environ.get("RIZZLER_MCP_ALLOW_WRITE", "0") == "1"
    create_mcp_server(MCPWorkBridge(store, owner, allow_write=allow_write)
                      ).run(transport="stdio")


if __name__ == "__main__":
    main()
