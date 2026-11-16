"""Operational capabilities and missing prerequisites for the Work MVP.

This is a local configuration/installation audit, not a live provider probe.
Never expose API tokens, internal network addresses or private filesystem paths.
"""
from __future__ import annotations

import importlib.util
import os
import shutil


FORMAT_DEPS={
    "pptx":("pptx",),"docx":("docx",),"pdf":("reportlab",),
    "xlsx":("openpyxl",),"png":("matplotlib","PIL"),
    "svg":("matplotlib",),"csv":(),"json":(),"md":(),"txt":(),
    "html":(),"zip":(),
}


def assess() -> dict:
    from .work_sglang import enabled as sglang_enabled, config, SGLangProviderError
    from .work_visual import quality_mode
    from .work_worker import worker_parallelism
    backend="sglang" if sglang_enabled() else "gemini"
    model_configured=False
    issue=None
    if backend=="sglang":
        try:
            config()
            model_configured=True
        except SGLangProviderError as exc:
            issue=str(exc)
    else:
        model_configured=bool(os.environ.get("GEMINI_API_KEY"))
        if not model_configured:
            issue="gemini_key_missing"
    office=bool(shutil.which("libreoffice") or shutil.which("soffice"))
    visual=importlib.util.find_spec("fitz") is not None
    qa=quality_mode()
    outputs={}
    for fmt,names in FORMAT_DEPS.items():
        missing=[name for name in names if importlib.util.find_spec(name) is None]
        if qa!="structural" and fmt in ("docx","pptx","xlsx") and not office:
            missing.append("libreoffice")
        if qa!="structural" and fmt in ("docx","pptx","pdf") and not visual:
            missing.append("pymupdf")
        outputs[fmt]={"installed":not missing,"missing":missing}
    from .work_searxng import search_ready
    keyless = search_ready()
    return {
        "status":"configuration_only_not_live_verified",
        "work_backend":backend,
        "model_configured":model_configured,
        "model_issue":issue,
        "grounded_web_search_configured":bool(os.environ.get("GEMINI_API_KEY")) or keyless,
        "grounded_web_search_note":(
            "SearXNG discovery with pinned HTTPS source retrieval, not independent claim verification"
            if keyless else "Gemini Search attribution, not independent page fact verification"),
        "mcp_sdk_installed":importlib.util.find_spec("mcp") is not None,
        "strict_qa_mode":qa,
        "worker_concurrency":worker_parallelism(),
        "outputs":outputs,
        "external_provider_probed":False,
        "live_artifact_generation_tested":False,
    }
