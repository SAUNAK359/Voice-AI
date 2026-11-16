"""Optional SGLang inference backend for Rizzler cognitive specialist agents.

SGLang provides GPU model serving, structured decoding and tool-call parsing.
It does NOT own Rizzler's user authorization, persistent jobs, leases, file
generation or external side effects. Those stay in the existing WorkStore.
HTTP endpoints are operator-configured only and never derived from user text.
"""
from __future__ import annotations

import base64
import json
import os
import re
from urllib.parse import urlsplit


class SGLangProviderError(RuntimeError):
    """Sanitized inference failure; response bodies are never logged."""


def enabled() -> bool:
    value=os.environ.get("RIZZLER_WORK_LLM_BACKEND","gemini").strip().lower()
    if value not in ("gemini","sglang"):
        raise ValueError("RIZZLER_WORK_LLM_BACKEND must be gemini or sglang")
    return value=="sglang"


def config() -> tuple[str,str,str]:
    base=os.environ.get("RIZZLER_SGLANG_BASE_URL","http://127.0.0.1:30000/v1").strip().rstrip("/")
    model=os.environ.get("RIZZLER_SGLANG_MODEL","").strip()
    api_key=os.environ.get("RIZZLER_SGLANG_API_KEY","").strip()
    parsed=urlsplit(base)
    local=parsed.hostname in ("localhost","127.0.0.1","::1")
    if (parsed.scheme!="https" and not (parsed.scheme=="http" and local)
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or not parsed.hostname or (parsed.path not in ("/v1","/v1/"))
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/\-:]{1,180}",model)):
        raise SGLangProviderError("invalid_sglang_endpoint_or_model")
    if not local and not api_key:
        raise SGLangProviderError("remote_sglang_requires_authentication")
    return base,model,api_key


async def complete(prompt: str, *, schema: dict|None=None,
                   max_tokens: int=2000, temperature: float=0.1,
                   role: str="Rizzler specialist",
                   images: list[bytes] | None = None) -> str:
    """Async structured inference. No model-written URLs or tools executed.

    A broken inference server fails the current specialist instead of silently
    substituting a different provider or a fabricated success.
    """
    if not isinstance(prompt,str) or not prompt or len(prompt)>75000:
        raise ValueError("Invalid bounded inference prompt")
    if not 64<=max_tokens<=12000 or not 0<=temperature<=1:
        raise ValueError("Invalid inference sampling settings")
    base,model,api_key=config()
    # Respect the LLM-authored specialist reasoning tier. A deployment can
    # route high-compute specialists to a larger SGLang-served model without
    # changing the authenticated Work execution graph.
    if images is None:
        from .work_reasoning import current
        selected=(os.environ.get("RIZZLER_SGLANG_HIGH_MODEL","").strip()
                  if current()=="high" else "")
        if selected:
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/\-:]{1,180}",selected):
                raise SGLangProviderError("invalid_sglang_high_model")
            model=selected
    if images is not None:
        if (not isinstance(images,list) or not 1<=len(images)<=3 or
            any(not isinstance(img,bytes) or not img.startswith(b"\x89PNG\r\n\x1a\n")
                or len(img)>8_000_000 for img in images)):
            raise ValueError("Invalid bounded SGLang visual inputs")
        # An independent VLM may be selected without changing text specialists.
        model=os.environ.get("RIZZLER_SGLANG_VISION_MODEL",model).strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/\-:]{1,180}",model):
            raise SGLangProviderError("invalid_sglang_vision_model")
    import httpx
    parts=([{"type":"text","text":prompt}]+
           [{"type":"image_url","image_url":{"url":
             "data:image/png;base64,"+base64.b64encode(img).decode("ascii")}}
            for img in images]) if images else prompt
    body={"model":model,"messages":[
        {"role":"system","content":role+"\nRespect provided data, output schema, units, citation policy and tool permissions."},
        {"role":"user","content":parts}],
          "temperature":temperature,"max_tokens":max_tokens,"stream":False}
    if schema is not None:
        # Native SGLang XGrammar/Outlines constrained decoding.
        body["response_format"]={"type":"json_schema",
                                 "json_schema":{"name":"rizzler_specialist",
                                                "schema":schema,"strict":True}}
    headers={"Authorization":"Bearer "+(api_key or "EMPTY")}
    try:
        async with httpx.AsyncClient(timeout=None,trust_env=False,
                                     follow_redirects=False) as client:
            response=await client.post(base+"/chat/completions",json=body,
                                       headers=headers)
            if response.status_code!=200:
                raise SGLangProviderError("sglang_http_status_"+str(response.status_code))
            if len(response.content)>120000:
                raise SGLangProviderError("sglang_response_oversized")
            parsed=response.json()
            choices=parsed.get("choices",[])
            content=choices[0]["message"]["content"]
            if not isinstance(content,str) or not content.strip():
                raise SGLangProviderError("sglang_empty_response")
            return content
    except (httpx.RequestError,ValueError,KeyError,IndexError,TypeError) as exc:
        raise SGLangProviderError("sglang_transport_or_schema_error:"+type(exc).__name__) from None


async def decision(prompt: str, schema: dict, *,
                   max_tokens: int=2000, temperature: float=0.1) -> dict:
    raw=await complete(prompt,schema=schema,max_tokens=max_tokens,
                       temperature=temperature,role="Rizzler cognitive decision specialist")
    try:
        obj=json.loads(raw)
    except (TypeError,json.JSONDecodeError):
        raise SGLangProviderError("sglang_invalid_json") from None
    if type(obj) is not dict:
        raise SGLangProviderError("sglang_non_object_decision")
    return obj
