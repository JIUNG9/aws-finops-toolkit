"""OpenAI LLM provider."""

from __future__ import annotations

import os

from finops.llm.base import LLMProvider, LLMResponse, register_llm


class OpenAIProvider(LLMProvider):
    """OpenAI GPT provider."""

    name = "openai"

    def __init__(self, api_key: str = "", model: str = "gpt-4o"):
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.model = model

    async def generate(self, prompt: str, system_prompt: str = "",
                       max_tokens: int = 2000, temperature: float = 0.3) -> LLMResponse:
        try:
            import openai
        except ImportError:
            raise ImportError("Install openai: pip install aws-finops-toolkit[ai]")

        client = openai.AsyncOpenAI(api_key=self.api_key)
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        response = await client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        choice = response.choices[0]
        return LLMResponse(
            content=choice.message.content or "",
            model=self.model,
            provider="openai",
            tokens_used=(response.usage.prompt_tokens + response.usage.completion_tokens) if response.usage else 0,
        )

    async def test_connection(self) -> bool:
        if not self.api_key:
            return False
        try:
            import openai
            client = openai.AsyncOpenAI(api_key=self.api_key)
            await client.chat.completions.create(
                model=self.model, max_tokens=10,
                messages=[{"role": "user", "content": "ping"}],
            )
            return True
        except Exception:
            return False


register_llm("openai", OpenAIProvider)
