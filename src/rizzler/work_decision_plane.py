"""One auditable cognitive decision vocabulary for planning, execution and QA.

Never persist arbitrary provider exceptions (which may contain secrets,
retrieved page text, personal uploads or prompt excerpts). Only known,
stable internal failure rules are sent to the decision LLM and event log.
"""
from __future__ import annotations


KNOWN_RULES={
    "Artifact IR sections or source provenance missing":"artifact_provenance_mismatch",
    "Native Word output contains raw Markdown syntax":"raw_markdown_leaked_to_word",
    "Structured Word table was rendered as plain text":"word_table_structure_lost",
    "Word document lacks substantive text":"word_content_missing",
    "PowerPoint lacks substantive slides":"presentation_insufficient_slides",
    "PowerPoint contains an empty slide":"presentation_empty_slide",
    "Workbook source metrics differ from SQL evidence":"spreadsheet_source_mismatch",
    "Original workbook cell or formula modified":"source_formula_changed",
    "Original worksheet dimensions changed":"source_sheet_modified",
    "Source workbook worksheet missing":"source_sheet_missing",
    "Unapproved workbook formula":"spreadsheet_formula_contract_invalid",
    "Recalculated formula values differ from independent arithmetic":
        "spreadsheet_recalculation_mismatch",
    "XLSX input IR contract mismatch":"spreadsheet_ir_provenance_mismatch",
    "Strict artifact QA requires LibreOffice":"office_renderer_unavailable",
    "Artifact failed QA after repair budget":"quality_repair_budget_exhausted",
    "Office page rendering failed":"office_render_failed",
    "Office page rendering exceeded time budget":"office_render_deadline",
    "Rendered page is blank or not text-readable":"rendered_page_unreadable",
    "Rendered page contains clipped/out-of-bounds words":"rendered_page_clipped",
    "Cognitive preflight exceeded storage budget":"preflight_storage_budget",
    "Graph contains forward, unknown or cyclic dependencies":"graph_dependency_invalid",
    "Rendering must wait for its selected inputs":"graph_missing_prerequisite",
    "Uploaded-only evidence scope forbids external research":"source_policy_violation",
    "The registered dataset tool supports one dataset":"dataset_capacity_limit",
}


def diagnosis(exc: BaseException) -> str:
    """Machine-readable reason with no user/provider message leakage."""
    if isinstance(exc,BaseExceptionGroup):
        for child in exc.exceptions:
            found=diagnosis(child)
            if found!="unspecified_agent_failure":
                return found
        return "unspecified_agent_failure"
    raw=str(exc)
    for marker,code in KNOWN_RULES.items():
        if raw.startswith(marker):
            return code
    if isinstance(exc,TimeoutError):
        return "provider_or_worker_timeout"
    if isinstance(exc,PermissionError):
        return "permission_denied"
    if isinstance(exc,ConnectionError):
        return "provider_transport_unavailable"
    return "unspecified_agent_failure"



def snapshot(store, owner: str, jid: str) -> dict:
    """Authoritative bounded state shared by agentic planning and recovery.

    This state contains no raw upload contents, arbitrary exception messages,
    private file paths, model reasoning traces or provider credentials.
    """
    job=store.get(owner,jid)
    plan=store.job_plan(owner,jid)
    steps=store.agent_steps(owner,jid)
    status=[]
    for row in steps[:20]:
        status.append({"agent":row["agent"],"status":row["status"],
                       "attempt":row["attempt"],
                       "diagnosis":row.get("error_code","")[:80],
                       "has_verified_checkpoint":bool(row.get("result_sha256"))})
    events=store.events(owner,jid)
    recent=[{"stage":x["stage"][:55],"message":x["message"][:120]}
            for x in events[-10:] if x["stage"] in (
                "agent_failed","agent_diagnosis","agent_completed","planning",
                "research","analysis","rendering","validating","completed")]
    approved=store.cognitive_preflight(owner,jid)
    if approved is not None:
        from .work_preflight import safe_summary
        cognitive=safe_summary(approved)
        cognitive={key:cognitive[key] for key in
                   ("goal","deliverables","evidence_policy","success_criteria",
                    "prerequisites") if key in cognitive}
    else:
        cognitive={"status":"not_yet_approved"}
    return {"state_version":1,
            "job_status":job["status"],
            "approved_requirements":cognitive,
            "active_plan":[{"agent":x["id"],"requires":x["depends_on"]}
                           for x in plan.get("steps",[])[:20]],
            "specialists":status,
            "recent_events":recent}
