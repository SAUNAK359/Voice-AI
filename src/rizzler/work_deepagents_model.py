"""Full-request Gemini admission for recursive LangChain / Deep Agents calls.

A BaseRateLimiter alone is insufficient: LangChain acquires rate tokens before
a model request but does not expose a post-inference release callback. This
adapter acquires a Rizzler Work gateway lease around the ENTIRE model
invocation, including errors and cancellation, and disables provider streaming
for these background agent calls. Voice has an independent Gemini Live path.
"""
from __future__ import annotations

import asyncio
import json


def create_gated_model(cfg):
    """Return an async-safe tool-capable Gemini model with Work admission.

    The implementation inherits the native LangChain Gemini chat model so
    bind_tools(), structured tool messages and delegated subagents all remain
    available. Every generation is admitted and released through GeminiWorkGate.
    """
    from langchain_google_genai import ChatGoogleGenerativeAI
    from .work_gemini_gateway import GeminiWorkGate

    class GatedGeminiChat(ChatGoogleGenerativeAI):
        async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
            # LangChain may invoke the model many times during one Deep Agent
            # run. Each generation receives its own full-duration lease.
            budget = min(60000, sum(len(str(getattr(m, "content", "")))
                                    for m in messages) +
                         len(json.dumps(kwargs, default=str)) // 2)
            gate = GeminiWorkGate()
            async def call(model):
                # Keep a single configured model per recursive generation.
                # Model selection for the native Gemini gateway is separate.
                if model != self.model:
                    raise ValueError("Gated recursive Work model mismatch")
                return await super(GatedGeminiChat, self)._agenerate(
                    messages, stop=stop, run_manager=run_manager, **kwargs)
            return await gate.run(
                (self.model,), call, prompt_characters=budget,
                max_output_tokens=2500)

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            # Synchronous tool/model paths must also receive a full request
            # admission lease. Never call asyncio.run from a running event loop.
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                return asyncio.run(self._agenerate(
                    messages, stop=stop, run_manager=None, **kwargs))
            raise RuntimeError(
                "Rizzler Deep Agents requires async model invocation")

    return GatedGeminiChat(
        model=cfg.gemini_model,
        google_api_key=cfg.gemini_api_key,
        temperature=0.1,
        max_retries=0,
        timeout=cfg.request_timeout,
        disable_streaming=True,
        rate_limiter=None,
    )
