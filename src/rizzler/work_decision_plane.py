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
