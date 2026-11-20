"""V26 independent, page-aware visual critique on ACTUAL rendered pixels.

The format specialist creates artifacts; a separate multimodal Gemini critic
reads real output pages. Source verification and bounds are still independent.
The critic cannot claim source facts or authorize new tools. Critical issues
are classified as repair tasks, never silently waived or counted as proof.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

from .cognitive_json import decode_model_json

KINDS=frozenset({"pptx","docx","pdf"})
CATEGORIES=frozenset({
    "text_clipped","text_too_small","low_contrast","visual_overlap",
    "misleading_chart","illegible_table","broken_alignment",
    "redundant_layout","poor_information_hierarchy","blank_visual",
    "content_missing_from_render","color_dependency","unreadable_label",
    "weak_narrative_visual","other_readability",
})
MAX_PAGES=60
PAGES_PER_CALL=4


class VisualReviewFailure(ValueError):
    """An actual rendered page failed independent critical visual inspection."""


class VisualReviewIncomplete(ValueError):
    """Required visual review was unavailable or beyond a bounded budget."""


def validate_visual_review(data: dict,*,pages: list[int]) -> dict:
    if (not isinstance(data,dict) or set(data)!={
            "schema_version","reviewed_pages","decision","findings","summary"}
            or data["schema_version"]!=2
            or data["decision"] not in ("pass","revise")
            or data["reviewed_pages"]!=pages
            or not isinstance(data["summary"],str)
            or not 18<=len(data["summary"].strip())<=700):
        raise VisualReviewIncomplete("Malformed or partial visual review response")
    findings=data["findings"]
    if not isinstance(findings,list) or len(findings)>12:
        raise VisualReviewIncomplete("Unbounded visual findings")
    for f in findings:
        if (not isinstance(f,dict) or set(f)!={
                "page","category","severity","evidence","repair"}
                or type(f["page"]) is not int or f["page"] not in pages
                or f["category"] not in CATEGORIES
                or f["severity"] not in ("low","medium","high")
                or not isinstance(f["evidence"],str)
                or not 15<=len(f["evidence"].strip())<=460
                or not isinstance(f["repair"],str)
                or not 15<=len(f["repair"].strip())<=460):
            raise VisualReviewIncomplete("Visual reviewer provided malformed page evidence")
    if (data["decision"]=="pass" and any(
            x["severity"]=="high" for x in findings)):
        raise VisualReviewIncomplete("Critical visual defect cannot be approved")
    if (data["decision"]=="revise" and not findings):
        raise VisualReviewIncomplete("Cannot request blind visual revision")
    return data


def rasterized_pages(path: Path,kind: str,*,max_pages: int=MAX_PAGES) -> list[dict]:
    """Full-page PNG rasterization in an isolated LibreOffice invocation."""
    if kind not in KINDS or not path.is_file():
        raise VisualReviewIncomplete("Unsupported visual artifact")
    if not 1<=max_pages<=MAX_PAGES:
        raise VisualReviewIncomplete("Invalid visual inspection budget")
    try:
        import fitz
    except ImportError as exc:
        raise VisualReviewIncomplete("PyMuPDF required for real raster review") from exc
    with tempfile.TemporaryDirectory(prefix="rizzler-v26-critic-") as tmp:
        root=Path(tmp)
        target=path
        if kind!="pdf":
            office=shutil.which("libreoffice") or shutil.which("soffice")
            if not office:
                raise VisualReviewIncomplete("Office render engine unavailable")
            output=root/"pdf"
            output.mkdir()
            try:
                proc=subprocess.run(
                    [office,"--headless","--nologo","--nodefault",
                     "--nofirststartwizard",
                     "-env:UserInstallation="+(root/"profile").as_uri(),
                     "--convert-to","pdf","--outdir",str(output),str(path)],
                    capture_output=True,timeout=75,check=False)
            except subprocess.TimeoutExpired as exc:
                raise VisualReviewIncomplete("Visual render timed out") from exc
            target=output/(path.stem+".pdf")
            if proc.returncode!=0 or not target.is_file():
                raise VisualReviewIncomplete("Office failed to render document")
        result=[]
        with fitz.open(target) as doc:
            if doc.page_count<1 or doc.page_count>max_pages:
                raise VisualReviewIncomplete(
                    "Visual critic cannot honestly certify more pages than its budget")
            for index,page in enumerate(doc):
                # Moderate resolution avoids transmitting huge documents.
                pix=page.get_pixmap(
                    matrix=fitz.Matrix(.9,.9),
                    alpha=False,colorspace=fitz.csRGB)
                data=pix.tobytes("png")
                if not 100<=pix.width<=2500 or not 100<=pix.height<=2500:
                    raise VisualReviewIncomplete("Rendered page raster is unusable")
                if len(data)>2_000_000:
                    raise VisualReviewIncomplete("Rendered page exceeds bounded image cap")
                result.append({
                    "page":index+1,"png":data,
                    "pixel_sha256":hashlib.sha256(data).hexdigest(),
                    "width":pix.width,"height":pix.height})
        return result


async def inspect_actual_visual(*,path: Path,kind: str,
                                objective: str,model: str,api_key: str,
                                client=None) -> dict:
    """Send 1–4 page PNG batches to an independent vision-capable reviewer."""
    if kind not in KINDS or not api_key:
        raise VisualReviewIncomplete("No authorized multimodal visual QA")
    pages=await asyncio.to_thread(rasterized_pages,path,kind)
    owned=client is None
    if owned:
        from google import genai
        client=genai.Client(api_key=api_key)
    from google.genai import types
    from .cognitive_provider import generate_with_recovery
    decisions=[]
    try:
        for start in range(0,len(pages),PAGES_PER_CALL):
            subset=pages[start:start+PAGES_PER_CALL]
            numbers=[item["page"] for item in subset]
            instruction=(
                "You are an independent professional visual reviewer. "
                "These are actual rasterized rendered pages of an artifact "
                "created for the original user goal, not design-plan sketches. "
                "Inspect ALL submitted pages visually for readability, "
                "clipped text, visual overlap, poor hierarchy, misleading "
                "or repeated charts, tiny labels, irrelevant decoration, "
                "inconsistent alignment, and excessive filler. Be exact "
                "and nonperfunctory. Do not claim to have checked numerical "
                "truth, external websites, accessibility devices or pages "
                "not attached. Findings must cite the page number and "
                "specific visible evidence. Critical defects require a "
                "revised candidate; never silently approve unreadable pages. "
                "No new data, permissions, file modifications or source claims. "
                "Return JSON EXACTLY: "
                '{"schema_version":2,"reviewed_pages":[1],'
                '"decision":"pass|revise","findings":['
                '{"page":1,"category":"text_clipped|text_too_small|'
                'low_contrast|visual_overlap|misleading_chart|'
                'illegible_table|broken_alignment|redundant_layout|'
                'poor_information_hierarchy|blank_visual|'
                'content_missing_from_render|color_dependency|'
                'unreadable_label|weak_narrative_visual|other_readability",'
                '"severity":"low|medium|high",'
                '"evidence":"precise visual observation",'
                '"repair":"specific action for the producing specialist"}],'
                '"summary":"independent professional visual verdict"}. '
                "The reviewed_pages list MUST exactly match the page IDs "
                "supplied below, in order. Report only actual visible issues; "
                "minor aesthetic preferences must not trigger high severity. "
                "\nUser goal:\n"+objective[:2500]+
                "\nActual page identifiers:\n"+
                json.dumps(numbers))
            parts=[types.Part.from_text(text=instruction)]
            for part in subset:
                parts.append(types.Part.from_text(
                    text="Rendered document page "+str(part["page"])))
                parts.append(types.Part.from_bytes(
                    data=part["png"],mime_type="image/png"))
            response=await generate_with_recovery(
                client,role="work",model=model,
                contents=[types.Content(role="user",parts=parts)],
                timeout=100,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    max_output_tokens=3000,temperature=.12))
            try:
                decision=validate_visual_review(
                    decode_model_json(
                        getattr(response,"text","") or "",max_bytes=22000),
                    pages=numbers)
            except (ValueError,TypeError,KeyError) as exc:
                raise VisualReviewIncomplete(
                    "Model omitted or invalidated a required real page review") from exc
            decisions.append(decision)
        problems=[f for d in decisions for f in d["findings"]
                  if f["severity"]=="high"]
        summary={"kind":kind,"pages":len(pages),
                 "pixel_sha256":[x["pixel_sha256"] for x in pages],
                 "critical_findings":[
                    {"page":x["page"],"category":x["category"],
                     "severity":x["severity"]} for x in problems],
                 "model_page_reviews":len(decisions),
                 "limitations":"Model vision is a subjective critic, not factual truth "
                               "or fully certified accessibility evidence"}
        if problems:
            raise VisualReviewFailure(
                "Independent visual critic found significant rendered-page defects")
        if any(d["decision"]=="revise" for d in decisions):
            raise VisualReviewFailure(
                "Independent visual critic requested a supported layout repair")
        return {"passed":True,**summary}
    finally:
        if owned:
            await client.aio.aclose()
