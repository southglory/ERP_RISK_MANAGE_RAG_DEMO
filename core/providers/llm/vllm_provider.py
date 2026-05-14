from __future__ import annotations
import os
from typing import AsyncIterator
from openai import AsyncOpenAI
from core.providers.base import LLMProvider, ChatMessage


class VLLMProvider(LLMProvider):
    """OpenAI-compatible provider for vLLM local server.

    Swap target: set VLLM_BASE_URL=https://api.upstage.ai/v1 and
    VLLM_MODEL=solar-pro to switch to Upstage Solar API with zero code change.
    """

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
    ) -> None:
        self.base_url = base_url or os.environ["VLLM_BASE_URL"]
        self.model = model or os.environ.get("VLLM_MODEL", "solar-10.7b-instruct")
        self.client = AsyncOpenAI(
            base_url=self.base_url,
            api_key=api_key or os.environ.get("VLLM_API_KEY", "EMPTY"),
        )

    def _to_dicts(self, messages: list[ChatMessage]) -> list[dict]:
        return [{"role": m.role, "content": m.content} for m in messages]

    async def chat(self, messages: list[ChatMessage], **kwargs) -> str:
        resp = await self.client.chat.completions.create(
            model=self.model,
            messages=self._to_dicts(messages),
            **kwargs,
        )
        return resp.choices[0].message.content

    async def chat_stream(self, messages: list[ChatMessage], **kwargs) -> AsyncIterator[str]:
        stream = await self.client.chat.completions.create(
            model=self.model,
            messages=self._to_dicts(messages),
            stream=True,
            **kwargs,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta
