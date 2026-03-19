"""Claude (Anthropic) LLM provider."""

from __future__ import annotations

import os

from finops.llm.base import LLMProvider, LLMResponse, register_llm


class ClaudeProvider(LLMProvider):
    """Anthropic Claude provider."""

    name = "claude"

    def __init__(self, api_key: str = "", model: str = "claude-sonnet-4-20250514"):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.model = model

    async def generate(self, prompt: str, system_prompt: str = "",
                       max_tokens: int = 2000, temperature: float = 0.3) -> LLMResponse:
        try:
            import anthropic
        except ImportError:
            raise ImportError("Install anthropic: pip install aws-finops-toolkit[ai]")

        client = anthropic.AsyncAnthropic(api_key=self.api_key)
        response = await client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
        )
        return LLMResponse(
            content=response.content[0].text,
            model=self.model,
            provider="claude",
            tokens_used=response.usage.input_tokens + response.usage.output_tokens,
        )

    async def test_connection(self) -> bool:
        if not self.api_key:
            return False
        try:
            import anthropic
            client = anthropic.AsyncAnthropic(api_key=self.api_key)
            response = await client.messages.create(
                model=self.model, max_tokens=10,
                messages=[{"role": "user", "content": "ping"}],
            )
            return True
        except Exception:
            return False


register_llm("claude", ClaudeProvider)
