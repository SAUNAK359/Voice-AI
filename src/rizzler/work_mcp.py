"""Operator-governed MCP read tools for voice and Work research.

MCP servers can perform arbitrary side effects regardless of advertised
annotations. Rizzler only exposes individually approved, read-only tools.
Server addresses and tool permissions come from trusted operator configuration,
never a model response, source document, or HTTP request.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import os
import re
from urllib.parse import urlsplit

_NAME = re.compile(r"^[a-z][a-z0-9_]{1,30}$")
_TYPES = frozenset(("str", "int", "bool"))
MAX_RESPONSE = 12000


class MCPUnavailable(RuntimeError):
    """Safe-to-log error category; tool payload and endpoint are never logged."""


@dataclass(frozen=True)
class MCPTool:
    alias: str
    name: str
    description: str
    arguments: dict[str, str]
    endpoint: str
    auth_env: str | None = None

    @property
    def identifier(self):
        return f"mcp.{self.alias}.{self.name}"


def _endpoint(url: str) -> str:
    if type(url) is not str or len(url) > 700:
        raise ValueError("MCP endpoint is not configured safely")
    parsed = urlsplit(url)
    loopback = parsed.hostname in ("127.0.0.1", "::1", "localhost")
    if (parsed.scheme != "https" and not (parsed.scheme == "http" and loopback)
        or not parsed.hostname or parsed.username or parsed.password
        or parsed.query or parsed.fragment or not parsed.path.startswith("/")
        or parsed.path.startswith("//") or parsed.hostname in
        ("metadata.google.internal", "host.docker.internal")):
        raise ValueError("MCP requires HTTPS or local loopback endpoint")
    return url


def configured() -> dict[str, MCPTool]:
    """Only operator-declared read tools are discoverable by the LLM."""
    raw = os.environ.get("RIZZLER_MCP_SERVERS_JSON", "").strip()
    if not raw:
        return {}
    if len(raw) > 24000:
        raise ValueError("MCP registry exceeds approved configuration budget")
    try:
        servers = json.loads(raw)
    except json.JSONDecodeError:
        raise ValueError("MCP registry must be valid JSON") from None
    if type(servers) is not list or len(servers) > 5:
        raise ValueError("MCP registry requires at most five servers")
    result = {}
    for server in servers:
        if (type(server) is not dict or
                not {"alias","url","tools"}.issubset(server) or
                set(server)-{"alias","url","tools","auth_env"}):
            raise ValueError("Invalid MCP server specification")
        secret_name=server.get("auth_env")
        if secret_name is not None and (
                type(secret_name) is not str or
                not re.fullmatch(r"RIZZLER_MCP_[A-Z0-9_]{4,64}",secret_name)):
            raise ValueError("MCP bearer credential must be a trusted environment variable")
        alias = server["alias"]
        if type(alias) is not str or not _NAME.fullmatch(alias):
            raise ValueError("Invalid MCP alias")
        endpoint = _endpoint(server["url"])
        tools = server["tools"]
        if type(tools) is not list or not 1 <= len(tools) <= 12:
            raise ValueError("Invalid MCP tool catalogue")
        for item in tools:
            if type(item) is not dict or set(item) != {"name","description","arguments","risk"}:
                raise ValueError("Invalid MCP tool contract")
            name, desc, args = item["name"], item["description"], item["arguments"]
            if (type(name) is not str or not _NAME.fullmatch(name)
                or type(desc) is not str or not 8 <= len(desc) <= 220
                or item["risk"] != "read_only" or type(args) is not dict
                or len(args) > 8 or any(type(k) is not str or
                    not _NAME.fullmatch(k) or v not in _TYPES
                    for k,v in args.items())):
                raise ValueError("MCP capabilities must be explicit and read-only")
            spec = MCPTool(alias,name,desc,args,endpoint,secret_name)
            if spec.identifier in result:
                raise ValueError("Duplicated MCP tool name")
            result[spec.identifier] = spec
    return result


def verify_args(arguments: dict, schema: dict[str,str]) -> None:
    if type(arguments) is not dict or set(arguments) != set(schema):
        raise ValueError("MCP tool argument names do not match approved contract")
    for key, value_type in schema.items():
        value = arguments[key]
        if value_type == "str" and (type(value) is not str or
                                    not 1 <= len(value.strip()) <= 2500):
            raise ValueError("Invalid MCP text argument")
        if value_type == "int" and (type(value) is not int or not 0 <= value <= 100):
            raise ValueError("Invalid MCP integer argument")
        if value_type == "bool" and type(value) is not bool:
            raise ValueError("Invalid MCP boolean argument")


async def _call_server(spec: MCPTool, arguments: dict) -> dict:
    """MCP v2 streamable HTTP, optional secret-based bearer credentials.

    URLs and authorization variable names are solely operator-configured.
    MCP redirects are constrained to the original HTTPS origin by the SDK.
    """
    try:
        from mcp import Client
    except ImportError as exc:
        raise MCPUnavailable("mcp_sdk_not_installed") from exc

    async def execute(client):
        found=False
        cursor=None
        for _ in range(8):
            page=await client.list_tools(cursor=cursor)
            if any(tool.name==spec.name for tool in page.tools):
                found=True
                break
            cursor=page.next_cursor
            if not cursor:
                break
        if not found:
            raise MCPUnavailable("approved_mcp_tool_not_available")
        answer=await client.call_tool(spec.name,arguments=arguments)
        if answer.is_error:
            raise MCPUnavailable("mcp_tool_reported_error")
        structured=answer.structured_content
        parts=[getattr(part,"text","") for part in answer.content or []
               if isinstance(getattr(part,"text",None),str)]
        body="\n".join(parts)
        if structured is not None and not isinstance(structured,dict):
            raise MCPUnavailable("mcp_structured_response_invalid")
        if len(body)>MAX_RESPONSE or len(json.dumps(structured or {},
                                                    default=str))>MAX_RESPONSE:
            raise MCPUnavailable("mcp_response_oversized")
        return {"text":body,"structured":structured or {}}

    try:
        if spec.auth_env:
            token=os.environ.get(spec.auth_env,"").strip()
            if not token or len(token)>4096 or "\n" in token or "\r" in token:
                raise MCPUnavailable("mcp_authentication_not_configured")
            import httpx2
            from mcp.client.streamable_http import streamable_http_client
            async with httpx2.AsyncClient(
                headers={"Authorization":"Bearer "+token},
                timeout=httpx2.Timeout(20,read=60),
                follow_redirects=False,trust_env=False
            ) as http:
                async with Client(streamable_http_client(
                        spec.endpoint,http_client=http)) as client:
                    return await execute(client)
        async with Client(spec.endpoint) as client:
            return await execute(client)
    except MCPUnavailable:
        raise
    except Exception:
        # Never leak server responses, credentials, prompts or raw documents.
        raise MCPUnavailable("mcp_transport_or_tool_failure") from None

async def invoke(identifier: str, arguments: dict, *, timeout: int = 25,
                 executor=None) -> dict:
    """No model-supplied server URLs, names, writes, or elevated permissions."""
    tools = configured()
    spec = tools.get(identifier)
    if spec is None:
        raise PermissionError("MCP capability was not approved")
    verify_args(arguments, spec.arguments)
    if not 1 <= timeout <= 60:
        raise ValueError("Invalid MCP call budget")
    try:
        result = await asyncio.wait_for(
            (executor or _call_server)(spec, arguments), timeout=timeout)
    except asyncio.TimeoutError:
        raise MCPUnavailable("mcp_call_budget_exhausted") from None
    if type(result) is not dict or set(result) != {"text","structured"}:
        raise MCPUnavailable("mcp_response_contract_invalid")
    data = result["structured"]
    if type(data) is not dict or type(result["text"]) is not str:
        raise MCPUnavailable("mcp_response_contract_invalid")
    if len(result["text"]) > MAX_RESPONSE or len(json.dumps(data,default=str)) > MAX_RESPONSE:
        raise MCPUnavailable("mcp_response_oversized")
    # Grounded provenance is distinct from an MCP server claiming "verified".
    sources = data.get("sources", [])
    if type(sources) is not list:
        sources = []
    from .research_evidence import safe_source_url
    links=[]
    for record in sources[:24]:
        raw = record if type(record) is str else record.get("url","") if type(record) is dict else ""
        url = safe_source_url(raw)
        if url and url not in links:
            links.append(url)
    return {"text":result["text"],"sources":links,
            "structured":data,"verified":False,
            "provenance":"configured_mcp_server_unverified"}
